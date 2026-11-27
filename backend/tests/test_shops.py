"""Shop template: merchants provision isolated shops; every shop is served by one dispatcher."""
import secrets

import pytest
from fastapi.testclient import TestClient

from backend.api import Settings, create_app
from backend.catalog import is_shop_stack, shop_stack_ids, stack_definition
from backend.retail_seed import BLOOM_CATALOG
from backend.shops import ShopError, ShopRequest


def make_mall(tmp_path, quota=5):
    app = create_app(Settings(
        tmp_path / "securecloud.sqlite", retail_database=tmp_path / "retail.sqlite",
        origin="http://testserver", secure_cookie=False, marketplace=True, shop_quota=quota,
    ))
    app.state.retail_store.seed_catalog()
    app.state.bloom_store.seed_catalog(BLOOM_CATALOG)
    password = secrets.token_urlsafe(18)
    app.state.store.create_user("operator", password, administrator=True)
    users = {email: app.state.accounts.create_user(email, password, "Demo User") for email in ("maya@example.com", "ravi@example.com")}
    return app, password, users


def signed_in(app, email, password):
    api = TestClient(app, headers={"Origin": "http://testserver"})
    response = api.post("/api/shops/northstar/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    api.headers["X-CSRF-Token"] = response.json()["csrf"]
    return api


def request(slug="terra-pots", **overrides):
    values = dict(slug=slug, name="Terra Pots", tagline="Handmade planters", hero_title="Grow something lovely.",
                  hero_text="Clay planters thrown by hand in Pune.", theme="forest", categories=["Planters", "Saucers"])
    return ShopRequest(**{**values, **overrides})


def test_fixed_shops_are_listed_and_served_by_the_dispatcher(tmp_path):
    app, _, _ = make_mall(tmp_path)
    api = TestClient(app)
    listed = api.get("/api/mall/shops").json()
    assert [shop["slug"] for shop in listed["items"]] == ["northstar", "bloom"]
    assert listed["quota"] == {"used": 2, "limit": 5}
    assert all(shop["state"] == "live" for shop in listed["items"])
    legacy = {p["id"] for p in api.get("/api/retail/products").json()["items"]}
    assert {p["id"] for p in api.get("/api/shops/northstar/products").json()["items"]} == legacy
    assert api.get("/api/shops/nope/products").status_code == 404


def test_signup_records_the_same_persisted_provisioning_as_the_portal(tmp_path):
    app, password, users = make_mall(tmp_path)
    shops = app.state.shops
    shop = shops.create({"user_id": users["maya@example.com"]["id"]}, request())
    assert shop["slug"] == "terra-pots" and is_shop_stack(shop["stack_id"]) and shop["stack_id"] in shop_stack_ids()
    definition = stack_definition(shop["stack_id"])
    assert [s.id for s in definition.services] == ["terra-pots-web", "terra-pots-api", "terra-pots-database"]
    with app.state.store.connect() as db:
        deployment = db.execute("SELECT * FROM stack_deployments WHERE tenant_id=?", (shop["tenant_id"],)).fetchone()
        operation = db.execute("SELECT * FROM stack_operations WHERE stack_deployment_id=?", (deployment["id"],)).fetchone()
        names = [row[0] for row in db.execute("SELECT name FROM workloads WHERE stack_deployment_id=? ORDER BY name", (deployment["id"],))]
        audit = db.execute("SELECT actor,action FROM audit WHERE tenant_id=?", (shop["tenant_id"],)).fetchone()
    assert operation["action"] == "deploy" and operation["status"] == "queued"
    assert names == ["terra-pots-api", "terra-pots-database", "terra-pots-web"]
    assert audit["action"] == "shop.provision.requested" and audit["actor"].startswith("merchant:")
    state = shops.state(shop)  # nothing is faked: still provisioning until the reconciler runs
    assert state["state"] == "provisioning" and {s["observed"] for s in state["steps"]} == {"pending"}


def test_merchant_owns_only_their_shop_and_data_is_isolated(tmp_path):
    app, password, users = make_mall(tmp_path)
    app.state.shops.create({"user_id": users["maya@example.com"]["id"]}, request())
    maya, ravi = signed_in(app, "maya@example.com", password), signed_in(app, "ravi@example.com", password)
    assert maya.get("/api/shops/terra-pots/auth/session").json()["user"]["role"] == "owner"
    assert maya.get("/api/shops/terra-pots/admin/orders").status_code == 200
    assert maya.get("/api/shops/northstar/admin/orders").status_code == 403
    assert ravi.get("/api/shops/terra-pots/admin/orders").status_code == 403
    assert ravi.get("/api/shops/terra-pots/products").json()["items"] == []  # its own empty catalogue
    assert maya.get("/api/mall/me").json()["shops"][0]["slug"] == "terra-pots"
    assert ravi.get("/api/mall/shops/terra-pots/status").status_code == 404  # only the owner sees provisioning


@pytest.mark.parametrize("overrides, message", [
    ({"slug": "admin"}, "reserved"), ({"slug": "Bad Slug"}, "lowercase"), ({"theme": "neon"}, "looks"),
    ({"categories": []}, "categories"), ({"name": "x"}, "Name"),
])
def test_invalid_shop_requests_are_rejected(tmp_path, overrides, message):
    app, _, users = make_mall(tmp_path)
    with pytest.raises(ShopError, match=message):
        app.state.shops.create({"user_id": users["maya@example.com"]["id"]}, request(**overrides))


def test_quota_one_shop_per_merchant_and_unique_addresses(tmp_path):
    app, _, users = make_mall(tmp_path, quota=3)
    shops = app.state.shops
    shops.create({"user_id": users["maya@example.com"]["id"]}, request())
    with pytest.raises(ShopError, match="already own"):
        shops.create({"user_id": users["maya@example.com"]["id"]}, request(slug="second-shop", name="Second"))
    with pytest.raises(ShopError, match="limit of 3"):
        shops.create({"user_id": users["ravi@example.com"]["id"]}, request(slug="ravi-shop", name="Ravi"))


def test_signup_endpoint_requires_a_session_and_the_lab(tmp_path):
    app, password, _ = make_mall(tmp_path)
    body = {"slug": "terra-pots", "name": "Terra Pots", "tagline": "Handmade planters", "hero_title": "Grow.",
            "hero_text": "Clay planters.", "theme": "forest", "categories": ["Planters"]}
    anonymous = TestClient(app, headers={"Origin": "http://testserver"})
    assert anonymous.post("/api/mall/shops", json=body).status_code == 401
    maya = signed_in(app, "maya@example.com", password)
    assert maya.post("/api/mall/shops", json=body).status_code == 503  # no Kubernetes lab in unit tests


class FakeCluster:
    """Reports the namespace as still terminating once, then gone, like Kubernetes."""
    def __init__(self):
        self.calls = []

    def delete_shop_namespace(self, tenant_id):
        self.calls.append(tenant_id)
        return "deleting" if len(self.calls) == 1 else "deleted"


def provider_client(app, password):
    user = app.state.accounts.create_user("sc@example.com", password, "Provider")
    app.state.accounts.grant(user["id"], "securecloud", "provider")
    return signed_in(app, "sc@example.com", password)


def test_provider_removes_a_shop_only_after_the_cluster_confirms(tmp_path):
    app, password, users = make_mall(tmp_path)
    shop = app.state.shops.create({"user_id": users["maya@example.com"]["id"]}, request())
    provider, maya = provider_client(app, password), signed_in(app, "maya@example.com", password)
    assert maya.post("/api/provider/admin/shops/terra-pots/remove", json={"confirm": "terra-pots"}).status_code == 403
    assert provider.post("/api/provider/admin/shops/terra-pots/remove", json={"confirm": "terra"}).status_code == 422
    assert provider.post("/api/provider/admin/shops/northstar/remove", json={"confirm": "northstar"}).status_code == 409
    removed = provider.post("/api/provider/admin/shops/terra-pots/remove", json={"confirm": "terra-pots"})
    assert removed.status_code == 202 and removed.json()["state"] == "removing"
    assert TestClient(app).get("/api/shops/terra-pots/products").status_code == 404  # closed to customers at once

    cluster = FakeCluster()
    app.state.shops.reconcile_deletions(cluster)
    assert app.state.shops.get("terra-pots")["status"] == "deleting"  # Kubernetes still terminating
    app.state.shops.reconcile_deletions(cluster)
    assert app.state.shops.get("terra-pots") is None and cluster.calls == [shop["tenant_id"]] * 2
    assert app.state.accounts.role(users["maya@example.com"]["id"], "terra-pots") == "customer"  # owner role revoked
    assert app.state.shops.usage() == {"used": 2, "limit": 5}  # quota freed
    with app.state.store.connect() as db:
        actions = [row[0] for row in db.execute("SELECT action FROM audit WHERE tenant_id=? ORDER BY id", (shop["tenant_id"],))]
        observed = {row[0] for row in db.execute("SELECT observed FROM workloads WHERE tenant_id=?", (shop["tenant_id"],))}
    assert actions[-2:] == ["shop.delete.requested", "shop.deleted"] and observed == {"deleted"}


def test_a_shop_under_investigation_cannot_be_removed(tmp_path):
    app, password, users = make_mall(tmp_path)
    shop = app.state.shops.create({"user_id": users["maya@example.com"]["id"]}, request())
    with app.state.store.connect() as db:
        db.execute("UPDATE workloads SET quarantined=1 WHERE tenant_id=? AND name='terra-pots-api'", (shop["tenant_id"],))
    with pytest.raises(ShopError, match="Resolve it first"):
        app.state.shops.request_delete("terra-pots", "provider:test", "terra-pots")


def _png_data_url(color=(30, 120, 60)):
    import base64
    from io import BytesIO
    from PIL import Image
    buffer = BytesIO()
    Image.new("RGB", (40, 30), color).save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def test_owner_uploads_a_product_photo_that_is_re_encoded_and_served(tmp_path):
    app, password, users = make_mall(tmp_path)
    app.state.shops.create({"user_id": users["maya@example.com"]["id"]}, request())
    maya, ravi = signed_in(app, "maya@example.com", password), signed_in(app, "ravi@example.com", password)
    assert ravi.post("/api/shops/terra-pots/admin/media", json={"data": _png_data_url()}).status_code == 403
    uploaded = maya.post("/api/shops/terra-pots/admin/media", json={"data": _png_data_url()})
    assert uploaded.status_code == 201, uploaded.text
    path = uploaded.json()["path"]
    assert path.startswith("/api/shops/terra-pots/media/") and path.endswith(".webp")
    served = TestClient(app).get(path)
    assert served.status_code == 200 and served.headers["content-type"] == "image/webp" and served.content[8:12] == b"WEBP"
    product = {"sku": "TP-PLA-00001", "name": "Planter", "description": "Clay planter.", "price_minor": 50000,
               "stock_quantity": 3, "published": True, "image_path": path}
    assert maya.post("/api/shops/terra-pots/admin/products", json=product).status_code == 201


def test_uploads_and_image_paths_are_validated(tmp_path):
    app, password, users = make_mall(tmp_path)
    app.state.shops.create({"user_id": users["maya@example.com"]["id"]}, request())
    maya = signed_in(app, "maya@example.com", password)
    fake = "data:image/png;base64," + __import__("base64").b64encode(b"<svg onload=alert(1)>" * 4).decode()
    assert maya.post("/api/shops/terra-pots/admin/media", json={"data": fake}).status_code == 422
    assert maya.post("/api/shops/terra-pots/admin/media", json={"data": "data:image/svg+xml;base64,PHN2Zz4="}).status_code in (415, 422)
    product = {"sku": "TP-PLA-00002", "name": "Planter", "description": "Clay planter.", "price_minor": 50000,
               "stock_quantity": 3, "published": True}
    for bad in ("https://evil.example/pixel.png", "/api/shops/northstar/media/" + "a" * 32 + ".webp", "/products/../x.webp"):
        assert maya.post("/api/shops/terra-pots/admin/products", json={**product, "image_path": bad}).status_code == 422
    assert maya.post("/api/shops/terra-pots/admin/products", json={**product, "image_path": "/products/lamp.webp"}).status_code == 201
    assert TestClient(app).get("/api/shops/terra-pots/media/../../secret.webp").status_code == 404


def test_public_guest_can_look_and_use_the_console_but_never_change_shops(tmp_path, monkeypatch):
    monkeypatch.setenv("SECURECLOUD_GUEST_LOGIN", "guest@example.com:published-on-purpose")
    app, password, users = make_mall(tmp_path)
    app.state.shops.create({"user_id": users["maya@example.com"]["id"]}, request())
    guest_user = app.state.accounts.create_user("guest@example.com", password, "Guest Reviewer")
    app.state.accounts.grant(guest_user["id"], "securecloud", "guest")
    guest = signed_in(app, "guest@example.com", password)

    assert TestClient(app).get("/api/mall/guest").json() == {"email": "guest@example.com", "password": "published-on-purpose"}
    console = guest.post("/api/provider/auth/login", json={"email": "guest@example.com", "password": password}).json()
    assert console["user"]["role"] == "owner"  # the provider console admits the guest
    guest.headers["X-CSRF-Token"] = console["csrf"]
    assert guest.get("/api/provider/admin/shops").status_code == 200           # sees every shop
    assert guest.get("/api/provider/admin/platform/services").status_code != 403  # console views open
    for path, body in (("terra-pots/remove", {"confirm": "terra-pots"}), ("terra-pots/mode", {"mode": "protect"}),
                       ("terra-pots/pause", {"confirm": "terra-pots"}), ("terra-pots/resume", {"confirm": "terra-pots"})):
        refused = guest.post(f"/api/provider/admin/shops/{path}", json=body)
        assert refused.status_code == 403 and "guest" in refused.json()["detail"], path
    assert guest.post("/api/mall/shops", json={}).status_code in (403, 422)
    assert app.state.shops.get("terra-pots")["status"] == "active"


def test_guest_login_endpoint_is_absent_unless_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("SECURECLOUD_GUEST_LOGIN", raising=False)
    app, _, _ = make_mall(tmp_path)
    assert TestClient(app).get("/api/mall/guest").status_code == 404


def test_older_account_databases_are_migrated_to_allow_the_guest_role(tmp_path):
    import sqlite3
    from backend.retail.accounts import AccountStore
    path = tmp_path / "accounts.sqlite"
    store = AccountStore(path)
    user = store.create_user("old@example.com", secrets.token_urlsafe(18), "Old Provider")
    store.grant(user["id"], "securecloud", "provider")
    with sqlite3.connect(path) as db:  # rebuild the table the way older releases created it
        db.executescript("""ALTER TABLE shop_roles RENAME TO t; CREATE TABLE shop_roles(user_id TEXT NOT NULL, shop TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN('owner','provider')), PRIMARY KEY(user_id, shop));
            INSERT INTO shop_roles SELECT * FROM t; DROP TABLE t;""")
    migrated = AccountStore(path)
    assert migrated.role(user["id"], "securecloud") == "provider"  # existing grants kept
    migrated.grant(user["id"], "reviewers", "guest")
    assert migrated.role(user["id"], "reviewers") == "guest"

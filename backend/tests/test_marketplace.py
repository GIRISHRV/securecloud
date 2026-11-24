"""Marketplace access model: one shared login, per-shop owners, provider-only security plane."""
import secrets

from fastapi.testclient import TestClient

from backend.api import Settings, create_app
from backend.retail_seed import BLOOM_CATALOG


def make_market(tmp_path):
    app = create_app(Settings(
        tmp_path / "securecloud.sqlite", retail_database=tmp_path / "retail.sqlite",
        origin="http://testserver", secure_cookie=False, marketplace=True,
    ))
    app.state.retail_store.seed_catalog()
    app.state.bloom_store.seed_catalog(BLOOM_CATALOG)
    password = secrets.token_urlsafe(18)
    accounts = app.state.accounts
    for email, shop, role in (("shopper@example.com", None, None), ("ns@example.com", "northstar", "owner"),
                              ("bl@example.com", "bloom", "owner"), ("sc@example.com", "securecloud", "provider")):
        user = accounts.create_user(email, password, "Demo User")
        if shop:
            accounts.grant(user["id"], shop, role)
    return app, password


def signed_in(app, email, password):
    api = TestClient(app, headers={"Origin": "http://testserver"})
    response = api.post("/api/bloom/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    api.headers["X-CSRF-Token"] = response.json()["csrf"]
    return api


def test_one_login_works_on_every_shop_with_per_shop_roles(tmp_path):
    app, password = make_market(tmp_path)
    shopper = signed_in(app, "shopper@example.com", password)  # signed in through Bloom
    assert shopper.get("/api/retail/auth/session").json()["user"]["role"] == "customer"
    ns_owner = signed_in(app, "ns@example.com", password)
    assert ns_owner.get("/api/retail/auth/session").json()["user"]["role"] == "owner"
    assert ns_owner.get("/api/bloom/auth/session").json()["user"]["role"] == "customer"
    assert ns_owner.get("/api/retail/admin/orders").status_code == 200
    assert ns_owner.get("/api/bloom/admin/orders").status_code == 403
    bl_owner = signed_in(app, "bl@example.com", password)
    assert bl_owner.get("/api/bloom/admin/orders").status_code == 200
    assert bl_owner.get("/api/retail/admin/orders").status_code == 403


def test_only_the_provider_reaches_the_security_plane(tmp_path):
    app, password = make_market(tmp_path)
    for email in ("shopper@example.com", "ns@example.com", "bl@example.com"):
        api = signed_in(app, email, password)
        assert api.get("/api/provider/admin/security/summary").status_code == 403
        assert api.get("/api/provider/admin/platform/services").status_code == 403
    provider = signed_in(app, "sc@example.com", password)
    assert provider.get("/api/provider/admin/security/summary").status_code == 200
    assert provider.get("/api/provider/admin/platform/services").status_code == 200
    # Shop APIs do not expose the security plane or the lab at all, and the provider gets no shop data.
    for path in ("/api/retail/admin/security/summary", "/api/bloom/admin/lab/status"):
        assert provider.get(path).status_code == 404
    assert provider.get("/api/provider/admin/orders").status_code == 404


def test_shops_keep_separate_catalogues_and_orders(tmp_path):
    app, password = make_market(tmp_path)
    shopper = signed_in(app, "shopper@example.com", password)
    ns_products = {p["id"] for p in shopper.get("/api/retail/products").json()["items"]}
    bl_products = {p["id"] for p in shopper.get("/api/bloom/products").json()["items"]}
    assert ns_products and bl_products and not ns_products & bl_products
    shopper.post("/api/bloom/cart/items", json={"product_id": "bloom-lavender", "quantity": 1})
    order = shopper.post("/api/bloom/checkout", headers={"Idempotency-Key": "bloom-order-0001"}, json={
        "recipient": "Demo User", "line1": "1 MG Road", "line2": "", "city": "Bengaluru",
        "state": "Karnataka", "postal_code": "560001", "phone": "9999999999"})
    assert order.status_code == 201 and order.json()["order_number"].startswith("BL-")
    assert [o["id"] for o in shopper.get("/api/bloom/orders").json()["items"]] == [order.json()["id"]]
    assert shopper.get("/api/retail/orders").json()["items"] == []

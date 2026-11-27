"""Shop registry: every shop on the mall is an instance of one template.

A merchant signs up, picks a name, URL slug and look, and SecureCloud provisions an isolated
tenant for them through the same persisted stack operations the portal uses: a tenant record,
a stack deployment of the allowlisted shop template, and a queued operation that the
reconciler applies (namespace, default-deny policies, workloads). Nothing here talks to
Kubernetes directly, so provisioning progress is always the reconciler's real state.

The two testbed shops (Northstar and Bloom) are registered as fixed entries so the attack
lab keeps its repeatable topology.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .catalog import register_shop_stack, shop_stack_id
from .retail.store import RetailStore
from .store import audit

SLUG = re.compile(r"^[a-z][a-z0-9-]{2,22}[a-z0-9]$")
LEARN_SECONDS = 600  # matches the detector's warm-up for new workloads
RESERVED = {"admin", "lab", "api", "shops", "mall", "shop", "provider", "securecloud", "platform", "static", "assets", "home"}
THEMES = ("navy", "forest", "plum", "sunset", "graphite")
SCHEMA = """
CREATE TABLE IF NOT EXISTS shops(
 slug TEXT PRIMARY KEY, name TEXT NOT NULL, tagline TEXT NOT NULL, hero_title TEXT NOT NULL, hero_text TEXT NOT NULL,
 theme TEXT NOT NULL, categories_json TEXT NOT NULL, owner_user_id TEXT, tenant_id TEXT, stack_id TEXT NOT NULL,
 order_prefix TEXT NOT NULL, fixed INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active', created_at REAL NOT NULL);
"""

# The testbed's fixed shops, registered so every surface can list them like any other shop.
FIXED_SHOPS = (
    dict(slug="northstar", name="Northstar", tagline="Bags and everyday carry", hero_title="Everyday goods, built to last.",
         hero_text="Bags, bottles, lamps and eyewear chosen for daily use. Fast delivery and easy returns across India.",
         theme="navy", categories=[{"code": "BAG", "name": "Bags"}, {"code": "ACC", "name": "Accessories"}, {"code": "HOM", "name": "Home"}],
         stack_id="northstar-shop-stack", order_prefix="NS"),
    dict(slug="bloom", name="Bloom", tagline="Hand-poured candles", hero_title="Slow evenings, softly lit.",
         hero_text="Soy candles, reed diffusers and gift boxes in scents inspired by Indian gardens and kitchens.",
         theme="plum", categories=[{"code": "CAN", "name": "Candles"}, {"code": "DIF", "name": "Diffusers"}, {"code": "GFT", "name": "Gift sets"}],
         stack_id="bloom-shop-stack", order_prefix="BL"),
)


class ShopError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


@dataclass
class ShopRequest:
    slug: str
    name: str
    tagline: str
    hero_title: str
    hero_text: str
    theme: str
    categories: list[str]


def validate(request: ShopRequest) -> ShopRequest:
    slug = request.slug.strip().lower()
    if not SLUG.fullmatch(slug) or "--" in slug:
        raise ShopError("Use 4-24 lowercase letters, numbers or dashes for the shop address", 422)
    if slug in RESERVED:
        raise ShopError("That shop address is reserved", 422)
    fields = {"name": (request.name, 2, 40), "tagline": (request.tagline, 2, 60),
              "hero_title": (request.hero_title, 2, 60), "hero_text": (request.hero_text, 2, 200)}
    clean = {}
    for key, (value, low, high) in fields.items():
        value = " ".join(str(value).split())
        if not low <= len(value) <= high:
            raise ShopError(f"{key.replace('_', ' ').capitalize()} must be {low}-{high} characters", 422)
        clean[key] = value
    if request.theme not in THEMES:
        raise ShopError("Pick one of the offered looks", 422)
    categories = [" ".join(str(item).split()) for item in request.categories if str(item).strip()]
    if not 1 <= len(categories) <= 6 or any(not 2 <= len(item) <= 24 for item in categories) or len(set(categories)) != len(categories):
        raise ShopError("Add 1-6 distinct categories of 2-24 characters", 422)
    return ShopRequest(slug=slug, theme=request.theme, categories=categories, **clean)


def category_codes(names: list[str]) -> list[dict]:
    """Products carry their category as the SKU's middle segment (XX-CODE-001); derive unique codes."""
    used, result = set(), []
    for name in names:
        letters = "".join(ch for ch in name.upper() if ch.isalnum()) or "CAT"
        code = letters[:3].ljust(3, "X")
        suffix = 1
        while code in used:
            code, suffix = f"{letters[:2]}{suffix}", suffix + 1
        used.add(code)
        result.append({"code": code, "name": name})
    return result


class ShopRegistry:
    def __init__(self, path: Path, *, cloud, accounts, retail_base: Path, quota: int, fixed_stores: dict[str, RetailStore]):
        self.path, self.cloud, self.accounts, self.quota = Path(path), cloud, accounts, quota
        self.retail_base = Path(retail_base)
        self._stores: dict[str, RetailStore] = dict(fixed_stores)
        with self.connect() as db:
            db.executescript(SCHEMA)
            columns = {row[1] for row in db.execute("PRAGMA table_info(shops)")}
            if "mode" not in columns:  # learn -> monitor -> protect, like NeuVector's discover/monitor/protect
                db.execute("ALTER TABLE shops ADD COLUMN mode TEXT NOT NULL DEFAULT 'monitor'")
                db.execute("ALTER TABLE shops ADD COLUMN mode_auto INTEGER NOT NULL DEFAULT 0")
            for shop in FIXED_SHOPS:
                db.execute(
                    """INSERT INTO shops(slug,name,tagline,hero_title,hero_text,theme,categories_json,stack_id,order_prefix,fixed,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,1,?) ON CONFLICT(slug) DO NOTHING""",
                    (shop["slug"], shop["name"], shop["tagline"], shop["hero_title"], shop["hero_text"], shop["theme"],
                     json.dumps(shop["categories"]), shop["stack_id"], shop["order_prefix"], time.time()))
        for shop in self.shops():
            if not shop["fixed"]:
                register_shop_stack(shop["slug"], shop["name"])  # stack definitions survive restarts

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    # ---------------------------------------------------------------- reads
    def shops(self, include_deleted: bool = False) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM shops" + ("" if include_deleted else " WHERE status!='deleted'") + " ORDER BY fixed DESC, created_at").fetchall()
        return [self._row(row) for row in rows]

    def get(self, slug: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM shops WHERE slug=? AND status!='deleted'", (slug,)).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(row) -> dict:
        shop = dict(row)
        shop["categories"] = json.loads(shop.pop("categories_json"))
        shop["fixed"] = bool(shop["fixed"])
        return shop

    def public(self, shop: dict) -> dict:
        """What any visitor may see about a shop (no owner or tenant identifiers)."""
        keys = ("slug", "name", "tagline", "hero_title", "hero_text", "theme", "categories", "fixed")
        lifecycle = {"pausing": "pausing", "paused": "paused", "resuming": "resuming", "deleting": "removing"}.get(shop["status"])
        return {**{key: shop[key] for key in keys}, "state": lifecycle or self.state(shop)["state"]}

    def store(self, slug: str) -> RetailStore | None:
        if slug in self._stores:
            return self._stores[slug]
        shop = self.get(slug)
        if shop is None:
            return None
        store = RetailStore(self.retail_base.with_name(f"{self.retail_base.stem}-shop-{slug}.sqlite"),
                            order_prefix=shop["order_prefix"], tenant_id=slug)
        self._stores[slug] = store
        return store

    def usage(self) -> dict:
        with self.connect() as db:
            used = db.execute("SELECT count(*) FROM shops WHERE status!='deleted'").fetchone()[0]
        return {"used": used, "limit": self.quota}

    def state(self, shop: dict) -> dict:
        """Provisioning state straight from the persisted stack deployment and its operation."""
        if shop["fixed"]:
            return {"state": "live", "steps": []}
        with self.cloud.connect() as db:
            deployment = db.execute("SELECT * FROM stack_deployments WHERE tenant_id=? AND stack_id=? ORDER BY created DESC LIMIT 1",
                                    (shop["tenant_id"], shop["stack_id"])).fetchone()
            if deployment is None:
                return {"state": "failed", "error": "No deployment was recorded", "steps": []}
            operation = db.execute("SELECT status,error FROM stack_operations WHERE stack_deployment_id=? ORDER BY created DESC LIMIT 1",
                                   (deployment["id"],)).fetchone()
            workloads = db.execute("SELECT name,template,observed FROM workloads WHERE stack_deployment_id=? ORDER BY name",
                                   (deployment["id"],)).fetchall()
        running = sum(1 for row in workloads if row["observed"] == "running")
        op_status = operation["status"] if operation else "unknown"
        if deployment["observed"] == "running" and running == len(workloads):
            state = "live"
        elif op_status == "failed":
            state = "failed"
        else:
            state = "provisioning"
        return {
            "state": state, "operation": op_status, "error": operation["error"] if operation else None,
            "steps": [{"name": row["name"], "template": row["template"], "observed": row["observed"]} for row in workloads],
        }

    # ---------------------------------------------------------------- removal
    def request_delete(self, slug: str, actor: str, confirm: str) -> dict:
        """Provider asks to remove a shop. Serialized and idempotent; the reconciler does the work."""
        shop = self.get(slug)
        if shop is None:
            raise ShopError("Shop not found", 404)
        if shop["fixed"]:
            raise ShopError("Testbed shops cannot be removed; the attack lab depends on them")
        if confirm != slug:
            raise ShopError("Type the shop address exactly to confirm", 422)
        if shop["status"] == "deleting":
            return shop
        if shop["status"] in ("pausing", "resuming"):
            raise ShopError("Wait for the shop to finish pausing or resuming")
        with self.cloud.connect() as db:
            locked = db.execute(
                "SELECT count(*) FROM workloads WHERE tenant_id=? AND quarantined=1 AND desired!='deleted'", (shop["tenant_id"],)).fetchone()[0]
            investigating = db.execute(
                "SELECT count(*) FROM incidents WHERE tenant_id=? AND status IN ('quarantined','review')", (shop["tenant_id"],)).fetchone()[0]
            if locked or investigating:
                raise ShopError("This shop has a locked-out workload or an incident under review. Resolve it first.")
            db.execute("UPDATE stack_deployments SET desired='deleted' WHERE tenant_id=?", (shop["tenant_id"],))
            db.execute("UPDATE workloads SET desired='deleted' WHERE tenant_id=?", (shop["tenant_id"],))
            audit(db, actor, shop["tenant_id"], "shop.delete.requested", slug)
        with self.connect() as db:
            db.execute("UPDATE shops SET status='deleting' WHERE slug=?", (slug,))
        return self.get(slug)

    def reconcile_deletions(self, infrastructure) -> None:
        """Delete requested shops' namespaces; mark a shop deleted only once Kubernetes confirms it."""
        if infrastructure is None or not hasattr(infrastructure, "delete_shop_namespace"):
            return
        with self.connect() as db:
            pending = [dict(row) for row in db.execute("SELECT slug,tenant_id FROM shops WHERE status='deleting'")]
        for shop in pending:
            try:
                state = infrastructure.delete_shop_namespace(shop["tenant_id"])
            except Exception as exc:  # recorded, retried next loop; never forced
                with self.cloud.connect() as db:
                    audit(db, "system.reconciler", shop["tenant_id"], "shop.delete.blocked", f"{shop['slug']}: {exc}", "rejected")
                continue
            if state != "deleted":
                continue
            with self.cloud.connect() as db:
                db.execute("UPDATE workloads SET observed='deleted' WHERE tenant_id=?", (shop["tenant_id"],))
                db.execute("UPDATE stack_deployments SET observed='deleted' WHERE tenant_id=?", (shop["tenant_id"],))
                audit(db, "system.reconciler", shop["tenant_id"], "shop.deleted", shop["slug"], "verified")
                open_alerts = [row[0] for row in db.execute("SELECT id FROM incidents WHERE tenant_id=? AND status='alert'", (shop["tenant_id"],))]
            for incident_id in open_alerts:  # nothing left to act on once the shop's workloads are gone
                self.cloud.update_incident_status(incident_id, "closed", {"at": time.time(), "title": "Closed: shop removed",
                                                  "detail": f"{shop['slug']} was removed by the provider; its workloads no longer exist."},
                                                  actor="system.reconciler")
            with self.accounts.connect() as db:
                db.execute("DELETE FROM shop_roles WHERE shop=?", (shop["slug"],))
            with self.connect() as db:
                db.execute("UPDATE shops SET status='deleted' WHERE slug=?", (shop["slug"],))
            self._stores.pop(shop["slug"], None)

    def provider_view(self, shop: dict) -> dict:
        """Provider console row: public fields plus owner and tenant identifiers."""
        owner = None
        if shop["owner_user_id"]:
            with self.accounts.connect() as db:
                row = db.execute("SELECT email,display_name FROM retail_users WHERE id=?", (shop["owner_user_id"],)).fetchone()
                owner = dict(row) if row else None
        public = self.public(shop)
        return {**public, "status": shop["status"], "owner": owner, "tenant_id": self.tenant_of(shop),
                "created_at": shop["created_at"], "provisioning": self.state(shop),
                "mode": self.mode(shop), "mode_auto": bool(shop["mode_auto"]), "staff": len(self.accounts.staff(shop["slug"]))}

    # ---------------------------------------------------------------- security modes
    MODES = ("learn", "monitor", "protect")

    def tenant_of(self, shop: dict) -> str | None:
        if shop["tenant_id"]:
            return shop["tenant_id"]
        with self.cloud.connect() as db:  # fixed testbed shops: find their tenant from the deployment
            row = db.execute("SELECT tenant_id FROM stack_deployments WHERE stack_id=? AND desired!='deleted' ORDER BY created DESC LIMIT 1",
                             (shop["stack_id"],)).fetchone()
        return row[0] if row else None

    def mode(self, shop: dict) -> str:
        """Effective mode. A new shop starts in learn and moves to monitor once its warm-up ends."""
        if shop["mode"] == "learn" and shop["mode_auto"] and time.time() - shop["created_at"] >= LEARN_SECONDS:
            return "monitor"
        return shop["mode"]

    def mode_for_tenant(self, tenant_id: str | None) -> str:
        for shop in self.shops():
            if self.tenant_of(shop) == tenant_id:
                return self.mode(shop)
        return "monitor"  # platform and non-shop tenants: alert, never auto-act

    def set_mode(self, slug: str, mode: str, actor: str) -> dict:
        shop = self.get(slug)
        if shop is None:
            raise ShopError("Shop not found", 404)
        if mode not in self.MODES:
            raise ShopError("Mode must be learn, monitor or protect", 422)
        with self.connect() as db:
            db.execute("UPDATE shops SET mode=?, mode_auto=0 WHERE slug=?", (mode, slug))
        with self.cloud.connect() as db:
            audit(db, actor, self.tenant_of(shop), f"shop.mode.{mode}", slug)
        return self.get(slug)

    # ---------------------------------------------------------------- pause / resume
    def request_lifecycle(self, slug: str, action: str, actor: str, confirm: str) -> dict:
        """Pause (scale to zero) or resume a template shop. Serialized, idempotent, exact-name confirmed."""
        shop = self.get(slug)
        if shop is None:
            raise ShopError("Shop not found", 404)
        if shop["fixed"]:
            raise ShopError("Testbed shops cannot be paused; the attack lab depends on them")
        if confirm != slug:
            raise ShopError("Type the shop address exactly to confirm", 422)
        wanted = {"pause": ("active", "pausing"), "resume": ("paused", "resuming")}[action]
        if shop["status"] == wanted[1]:
            return shop
        if shop["status"] != wanted[0]:
            raise ShopError(f"The shop is {shop['status']}; it cannot be {action}d now")
        with self.connect() as db:
            db.execute("UPDATE shops SET status=? WHERE slug=?", (wanted[1], slug))
        with self.cloud.connect() as db:
            audit(db, actor, shop["tenant_id"], f"shop.{action}.requested", slug)
        return self.get(slug)

    def reconcile_lifecycle(self, infrastructure) -> None:
        if infrastructure is None or not hasattr(infrastructure, "scale_shop"):
            return
        with self.connect() as db:
            pending = [dict(row) for row in db.execute("SELECT slug,tenant_id,status FROM shops WHERE status IN ('pausing','resuming')")]
        for shop in pending:
            pausing = shop["status"] == "pausing"
            try:
                state = infrastructure.scale_shop(shop["tenant_id"], 0 if pausing else 1)
            except Exception as exc:
                with self.cloud.connect() as db:
                    audit(db, "system.reconciler", shop["tenant_id"], "shop.lifecycle.blocked", f"{shop['slug']}: {exc}", "rejected")
                continue
            if state != "done":
                continue
            with self.cloud.connect() as db:
                db.execute("UPDATE workloads SET observed=? WHERE tenant_id=? AND desired!='deleted'",
                           ("stopped" if pausing else "running", shop["tenant_id"]))
                audit(db, "system.reconciler", shop["tenant_id"], "shop.paused" if pausing else "shop.resumed", shop["slug"], "verified")
            with self.connect() as db:
                db.execute("UPDATE shops SET status=? WHERE slug=?", ("paused" if pausing else "active", shop["slug"]))

    # ---------------------------------------------------------------- provisioning
    def create(self, owner: dict, request: ShopRequest) -> dict:
        request = validate(request)
        with self.connect() as db:
            if db.execute("SELECT 1 FROM shops WHERE owner_user_id=? AND status!='deleted'", (owner["user_id"],)).fetchone():
                raise ShopError("You already own a shop on this lab")
            if db.execute("SELECT 1 FROM shops WHERE slug=?", (request.slug,)).fetchone():
                raise ShopError("That shop address is taken")
        if self.usage()["used"] >= self.quota:
            raise ShopError(f"The lab is at its limit of {self.quota} live shops. Ask the provider to remove one first.")
        definition = register_shop_stack(request.slug, request.name)
        tenant, deployment_id, operation_id, now = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), time.time()
        with self.cloud.connect() as db:
            operator = db.execute("SELECT id FROM users WHERE administrator=1 AND disabled=0 ORDER BY rowid LIMIT 1").fetchone()
            if operator is None:
                raise ShopError("The platform has no operator account to run provisioning", 503)
            try:
                db.execute("INSERT INTO tenants(id,name,description,created) VALUES(?,?,?,?)",
                           (tenant, request.name, f"{request.tagline} (self-service shop)", now))
            except sqlite3.IntegrityError:
                raise ShopError("A tenant with that shop name already exists")
            db.execute("INSERT INTO memberships VALUES(?,?,?)", (tenant, operator["id"], "admin"))
            db.execute("INSERT INTO stack_deployments(id,tenant_id,name,stack_id,desired,observed,created) VALUES(?,?,?,?,?,'pending',?)",
                       (deployment_id, tenant, f"{request.slug}-shop", definition.id, "running", now))
            for component in definition.services:
                db.execute("""INSERT INTO workloads(id,tenant_id,name,template,desired,observed,created,stack_deployment_id)
                              VALUES(?,?,?,?,?,'pending',?,?)""",
                           (str(uuid.uuid4()), tenant, component.id, component.template, "running", now, deployment_id))
            db.execute("INSERT INTO stack_operations VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (operation_id, operator["id"], tenant, deployment_id, "deploy", "queued",
                        f"shop-{request.slug}", f"shop-signup:{owner['user_id']}", now, None))
            audit(db, f"merchant:{owner['user_id']}", tenant, "shop.provision.requested", deployment_id)
        with self.connect() as db:
            db.execute("""INSERT INTO shops(slug,name,tagline,hero_title,hero_text,theme,categories_json,owner_user_id,tenant_id,
                          stack_id,order_prefix,fixed,created_at,mode,mode_auto) VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?,'learn',1)""",
                       (request.slug, request.name, request.tagline, request.hero_title, request.hero_text, request.theme,
                        json.dumps(category_codes(request.categories)), owner["user_id"], tenant, shop_stack_id(request.slug),
                        order_prefix(request.slug), now))
        self.accounts.grant(owner["user_id"], request.slug, "owner")
        self.store(request.slug)
        return self.get(request.slug)


def order_prefix(slug: str) -> str:
    letters = "".join(part[0] for part in slug.split("-") if part)[:3].upper()
    return (letters if len(letters) >= 2 else slug[:2].upper())

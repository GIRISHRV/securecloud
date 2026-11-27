"""Shared accounts for every shop on the platform (one login, per-shop roles).

Users and sessions live in one provider-run store. Each shop keeps its own products,
carts and orders, and a local customer profile keyed by email so its data stays separate.
"""
from __future__ import annotations

import time

from .store import RetailStore

ROLES_SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_roles(
 user_id TEXT NOT NULL REFERENCES retail_users(id) ON DELETE CASCADE,
 shop TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN('owner','provider','guest')),
 PRIMARY KEY(user_id, shop));
CREATE TABLE IF NOT EXISTS shop_staff(
 user_id TEXT NOT NULL REFERENCES retail_users(id) ON DELETE CASCADE,
 shop TEXT NOT NULL, added_by TEXT NOT NULL, added_at REAL NOT NULL,
 PRIMARY KEY(user_id, shop));
"""


class AccountStore(RetailStore):
    def __init__(self, path):
        super().__init__(path)
        with self.connect() as db:
            db.executescript(ROLES_SCHEMA)
            table = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='shop_roles'").fetchone()[0]
            if "'guest'" not in table:  # older databases: widen the role check to allow the public guest reviewer
                db.executescript("""
                    ALTER TABLE shop_roles RENAME TO shop_roles_old;
                    CREATE TABLE shop_roles(
                     user_id TEXT NOT NULL REFERENCES retail_users(id) ON DELETE CASCADE,
                     shop TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN('owner','provider','guest')),
                     PRIMARY KEY(user_id, shop));
                    INSERT INTO shop_roles SELECT user_id, shop, role FROM shop_roles_old;
                    DROP TABLE shop_roles_old;""")

    def role(self, user_id: str, shop: str) -> str:
        """owner/provider from shop_roles; invited staff manage the shop like its owner (except the team)."""
        with self.connect() as db:
            row = db.execute("SELECT role FROM shop_roles WHERE user_id=? AND shop=?", (user_id, shop)).fetchone()
            if row:
                return row["role"]
            staff = db.execute("SELECT 1 FROM shop_staff WHERE user_id=? AND shop=?", (user_id, shop)).fetchone()
        return "owner" if staff else "customer"

    def staff(self, shop: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""SELECT s.user_id,u.email,u.display_name,s.added_at FROM shop_staff s
                                 JOIN retail_users u ON u.id=s.user_id WHERE s.shop=? ORDER BY s.added_at""", (shop,)).fetchall()
        return [dict(row) for row in rows]

    def add_staff(self, shop: str, email: str, added_by: str) -> dict:
        email = self.normalize_email(email)
        with self.connect() as db:
            user = db.execute("SELECT id,email,display_name FROM retail_users WHERE email=? AND status='active'", (email,)).fetchone()
            if user is None:
                raise ValueError("No SecureCloud account uses that email. Ask them to sign up first.")
            db.execute("INSERT INTO shop_staff VALUES(?,?,?,?) ON CONFLICT(user_id,shop) DO NOTHING", (user["id"], shop, added_by, time.time()))
        return dict(user)

    def remove_staff(self, shop: str, user_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM shop_staff WHERE shop=? AND user_id=?", (shop, user_id))

    def grant(self, user_id: str, shop: str, role: str) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO shop_roles VALUES(?,?,?) ON CONFLICT(user_id,shop) DO UPDATE SET role=excluded.role",
                       (user_id, shop, role))


def local_profile(store: RetailStore, account: dict, role: str) -> str:
    """Create or refresh the shop's local profile for a shared account; returns the local user id."""
    email = account["email"]
    with store.connect() as db:
        row = db.execute("SELECT id FROM retail_users WHERE email=?", (email,)).fetchone()
        if row is None:
            db.execute("INSERT INTO retail_users VALUES(?,?,?,'!shared-account',?,?,?,'active',?)",
                       (account["user_id"], store.tenant_id, email, account["display_name"], account.get("phone") or "",
                        "owner" if role == "owner" else "customer", time.time()))
            return account["user_id"]
        db.execute("UPDATE retail_users SET display_name=?,role=?,tenant_id=? WHERE id=?",
                   (account["display_name"], "owner" if role == "owner" else "customer", store.tenant_id, row["id"]))
        return row["id"]

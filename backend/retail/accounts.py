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
 shop TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN('owner','provider')),
 PRIMARY KEY(user_id, shop));
"""


class AccountStore(RetailStore):
    def __init__(self, path):
        super().__init__(path)
        with self.connect() as db:
            db.executescript(ROLES_SCHEMA)

    def role(self, user_id: str, shop: str) -> str:
        with self.connect() as db:
            row = db.execute("SELECT role FROM shop_roles WHERE user_id=? AND shop=?", (user_id, shop)).fetchone()
        return row["role"] if row else "customer"

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

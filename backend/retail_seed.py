"""Seed the Northstar store: catalogue, optional labelled sample orders, and lab demo accounts.

Demo account credentials are read from a local, gitignored file (default
runtime/demo-accounts.env) and never stored in source. Example file:

    OWNER=admin@example.test:choose-a-password
    CUSTOMER=customer@example.test:choose-a-password

Sample shoppers use the reserved sample.northstar.test domain and cannot sign in.
No security or application events are written; those only come from real traffic.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .retail.store import RetailError, RetailStore

ROLES = {"OWNER": ("owner", "Store Admin"), "CUSTOMER": ("customer", "Demo Customer")}


def read_accounts(path: Path):
    accounts = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        email, _, password = value.strip().partition(":")
        if key.strip().upper() not in ROLES or not email or not password:
            raise SystemExit(f"{path}:{number}: expected OWNER=email:password or CUSTOMER=email:password")
        role, name = ROLES[key.strip().upper()]
        accounts.append((email.strip(), password, name, role))
    return accounts


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Northstar store data")
    parser.add_argument("--database", type=Path, default=Path("runtime/securecloud-retail-commerce.sqlite"))
    parser.add_argument("--accounts", type=Path, default=Path("runtime/demo-accounts.env"),
                        help="local file with OWNER=/CUSTOMER= lines; skipped if missing")
    parser.add_argument("--sample-orders", action="store_true", help="also create labelled sample order history")
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()
    store = RetailStore(args.database)
    products = store.seed_catalog()
    print(f"Catalogue: {len(products)} products")
    if args.accounts.is_file():
        for email, password, name, role in read_accounts(args.accounts):
            try:
                _, created = store.upsert_lab_account(email, password, name, role=role)
            except RetailError as exc:
                raise SystemExit(f"{email}: {exc}")
            print(f"{'Created' if created else 'Reset'} lab {role} account {email}")
        print("Lab demo accounts may use short passwords. Never reuse them outside this local lab.")
    else:
        print(f"No accounts file at {args.accounts}; demo accounts unchanged")
    if args.sample_orders:
        print(f"Sample orders created: {store.seed_sample_history(days=args.days)} (0 means already seeded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

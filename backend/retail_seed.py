"""Seed the marketplace: both shops' catalogues, labelled sample orders, and shared demo accounts.

Demo account credentials are read from a local, gitignored file (default
runtime/demo-accounts.env) and never stored in source. Example file:

    CUSTOMER=customer@example.test:choose-a-password
    NORTHSTAR_OWNER=owner@example.test:choose-a-password
    BLOOM_OWNER=bloom-owner@example.test:choose-a-password
    PROVIDER=provider@example.test:choose-a-password

Accounts are shared by every shop (one login); each line grants that shop's owner role
or the provider console role. Sample shoppers use reserved .test domains and cannot sign in.
No security or application events are written; those only come from real traffic.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from .retail.accounts import AccountStore
from .retail.store import RetailError, RetailStore

# key -> (display name, shop, role granted in the shared account store)
ROLES = {
    "CUSTOMER": ("Demo Customer", None, None),
    "NORTHSTAR_OWNER": ("Northstar Owner", "northstar", "owner"),
    "BLOOM_OWNER": ("Bloom Owner", "bloom", "owner"),
    "PROVIDER": ("SecureCloud Provider", "securecloud", "provider"),
    "OWNER": ("Northstar Owner", "northstar", "owner"),  # older single-shop files
}

BLOOM_CATALOG = [
    ("bloom-lavender", "BL-CAN-101", "Lavender Calm Candle", "Hand-poured soy wax with French lavender. 40-hour burn.", 49900, 40, "/products/bloom/lavender.svg"),
    ("bloom-sandalwood", "BL-CAN-102", "Mysore Sandalwood Candle", "Warm sandalwood and vanilla in a ceramic jar.", 64900, 28, "/products/bloom/sandalwood.svg"),
    ("bloom-jasmine", "BL-CAN-103", "Night Jasmine Candle", "Fresh jasmine blooms with a hint of citrus.", 54900, 35, "/products/bloom/jasmine.svg"),
    ("bloom-rose", "BL-CAN-104", "Rose Garden Candle", "Damask rose and soft musk. Cotton wick.", 59900, 22, "/products/bloom/rose.svg"),
    ("bloom-coffee", "BL-CAN-105", "Filter Coffee Candle", "Roasted coffee and jaggery for slow mornings.", 44900, 30, "/products/bloom/coffee.svg"),
    ("bloom-diffuser", "BL-DIF-201", "Eucalyptus Reed Diffuser", "Eucalyptus and mint reed diffuser, 100 ml.", 79900, 18, "/products/bloom/diffuser.svg"),
    ("bloom-tealights", "BL-CAN-106", "Citrus Tealight Set", "Twelve orange-peel tealights for everyday glow.", 29900, 60, "/products/bloom/tealights.svg"),
    ("bloom-giftbox", "BL-GFT-301", "Bloom Gift Box", "Three mini candles and a matchbox in a keepsake box.", 129900, 15, "/products/bloom/giftbox.svg"),
]


def read_accounts(path: Path):
    accounts = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        email, _, password = value.strip().partition(":")
        if key.strip().upper() not in ROLES or not email or not password:
            raise SystemExit(f"{path}:{number}: expected one of {', '.join(ROLES)}=email:password")
        accounts.append((key.strip().upper(), email.strip(), password))
    return accounts


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed marketplace shop data and shared accounts")
    parser.add_argument("--database", type=Path, default=Path("runtime/securecloud-retail-commerce.sqlite"),
                        help="Northstar shop database; Bloom and shared accounts live beside it")
    parser.add_argument("--accounts", type=Path, default=Path("runtime/demo-accounts.env"),
                        help="local file with demo account lines; skipped if missing")
    parser.add_argument("--sample-orders", action="store_true", help="also create labelled sample order history")
    parser.add_argument("--days", type=int, default=60)
    args = parser.parse_args()
    northstar = RetailStore(args.database)
    bloom = RetailStore(args.database.with_name(f"{args.database.stem}-bloom.sqlite"), order_prefix="BL", tenant_id="bloom")
    shared = AccountStore(args.database.with_name(f"{args.database.stem}-accounts.sqlite"))
    print(f"Northstar catalogue: {len(northstar.seed_catalog())} products")
    print(f"Bloom catalogue: {len(bloom.seed_catalog(BLOOM_CATALOG))} products")
    if args.accounts.is_file():
        public = os.environ.get("SECURECLOUD_PUBLIC") == "1"
        for key, email, password in read_accounts(args.accounts):
            if public and len(password) < 16:
                raise SystemExit(f"{key}: public deployments need passwords of at least 16 characters")
            name, shop, role = ROLES[key]
            try:
                user, created = shared.upsert_lab_account(email, password, name, role="customer")
            except RetailError as exc:
                raise SystemExit(f"{email}: {exc}")
            if shop:
                shared.grant(user["id"], shop, role)
            print(f"{'Created' if created else 'Reset'} shared account {email}" + (f" ({role} of {shop})" if shop else ""))
        print("Lab demo accounts may use short passwords. Never reuse them outside this local lab.")
    else:
        print(f"No accounts file at {args.accounts}; demo accounts unchanged")
    if args.sample_orders:
        print(f"Northstar sample orders: {northstar.seed_sample_history(days=args.days)} (0 means already seeded)")
        print(f"Bloom sample orders: {bloom.seed_sample_history(days=args.days, customers=10, seed=41)} (0 means already seeded)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

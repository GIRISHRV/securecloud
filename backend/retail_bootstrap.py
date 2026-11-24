"""Create a local retail owner without placing credentials in command history."""
from __future__ import annotations

import argparse
from getpass import getpass
from pathlib import Path
import sqlite3

from .retail.store import RetailError, RetailStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a SecureCloud retail owner")
    parser.add_argument("--database", type=Path, default=Path("retail_data.sqlite"))
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    password = getpass("Password (14-256 characters): ")
    if password != getpass("Confirm password: "):
        parser.error("Passwords do not match")
    try:
        RetailStore(args.database).create_user(args.email, password, args.name, role="owner")
    except (RetailError, sqlite3.IntegrityError) as exc:
        parser.error(str(exc))
    print(f"Created retail owner {args.email!r} in {args.database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

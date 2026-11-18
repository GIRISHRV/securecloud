"""Create the first local administrator without exposing a password in argv."""
from __future__ import annotations

import argparse
from getpass import getpass
from pathlib import Path
import sqlite3

from .store import Store


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a SecureCloud local administrator")
    parser.add_argument("--database", type=Path, default=Path("backend_data.sqlite"))
    parser.add_argument("--username", required=True)
    args = parser.parse_args()

    password = getpass("Password (14-256 characters): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        parser.error("Passwords do not match")

    store = Store(args.database)
    try:
        store.create_user(args.username, password, administrator=True)
    except (ValueError, sqlite3.IntegrityError) as exc:
        parser.error(str(exc))
    print(f"Created local administrator {args.username!r} in {args.database}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

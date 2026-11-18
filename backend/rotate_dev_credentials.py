"""Rotate a local development password without placing it in argv or stdout."""
from __future__ import annotations

import argparse
from pathlib import Path
import secrets
import sqlite3

from argon2 import PasswordHasher


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate SecureCloud development credentials")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--login-file", type=Path, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--portal", default="http://127.0.0.1:4174/")
    args = parser.parse_args()

    password = secrets.token_urlsafe(32)
    with sqlite3.connect(args.database) as connection:
        result = connection.execute(
            "UPDATE users SET password_hash=? WHERE username=? COLLATE NOCASE AND disabled=0",
            (PasswordHasher().hash(password), args.username),
        )
        if result.rowcount != 1:
            parser.error("username must identify one enabled local user")
        connection.execute(
            "DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE username=? COLLATE NOCASE)",
            (args.username,),
        )
    args.login_file.write_text(
        f"Username: {args.username}\nPassword: {password}\nPortal: {args.portal}\n",
        encoding="utf-8",
    )
    print("Development credential rotated; secret value was not written to stdout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

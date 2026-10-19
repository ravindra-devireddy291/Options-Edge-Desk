"""Create a desk login in the local SQLite file. Password is an argument, never printed."""
from __future__ import annotations

import sys

from app.client_live import create_client


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: py -3 scripts/create_client.py <email> <password> [admin|client]")
    email = sys.argv[1].strip().lower()
    password = sys.argv[2]
    role = sys.argv[3] if len(sys.argv) > 3 else "client"
    create_client(email, password, role)
    print(email + " " + ("admin" if role == "admin" else "client"))


if __name__ == "__main__":
    main()

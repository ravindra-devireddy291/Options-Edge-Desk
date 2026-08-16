#!/usr/bin/env python3
"""Load desk .env in Python (JWT-safe) and exec uvicorn. Run inside the VPS chroot."""
from __future__ import annotations

import os
from pathlib import Path

DESK = "/root/Options-Edge-Desk"
PY = "/root/Options-Edge-Lab/.venv/bin/python3"

os.chdir(DESK)
raw = Path(".env").read_text(encoding="utf-8")
if raw.count("\n") < 2 and "\\n" in raw:
    raw = raw.replace("\\n", "\n")
for line in raw.splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ[k.strip()] = v.strip().strip('"').strip("'")
os.environ["PYTHONPATH"] = DESK
Path("logs").mkdir(exist_ok=True)
print(
    "boot",
    "token_len",
    len(os.environ.get("DHAN_ACCESS_TOKEN") or ""),
    "totp",
    bool(os.environ.get("DHAN_TOTP_SECRET")),
    "pin",
    bool(os.environ.get("DHAN_PIN")),
    "paper_auto",
    os.environ.get("DESK_PAPER_AUTO"),
    flush=True,
)
os.execvpe(
    PY,
    [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8080"],
    os.environ,
)

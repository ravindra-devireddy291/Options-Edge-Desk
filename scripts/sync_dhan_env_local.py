#!/usr/bin/env python3
"""Sync Dhan auth keys across Desk + Nifty + BN lab .env files (local)."""
from __future__ import annotations

from pathlib import Path

KEYS = ("DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN", "DHAN_PIN", "DHAN_TOTP_SECRET")
PATHS = [
    Path(r"D:\Options-Edge-Desk\.env"),
    Path(r"D:\Options-Nifty-Edge-Lab\.env"),
    Path(r"D:\Options-Edge-Lab\.env"),
]


def parse(p: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def write_keys(p: Path, keys: dict[str, str]) -> None:
    vals = parse(p)
    vals.update({k: v for k, v in keys.items() if v})
    # keep non-DHAN keys
    lines_out = []
    seen = set()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#") or not line.strip():
                lines_out.append(line)
                continue
            if "=" in line:
                k = line.split("=", 1)[0].strip()
                if k in KEYS:
                    lines_out.append(f"{k}={vals.get(k, '')}")
                    seen.add(k)
                else:
                    lines_out.append(line)
                    seen.add(k)
            else:
                lines_out.append(line)
    for k in KEYS:
        if k not in seen:
            lines_out.append(f"{k}={vals.get(k, '')}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines_out) + "\n", encoding="utf-8")


merged: dict[str, str] = {}
# Prefer desk (fresh token), then nifty, then bn
for p in PATHS:
    for k, v in parse(p).items():
        if k in KEYS and v and not merged.get(k):
            merged[k] = v

print(
    "merged:",
    {k: (len(v) if v else 0) for k, v in merged.items()},
)
for p in PATHS:
    write_keys(p, merged)
    got = parse(p)
    print(
        p.name,
        {k: ("SET" if got.get(k) else "EMPTY") for k in KEYS},
    )

#!/usr/bin/env python3
"""Push local Dhan secrets (incl. TOTP) to VPS desk .env and restart desk.

Your laptop .env is NOT visible to the VPS. This script copies the needed
keys over SSH into /root/Options-Edge-Desk/.env inside the chroot.

Reads first existing of:
  D:/Options-Edge-Desk/.env
  D:/Options-Edge-Lab/.env
  D:/Options-Nifty-Edge-Lab/.env

Required for TOTP auto-login:
  DHAN_CLIENT_ID
  DHAN_PIN
  DHAN_TOTP_SECRET

Optional:
  DHAN_ACCESS_TOKEN  (if still valid, renew works until it expires)

Usage:
  set EDGE_VPS_PASS=...
  set DESK_API_KEY=...   # match UI
  python scripts/push_dhan_secrets_vps.py
  python scripts/push_dhan_secrets_vps.py --generate   # mint token via TOTP now
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
USER = os.environ.get("EDGE_VPS_USER", "root")
PASS = os.environ.get("EDGE_VPS_PASS", "")
CHROOT = "/mnt/sys"
DESK = "/root/Options-Edge-Desk"
KEY = os.environ.get("DESK_API_KEY", "hEe5070y9VnztqB1a2aFu9wkpw4L+PxcdQDbzuJjK+c=")

LOCAL_CANDIDATES = [
    Path(r"D:\Options-Edge-Desk\.env"),
    Path(r"D:\Options-Edge-Lab\.env"),
    Path(r"D:\Options-Nifty-Edge-Lab\.env"),
]

PUSH_KEYS = (
    "DHAN_CLIENT_ID",
    "DHAN_ACCESS_TOKEN",
    "DHAN_PIN",
    "DHAN_TOTP_SECRET",
)


def _parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_local_secrets() -> tuple[Path, dict[str, str]]:
    merged: dict[str, str] = {}
    used: list[str] = []
    for p in LOCAL_CANDIDATES:
        if not p.exists():
            continue
        vals = _parse_env(p)
        used.append(str(p))
        for k in PUSH_KEYS:
            if vals.get(k) and not merged.get(k):
                merged[k] = vals[k]
    if not used:
        raise SystemExit("No local .env found in Desk/BN/Nifty lab roots")
    return Path(used[0]), merged


def run(c, cmd: str, timeout: int = 120) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace") + e.read().decode("utf-8", "replace")
    code = o.channel.recv_exit_status()
    print(f"[{code}] {cmd}\n{out}\n---", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--generate",
        action="store_true",
        help="After push, call desk /system/token/renew to mint via TOTP",
    )
    ap.add_argument("--no-restart", action="store_true", help="Write .env only")
    args = ap.parse_args()

    if not PASS:
        raise SystemExit("Set EDGE_VPS_PASS")

    src, secrets = load_local_secrets()
    client = secrets.get("DHAN_CLIENT_ID") or ""
    pin = secrets.get("DHAN_PIN") or ""
    totp = secrets.get("DHAN_TOTP_SECRET") or ""
    token = secrets.get("DHAN_ACCESS_TOKEN") or ""

    print(f"source={src}", flush=True)
    print(
        f"found client_id={bool(client)} pin={bool(pin)} totp_secret={bool(totp)} access_token={bool(token)}",
        flush=True,
    )
    if not client:
        raise SystemExit("DHAN_CLIENT_ID missing in local .env")
    if not pin or not totp:
        print(
            "WARN: DHAN_PIN / DHAN_TOTP_SECRET missing — VPS cannot auto-mint after expiry.\n"
            "Add them to D:\\Options-Edge-Desk\\.env then re-run this script.",
            flush=True,
        )

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=60, allow_agent=False, look_for_keys=False)

    run(c, "mountpoint -q /mnt/sys/proc || mount -t proc proc /mnt/sys/proc")
    remote_env = f"{CHROOT}{DESK}/.env"
    sftp = c.open_sftp()
    try:
        with sftp.file(remote_env, "r") as fh:
            text = fh.read().decode("utf-8", "replace")
    except OSError:
        text = ""
    vals: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()

    vals.update(
        {
            "DESK_API_KEY": KEY,
            "DESK_MODE": vals.get("DESK_MODE") or "paper",
            "NIFTY_LAB_ROOT": "/root/Options-Nifty-Edge-Lab",
            "BN_LAB_ROOT": "/root/Options-Edge-Lab",
            "NIFTY_CONFIG": "config/rungs/nifty_alpha.yaml",
            "BN_CONFIG": "config/rungs/bn_alpha.yaml",
            "LIVE_NIFTY": vals.get("LIVE_NIFTY") or "0",
            "LIVE_BANKNIFTY": vals.get("LIVE_BANKNIFTY") or "0",
            "DESK_LIVE_ENABLED": vals.get("DESK_LIVE_ENABLED") or "0",
            "DESK_MOCK_LOOP": vals.get("DESK_MOCK_LOOP") or "0",
            "DESK_PAPER_AUTO": vals.get("DESK_PAPER_AUTO") or "1",
            "DHAN_CLIENT_ID": client,
        }
    )
    if token:
        vals["DHAN_ACCESS_TOKEN"] = token
    if pin:
        vals["DHAN_PIN"] = pin
    if totp:
        vals["DHAN_TOTP_SECRET"] = totp

    with sftp.file(remote_env, "w") as fh:
        for k, v in vals.items():
            fh.write(f"{k}={v}\n")
    sftp.close()
    print(
        "wrote VPS desk .env keys:",
        sorted(k for k in vals if k.startswith("DHAN_") or k.startswith("DESK_") or k.startswith("LIVE_")),
        flush=True,
    )

    if not args.no_restart:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from vps_desk_restart import restart_desk

        sftp_boot = c.open_sftp()
        sftp_boot.put(str(Path(__file__).resolve().parent / "boot_desk.py"), f"{CHROOT}{DESK}/scripts/boot_desk.py")
        sftp_boot.close()
        restart_desk(lambda cmd: run(c, cmd), KEY)

    if args.generate:
        # force TOTP mint via renew endpoint (ensure_fresh with wide window)
        body = json.dumps({})
        sftp = c.open_sftp()
        with sftp.file("/tmp/renew.json", "w") as fh:
            fh.write(body)
        sftp.close()
        out = run(
            c,
            f"curl -s -H 'X-API-Key: {KEY}' -H 'Content-Type: application/json' "
            f"--data @/tmp/renew.json http://127.0.0.1:8080/api/v1/desk/system/token/renew",
        )
        print("renew:", out[:800], flush=True)
        out2 = run(
            c,
            f"curl -s -H 'X-API-Key: {KEY}' http://127.0.0.1:8080/api/v1/desk/system/token",
        )
        print("token status:", out2[:800], flush=True)

    c.close()
    print("done — VPS desk now has the secrets from your local .env", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

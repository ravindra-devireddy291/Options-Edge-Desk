#!/usr/bin/env python3
"""Deploy Options-Edge-Desk to VPS and install systemd unit.

  set EDGE_VPS_PASS=...
  python scripts/deploy_desk_vps.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PORT = int(os.environ.get("EDGE_VPS_PORT", "443"))
USER = os.environ.get("EDGE_VPS_USER", "root")
PASS = os.environ.get("EDGE_VPS_PASS", "")
if not PASS:
    raise SystemExit("Set EDGE_VPS_PASS")

# VPS now boots from a single root disk (no /mnt/sys chroot). Override if needed.
CHROOT = os.environ.get("EDGE_VPS_CHROOT", "").rstrip("/")
REMOTE = "/root/Options-Edge-Desk"
LOCAL = Path(__file__).resolve().parents[1]
PY = "/root/Options-Edge-Lab/.venv/bin/python3"

FILES = [
    "requirements.txt",
    "README.md",
    ".env.example",
    "docs/MVP_UI_API.md",
    "docs/BACKEND_REQUIREMENTS.md",
    "docs/UI_API_CONTRACT.md",
    "docs/BACKEND_BUSINESS_LOGIC.md",
    "docs/MODE_SCENARIO_MATRIX.md",
    "docs/UI_COLLAB.md",
    "docs/DESK_SNAPSHOT_WS.md",
    "docs/ACTION_PLAN_DESK.md",
    "docs/ACTION_PLAN_INDEX.md",
    "docs/README_DESK_UX_PLANS.md",
    "docs/UX_REVIEW_CRITIQUE.md",
    "docs/EXECUTION_ARMOR.md",
    "docs/UI_HANDSHAKE_LIVE_TICK.md",
    "deploy/edge-desk.service",
    "deploy/nginx-desk.conf",
    "deploy/edge-desk-host.service",
    "scripts/boot_desk.py",
    "scripts/smoke_d1_d8.py",
    "scripts/promote_lab_to_paper.py",
]


def _discover_py_tree(*roots: str) -> list[str]:
    out: list[str] = []
    for root in roots:
        base = LOCAL / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if any(part in {"__pycache__", ".venv", "graphify-out", ".cursor"} for part in path.parts):
                continue
            if root in {"app", "tests"} and path.suffix != ".py":
                continue
            if root == "deploy" and path.suffix not in {".service", ".conf", ".md", ".sh", ".timer"}:
                continue
            out.append(path.relative_to(LOCAL).as_posix())
    return out


def deploy_file_list() -> list[str]:
    """All app/test/doc/deploy files needed on VPS (keeps pace with new modules)."""
    discovered = _discover_py_tree("app", "tests", "deploy")
    # Explicit docs + scripts + roots (may overlap; unique preserve order)
    seen: set[str] = set()
    ordered: list[str] = []
    for rel in FILES + discovered:
        if rel in seen:
            continue
        seen.add(rel)
        ordered.append(rel)
    return ordered


def run(c, cmd: str, timeout: int = 180, check: bool = True) -> str:
    _, o, e = c.exec_command(cmd, timeout=timeout)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    code = o.channel.recv_exit_status()
    if check and code != 0:
        raise RuntimeError(f"{code}: {cmd}\n{out}\n{err}")
    return out + err


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PASS, timeout=60, allow_agent=False, look_for_keys=False)
    print(f"connected {HOST}:{PORT} chroot={CHROOT or '(none)'}", flush=True)
    if CHROOT:
        run(c, f"findmnt {CHROOT} || (mkdir -p {CHROOT} && mount /dev/vdb1 {CHROOT})")
    root = f"{CHROOT}{REMOTE}"
    run(
        c,
        f"mkdir -p {root}/{{app/brokers/dhan,app/books,app/research,app/runners,app/schemas,app/mock,app/execution,docs,deploy,data/audit,data/paper,data/paper_ledger,scripts,tests}}",
    )
    run(
        c,
        f"mkdir -p {CHROOT}/root/Options-Nifty-Edge-Lab/reports/shadow "
        f"{CHROOT}/root/Options-Edge-Lab/reports/shadow",
        check=False,
    )

    sftp = c.open_sftp()
    for rel in deploy_file_list():
        local = LOCAL / rel
        if not local.exists():
            print("skip", rel, flush=True)
            continue
        remote = f"{root}/{rel}"
        run(c, f"mkdir -p $(dirname {remote})", check=False)
        sftp.put(str(local), remote)
        print("scp", rel, flush=True)
    sftp.close()

    # ensure .env exists (do not overwrite secrets)
    run(
        c,
        f"test -f {root}/.env || cp {root}/.env.example {root}/.env",
        check=False,
    )
    # merge desk paths + API key; pull Dhan creds from BN lab .env if present
    desk_key = os.environ.get("DESK_API_KEY", "").strip()
    merge_py = r"""
import os,re,secrets
from pathlib import Path
desk=Path('/root/Options-Edge-Desk/.env')
bn=Path('/root/Options-Edge-Lab/.env')
text=desk.read_text() if desk.exists() else ''
vals={}
for line in text.splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k,v=line.split('=',1); vals[k.strip()]=v.strip()
want={
 'DESK_MODE':'paper',
 'NIFTY_LAB_ROOT':'/root/Options-Nifty-Edge-Lab',
 'BN_LAB_ROOT':'/root/Options-Edge-Lab',
 'NIFTY_CONFIG':'config/rungs/nifty_alpha.yaml',
 'BN_CONFIG':'config/rungs/bn_alpha.yaml',
 'DESK_PAPER_AUTO': vals.get('DESK_PAPER_AUTO') or '1',
 'DESK_PAPER_ONLY': vals.get('DESK_PAPER_ONLY') or '1',
}
# Preserve live cutover flags. Default off only when missing — never reset a live enable.
for k, default in (
    ('LIVE_NIFTY', '0'),
    ('LIVE_BANKNIFTY', '0'),
    ('DESK_LIVE_ENABLED', '0'),
    ('DESK_MOCK_LOOP', '0'),
):
    if not vals.get(k):
        want[k] = default
if not vals.get('DESK_BFF_SECRET'):
    want['DESK_BFF_SECRET']=secrets.token_urlsafe(32)
key=os.environ.get('DESK_API_KEY','').strip()
if key: want['DESK_API_KEY']=key
elif not vals.get('DESK_API_KEY') or vals.get('DESK_API_KEY') in ('','change-me-desk-api-key'):
    want['DESK_API_KEY']='change-me-desk-api-key'
if bn.exists():
    for line in bn.read_text().splitlines():
        if line.startswith('DHAN_CLIENT_ID=') or line.startswith('DHAN_ACCESS_TOKEN='):
            k,v=line.split('=',1); want[k]=v.strip()
vals.update(want)
out=[]
for k,v in vals.items():
    out.append(f'{k}={v}')
desk.write_text('\n'.join(out)+'\n')
print('env keys', sorted(vals))
"""
    # write merge helper then run (chroot only if EDGE_VPS_CHROOT set)
    sftp2 = c.open_sftp()
    helper = f"{root}/scripts/_merge_env.py"
    with sftp2.file(helper, "w") as fh:
        fh.write(merge_py)
    sftp2.close()
    env_export = f"DESK_API_KEY={desk_key} " if desk_key else ""

    def _host_or_chroot(inner: str) -> str:
        if CHROOT:
            return f"chroot {CHROOT} bash -lc '{inner}'"
        return f"bash -lc '{inner}'"

    run(
        c,
        _host_or_chroot(f"{env_export}{PY} {REMOTE}/scripts/_merge_env.py"),
        timeout=60,
        check=False,
    )
    run(
        c,
        _host_or_chroot(
            f"{PY} -m pip install -q fastapi uvicorn pyyaml pydantic websockets python-dotenv tzdata"
        ),
        timeout=300,
    )
    # Host systemd unit. SIGTERM so lifespan can snapshot paper.
    host_unit = run(
        c,
        "test -f /etc/systemd/system/edge-desk.service && echo HAS_HOST_UNIT || true",
        check=False,
    )
    if "HAS_HOST_UNIT" in host_unit:
        run(
            c,
            "systemctl daemon-reload; systemctl restart edge-desk; sleep 3; "
            "systemctl is-active edge-desk; curl -s --max-time 10 http://127.0.0.1:8080/healthz || true",
            timeout=60,
            check=False,
        )
    elif CHROOT:
        systemd_ok = run(
            c,
            f"chroot {CHROOT} bash -lc 'command -v systemctl >/dev/null && systemctl daemon-reload 2>/dev/null; echo SYSTEMD_OK'",
            check=False,
        )
        if "SYSTEMD_OK" in systemd_ok and "Failed to connect to bus" not in systemd_ok:
            run(
                c,
                f"cp {root}/deploy/edge-desk.service {CHROOT}/etc/systemd/system/edge-desk.service; "
                f"chroot {CHROOT} bash -lc 'systemctl daemon-reload; systemctl enable edge-desk; systemctl restart edge-desk; "
                f"sleep 2; systemctl is-active edge-desk; curl -s http://127.0.0.1:8080/healthz || true'",
                timeout=120,
                check=False,
            )
        else:
            print("systemd unavailable — starting via Python env loader", flush=True)
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from vps_desk_restart import restart_desk

            desk_key = os.environ.get("DESK_API_KEY", "").strip() or "hEe5070y9VnztqB1a2aFu9wkpw4L+PxcdQDbzuJjK+c="

            def _run(cmd: str, timeout: int = 120) -> str:
                return run(c, cmd, timeout=timeout, check=False)

            restart_desk(_run, desk_key)
    else:
        run(
            c,
            f"cp {root}/deploy/edge-desk.service /etc/systemd/system/edge-desk.service; "
            "systemctl daemon-reload; systemctl enable edge-desk; systemctl restart edge-desk; "
            "sleep 2; systemctl is-active edge-desk; curl -s http://127.0.0.1:8080/healthz || true",
            timeout=120,
            check=False,
        )
    print(run(c, f"tail -n 30 {root}/logs/desk.out 2>/dev/null || true", check=False), flush=True)
    c.close()
    print("deployed", REMOTE, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

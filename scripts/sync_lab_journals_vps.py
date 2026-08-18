"""Upload lab shadow-journal scripts and edge_lab packages to the VPS lab trees."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

NIFTY_LOCAL = Path(r"D:\Options-Nifty-Edge-Lab")
BN_LOCAL = Path(r"D:\Options-Edge-Lab")
CHROOT = "/mnt/sys"
NIFTY_REMOTE = "/root/Options-Nifty-Edge-Lab"
BN_REMOTE = "/root/Options-Edge-Lab"

FILES = [
    "scripts/run_shadow_journal.py",
    "scripts/run_shadow_daily.py",
    "scripts/check_execution_gate.py",
    "scripts/sync_shadow_fills_from_dhan.py",
    "scripts/summarize_shadow.py",
    "scripts/record_shadow_fill.py",
    "scripts/ingest_dhan_nifty.py",
    "scripts/ingest_dhan_bn.py",
]

TREES = ("edge_lab", "config")
SKIP_DIR = {".venv", "__pycache__", ".git", "data_lake", "reports", "node_modules"}


def load_env() -> None:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _put(c, sftp, local: Path, remote: str) -> None:
    _, o, _ = c.exec_command(f"mkdir -p $(dirname {remote})", timeout=20)
    o.read()
    sftp.put(str(local), remote)
    print("put", remote)


def _walk_tree(local_root: Path, tree: str) -> list[Path]:
    base = local_root / tree
    if not base.exists():
        return []
    out: list[Path] = []
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR for part in path.parts):
            continue
        if path.suffix.lower() not in {".py", ".yaml", ".yml", ".json", ".md"}:
            continue
        out.append(path)
    return out


def main() -> None:
    load_env()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        os.environ.get("EDGE_VPS_HOST", "87.232.72.137"),
        username="root",
        password=os.environ["EDGE_VPS_PASS"],
        timeout=45,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = c.open_sftp()
    for local_root, remote_root in ((NIFTY_LOCAL, NIFTY_REMOTE), (BN_LOCAL, BN_REMOTE)):
        _, o, _ = c.exec_command(
            f"mkdir -p {CHROOT}{remote_root}/data_lake {CHROOT}{remote_root}/reports/shadow "
            f"{CHROOT}{remote_root}/scripts",
            timeout=20,
        )
        o.read()
        for rel in FILES:
            lp = local_root / rel
            if not lp.exists():
                print("skip", lp)
                continue
            _put(c, sftp, lp, f"{CHROOT}{remote_root}/{rel.replace(chr(92), '/')}")
        for tree in TREES:
            for lp in _walk_tree(local_root, tree):
                rel = lp.relative_to(local_root).as_posix()
                _put(c, sftp, lp, f"{CHROOT}{remote_root}/{rel}")
    sftp.close()
    c.close()
    print("lab journal scripts + edge_lab uploaded")


if __name__ == "__main__":
    main()

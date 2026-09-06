#!/usr/bin/env python3
"""VPS soak: localhost + public healthz + Dhan probe. No buy/sell. No secret prints."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("EDGE_VPS_HOST", "87.232.72.137")
PORT = int(os.environ.get("EDGE_VPS_PORT", "443"))
USER = os.environ.get("EDGE_VPS_USER", "root")
REMOTE = "/root/Options-Edge-Desk"
PY = "/root/Options-Edge-Lab/.venv/bin/python3"
ROOT = Path(__file__).resolve().parents[1]
HARVEST = ROOT / "reports" / "qa" / "harvest"

INNER = r'''
import json, os, statistics, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

vals = {}
for ln in Path("/root/Options-Edge-Desk/.env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.split("=", 1)
        vals[k.strip()] = v.strip()
h = {"X-API-Key": vals.get("DESK_API_KEY", "")}
if vals.get("DESK_BFF_SECRET"):
    h["X-Desk-BFF"] = vals["DESK_BFF_SECRET"]
BASE = "http://127.0.0.1:8080"


def hit(path, headers=None, timeout=20):
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(BASE + path, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = r.status
            r.read(256)
    except urllib.error.HTTPError as e:
        try:
            e.read()
        except Exception:
            pass
        return e.code, time.perf_counter() - t0
    except Exception:
        return 0, time.perf_counter() - t0
    return code, time.perf_counter() - t0


def burst(path, n, workers, headers=None):
    out = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(hit, path, headers) for _ in range(n)]
        for f in as_completed(futs, timeout=90):
            out.append(f.result())
    lat = [s for _, s in out]
    codes = [c for c, _ in out]
    return {
        "n": len(out),
        "ok": sum(1 for c in codes if c == 200),
        "codes": sorted(set(codes)),
        "p50_ms": round(sorted(lat)[len(lat)//2] * 1000, 1) if lat else 0,
        "p95_ms": round(sorted(lat)[min(len(lat)-1, int(0.95*(len(lat)-1)))] * 1000, 1) if lat else 0,
        "max_ms": round(max(lat) * 1000, 1) if lat else 0,
        "mean_ms": round(statistics.mean(lat) * 1000, 1) if lat else 0,
    }

# public healthz (tunnel) — modest
def pub():
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request("https://deskapi.ravindra-devireddy.com/healthz")
        with urllib.request.urlopen(req, timeout=12) as r:
            code = r.status
            r.read(128)
        return code, time.perf_counter() - t0
    except Exception as e:
        return getattr(e, "code", 0) or 0, time.perf_counter() - t0

pub_rows = []
with ThreadPoolExecutor(max_workers=4) as pool:
    futs = [pool.submit(pub) for _ in range(8)]
    for f in as_completed(futs, timeout=90):
        pub_rows.append(f.result())
plat = [s for _, s in pub_rows]

dhan = {}
os.chdir("/root/Options-Edge-Desk")
os.environ["PYTHONPATH"] = "/root/Options-Edge-Desk"
from app.brokers.dhan import client as dhan_mod
from app.brokers.dhan.contracts import option_rows
dhan_mod.load_dotenv()
view = dhan_mod.token_public_view()
dhan["token_ok"] = bool(view.get("token_ok"))
dhan["seconds_left"] = view.get("seconds_left")
t0 = time.perf_counter()
try:
    spots = dhan_mod.spots_with_change()
    dhan["spot_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    dhan["spot_n"] = (spots.get("NIFTY") or {}).get("ltp") is not None
    dhan["spot_bn"] = (spots.get("BANKNIFTY") or {}).get("ltp") is not None
except Exception as e:
    dhan["spot_err"] = type(e).__name__
try:
    rows = option_rows("NIFTY")[:1]
    dhan["scrip_nifty"] = True
    if rows:
        sid = str(rows[0].get("security_id") or "")
        q0 = time.perf_counter()
        q = dhan_mod.market_quote_option(sid) if sid else {}
        dhan["quote_ms"] = round((time.perf_counter() - q0) * 1000, 1)
        dhan["quote_ltp"] = bool((q or {}).get("ltp") or (q or {}).get("last_price"))
except Exception as e:
    dhan["quote_err"] = type(e).__name__

# still one listener?
import subprocess
ss = subprocess.check_output("ss -ltnp | grep 8080 || true", shell=True, text=True)

out = {
    "local_healthz": burst("/healthz", 200, 20),
    "local_status": burst("/api/v1/desk/status", 24, 4, h),
    "local_snapshot": burst("/api/v1/desk/snapshot", 12, 3, h),
    "public_healthz": {
        "n": len(pub_rows),
        "ok": sum(1 for c, _ in pub_rows if c == 200),
        "p50_ms": round(sorted(plat)[len(plat)//2] * 1000, 1) if plat else 0,
        "p95_ms": round(sorted(plat)[min(len(plat)-1, int(0.95*(len(plat)-1)))] * 1000, 1) if plat else 0,
        "max_ms": round(max(plat) * 1000, 1) if plat else 0,
    },
    "dhan_probe": dhan,
    "listen_8080": ss.strip()[:240],
    "docs": hit("/docs")[0],
    "status_no_key": hit("/api/v1/desk/status")[0],
}
print(json.dumps(out))
'''


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _load_env()
    pw = os.environ.get("EDGE_VPS_PASS", "")
    if not pw:
        raise SystemExit("Set EDGE_VPS_PASS")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=pw, timeout=60, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    sftp.put(str(ROOT / "app" / "brokers" / "dhan" / "client.py"), f"{REMOTE}/app/brokers/dhan/client.py")
    sftp.put(str(ROOT / "app" / "main.py"), f"{REMOTE}/app/main.py")
    with sftp.file(f"{REMOTE}/scripts/_load_inner.py", "w") as fh:
        fh.write(INNER)
    sftp.close()
    _, o, e = c.exec_command(
        "systemctl stop edge-desk; fuser -k 8080/tcp >/dev/null 2>&1 || true; sleep 2; "
        "systemctl start edge-desk; sleep 6; "
        f"cd {REMOTE} && PYTHONPATH={REMOTE} {PY} {REMOTE}/scripts/_load_inner.py",
        timeout=200,
    )
    raw = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    c.close()
    if err.strip():
        print(err[-400:], flush=True)
    print(raw[-4000:], flush=True)
    try:
        data = json.loads(raw.strip().splitlines()[-1])
    except Exception:
        return 1
    HARVEST.mkdir(parents=True, exist_ok=True)
    # Public tunnel from this PC (VPS cannot hairpin Cloudflare).
    import statistics
    import time
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _pub():
        t0 = time.perf_counter()
        try:
            import subprocess
            p = subprocess.run(
                ["curl.exe", "-sS", "-o", os.devnull, "-w", "%{http_code} %{time_total}", "--max-time", "12",
                 "https://deskapi.ravindra-devireddy.com/healthz"],
                capture_output=True, text=True, timeout=15,
            )
            parts = (p.stdout or "").strip().split()
            code = int(parts[0]) if parts else 0
            sec = float(parts[1]) if len(parts) > 1 else time.perf_counter() - t0
            return code, sec
        except Exception:
            return 0, time.perf_counter() - t0

    pub_rows = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = [pool.submit(_pub) for _ in range(40)]
        for f in as_completed(futs, timeout=60):
            pub_rows.append(f.result())
    plat = [s for _, s in pub_rows]
    data["laptop_public_healthz"] = {
        "n": len(pub_rows),
        "ok": sum(1 for c, _ in pub_rows if c == 200),
        "p50_ms": round(sorted(plat)[len(plat) // 2] * 1000, 1) if plat else 0,
        "p95_ms": round(sorted(plat)[min(len(plat) - 1, int(0.95 * (len(plat) - 1)))] * 1000, 1) if plat else 0,
    }
    (HARVEST / "load_vps.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    hz = data.get("local_healthz") or {}
    st = data.get("local_status") or {}
    sn = data.get("local_snapshot") or {}
    dhan = data.get("dhan_probe") or {}
    lap = data["laptop_public_healthz"]
    ok = (
        hz.get("ok") == hz.get("n")
        and st.get("ok") == st.get("n")
        and sn.get("ok") == sn.get("n")
        and lap.get("ok") == lap.get("n")
        and data.get("docs") == 404
        and data.get("status_no_key") == 401
        and dhan.get("token_ok")
        and dhan.get("spot_n")
        and dhan.get("spot_bn")
    )
    print("GATE", ok, "healthz", hz, "status", st, "snap", sn, "public", lap, "dhan", {k: dhan.get(k) for k in ("token_ok", "spot_ms", "spot_n", "spot_bn", "quote_ltp")}, flush=True)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

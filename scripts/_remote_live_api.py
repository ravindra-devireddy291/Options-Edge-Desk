import json
import urllib.request
from pathlib import Path

key = next(
    (ln.split("=", 1)[1].strip().strip('"') for ln in Path("/root/Options-Edge-Desk/.env").read_text().splitlines() if ln.startswith("DESK_API_KEY=")),
    "",
)
for ep in ("/healthz", "/api/v1/desk/status", "/api/v1/desk/signals/today"):
    req = urllib.request.Request("http://127.0.0.1:8080" + ep, headers={"X-API-Key": key})
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.loads(r.read())
    if ep.endswith("status"):
        payload = d.get("data") if isinstance(d.get("data"), dict) else d
        d = {k: payload.get(k) for k in (
            "mode", "execution", "trading_active", "runner_state", "market_session",
            "token_ok", "broker_reachable", "shadow_book_halted", "available_cash",
            "open_positions", "last_error", "last_cycle_at",
        ) if k in payload}
    print("===", ep, "===")
    print(json.dumps(d, indent=2))

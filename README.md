# Options Edge Desk — shared Dhan-backed FastAPI for NIFTY + BANKNIFTY UI

Serves `my-options-trader` contract on port **8080**:

- REST `/api/v1/desk/*` (envelope `{ok, server_time, data}`)
- WebSocket `/ws/desk` (`health.tick`)
- Auth: `X-API-Key` / `api_key=` = `DESK_API_KEY`

**UI handshake (endpoints + mock/paper/live):** [docs/UI_COLLAB.md](docs/UI_COLLAB.md). Field freeze: [docs/BACKEND_REQUIREMENTS.md](docs/BACKEND_REQUIREMENTS.md). Shapes: [docs/UI_API_CONTRACT.md](docs/UI_API_CONTRACT.md). Scenario matrix: [docs/MODE_SCENARIO_MATRIX.md](docs/MODE_SCENARIO_MATRIX.md).

Edge Labs remain strategy/capital owners; this service is the shared broker + desk plane.

## Local

```bash
cp .env.example .env   # set DESK_API_KEY to match UI
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Point the Next BFF (server-only, never `NEXT_PUBLIC_DESK_API_KEY`):

```
DESK_API_URL=http://127.0.0.1:8080
DESK_API_KEY=<same as desk>
```

Hosted desk: set `DESK_API_URL` to `https://deskapi.ravindra-devireddy.com` (production) or your local tunnel. See [docs/UI_COLLAB.md](docs/UI_COLLAB.md).

## VPS

```bash
set EDGE_VPS_PASS=...
set DESK_API_KEY=...   # match my-options-trader
python scripts/deploy_desk_vps.py
python scripts/hard_restart_desk_vps.py   # if host has no chroot systemd bus
```

Desk binds `127.0.0.1:8080` inside `/mnt/sys` chroot. Use SSH tunnel or `deploy/nginx-desk.conf` for TLS.

```bash
ssh -L 8080:127.0.0.1:8080 root@87.232.72.137
```

## Token (no daily paste if desk stays up)

Dhan tokens last ~24h. Desk auto-calls `RenewToken` every 15 minutes when <6h remain,
and persists the new token to `.env`. Paste once from web.dhan.co after a full expiry,
or set `DHAN_PIN` + `DHAN_TOTP_SECRET` for unattended regeneration.

### How secrets reach the VPS

Your laptop `.env` is **not** visible to the VPS. Pick one:

1. **Recommended:** fill `D:\Options-Edge-Desk\.env` then push:
   ```bash
   set EDGE_VPS_PASS=...
   set DESK_API_KEY=...
   python scripts/push_dhan_secrets_vps.py --generate
   ```
2. **UI path:** SSH tunnel `8080` to VPS, open System → Dhan, enter PIN + TOTP secret,
   click Save — that writes onto the **connected desk host** (VPS).

Enable TOTP in Dhan Web → Access DhanHQ APIs → Setup TOTP, then put the base32 secret
and your 6-digit PIN into local `.env` before pushing.

## Trading Start / Stop

UI **Start trading / Stop trading** only arms/disarms the trading control plane.
The VPS uvicorn process is never killed by these buttons — health, positions, signals,
and token renew keep running.

Weekday **paper-auto** (`DESK_PAPER_AUTO=1`) arms both books ~09:10 IST and disarms after 15:45.
Live stays off until written client confirmation, then:

```bash
py -3 scripts/enable_live_vps.py --confirm-client-ready
```

That sets `DESK_LIVE_ENABLED=1`, `LIVE_NIFTY=1`, `LIVE_BANKNIFTY=1` and restarts the desk.
The same clock then arms **live+auto**. Do not run this during the paper month.



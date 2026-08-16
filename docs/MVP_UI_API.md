# MVP UI API contract

> **Superseded.** MVP freeze is [`docs/BACKEND_REQUIREMENTS.md`](./BACKEND_REQUIREMENTS.md). Caller cheat-sheet: [`docs/UI_API_CONTRACT.md`](./UI_API_CONTRACT.md). This file is history only.

Desk host: `http://127.0.0.1:8080`  
JSON base: `http://127.0.0.1:8080/api/v1/desk`  
Auth: header `X-API-Key` (not required on `/healthz`)

One desk. `underlying` is `"NIFTY"` or `"BANKNIFTY"`. No second product, no `:8081`, no mock desk, no `:8090` job engine.

Start/Stop **arms trading only**. The uvicorn process stays up.

UI may call **only** the endpoints in this file.

---

## Envelope

Success (HTTP 200):

```json
{ "ok": true, "server_time": "2026-08-14T14:00:00Z", "data": {} }
```

Transport / auth failure (HTTP 4xx/5xx):

```json
{ "ok": false, "server_time": "2026-08-14T14:00:00Z", "code": "error", "detail": "invalid or missing API key" }
```

Place / cancel keep HTTP 200 with `data.accepted: false` plus `data.message` so the UI can show a gate/broker message without treating it as a network error.

---

## 0. Liveness (no API key)

`GET /healthz`

```json
{
  "ok": true,
  "service": "options-edge-desk",
  "desk_process": "alive",
  "trading_active": false,
  "runner_state": "STOPPED"
}
```

UI: connectivity badge only.

---

## 1. Desk snapshot (home)

`GET /api/v1/desk/status`

Do **not** use `/health/full`.

`data`:

```json
{
  "desk_process": "alive",
  "trading_active": false,
  "runner_state": "STOPPED",
  "mode": "paper",
  "token_ok": true,
  "kill_switch_active": false,
  "shadow_book_halted": false,
  "available_cash": 185000.5,
  "nifty_spot": 24810.2,
  "banknifty_spot": 52100.0,
  "open_positions": 0,
  "last_error": null,
  "last_cycle_at": null
}
```

| Field | Type | Notes |
|---|---|---|
| `desk_process` | `"alive"` | Process is up |
| `trading_active` | bool | Armed for new orders |
| `runner_state` | `"RUNNING"` \| `"STOPPED"` | |
| `mode` | `"paper"` \| `"live"` | |
| `token_ok` | bool | Dhan token usable |
| `kill_switch_active` | bool | Read-only in MVP |
| `shadow_book_halted` | bool | Book halt |
| `available_cash` | number \| null | Broker cash |
| `nifty_spot` / `banknifty_spot` | number \| null | |
| `open_positions` | int | Non-zero broker rows |
| `last_error` | string \| null | |
| `last_cycle_at` | ISO string \| null | |

Poll every 5–15s. WebSocket is optional (see §10).

---

## 2. Start trading

`POST /api/v1/desk/runner/start`

```json
{ "mode": "paper", "operator_id": "ui" }
```

MVP UI always sends `mode: "paper"`. Live requires `confirm_live: true` and is out of MVP screens.

`data`:

```json
{
  "command": "start",
  "runner_state": "RUNNING",
  "trading_active": true,
  "desk_process": "alive",
  "message": "trading armed in paper (desk API stays up)"
}
```

---

## 3. Stop trading

`POST /api/v1/desk/runner/stop`

```json
{ "operator_id": "ui", "reason": "stop" }
```

`data`:

```json
{
  "command": "stop",
  "runner_state": "STOPPED",
  "trading_active": false,
  "desk_process": "alive",
  "message": "trading stopped (desk API + token renew stay online)"
}
```

Do not call `GET /runner`. Use `/status`.

---

## 4. Positions

`GET /api/v1/desk/positions`

```json
{
  "rows": [
    {
      "symbol": "NIFTY2581425000PE",
      "tradingsymbol": "NIFTY2581425000PE",
      "underlying": "NIFTY",
      "qty": -65,
      "quantity": -65,
      "average_price": 112.4,
      "unrealized_pnl": 1200.0
    }
  ],
  "row_count": 1,
  "snapshot_at": "2026-08-14T14:00:00Z"
}
```

On broker error: still `ok: true` with `rows: []`, `row_count: 0`, and `detail` (show “broker unreachable”).

---

## 5. Open orders

`GET /api/v1/desk/orders/open`

```json
{
  "orders": [
    {
      "order_id": "123456",
      "symbol": "NIFTY2581425000PE",
      "side": "SELL",
      "qty": 65,
      "status": "TRANSIT"
    }
  ],
  "count": 1,
  "snapshot_at": "2026-08-14T14:00:00Z"
}
```

Broker error: `orders: []`, `count: 0`, plus `detail`.

---

## 6. Paper place

`POST /api/v1/desk/orders/paper`

Minimal body:

```json
{
  "underlying": "NIFTY",
  "side": "SELL",
  "lots": 1,
  "option_type": "PE",
  "strike": 25000,
  "expiry": "2026-08-20",
  "dry_run": false
}
```

Desk resolves `security_id` and lot size.

- `dry_run: true` — preview / size only, no broker place
- `dry_run: false` — real paper place; requires `trading_active`

`data`:

```json
{
  "accepted": true,
  "message": null,
  "order": {},
  "contract": { "security_id": "…", "lot_size": 65, "quantity": 65 },
  "gate": { "ok": true }
}
```

If gated: `accepted: false` and `message` (e.g. `"trading stopped — Start trading first"`).

---

## 7. Cancel

`POST /api/v1/desk/orders/cancel`

```json
{ "order_id": "123456" }
```

Allowed even when trading is stopped.

`data`: `{ "accepted": true, "result": {} }` or `{ "accepted": false, "message": "…" }`

---

## 8. Today's trade ledger (blotter)

`GET /api/v1/desk/trades/today`

Closed (and still-open) rounds from **today's shadow journals**. Live `/positions` only shows what is still on. After a 50% TP the position vanishes; this list keeps the round-trip.

```json
{
  "day": "2026-08-14",
  "trades": [
    {
      "trade_id": "trd_98765",
      "underlying": "NIFTY",
      "symbol": "NIFTY2581425000PE",
      "side": "BUY",
      "qty": 650,
      "lots": 10,
      "entry_price": 105.5,
      "exit_price": 158.25,
      "exit_reason": "take_profit",
      "realized_pnl": 34287.5,
      "closed_at": "2026-08-14T09:42:15"
    }
  ],
  "total_realized_pnl": 34287.5,
  "trade_count": 1,
  "closed_count": 1
}
```

`exit_reason` is `"open"` when the sleeve is still live (no exit yet). `total_realized_pnl` sums only closed rows with a PnL.

---

## 9. Today's signals (compass)

`GET /api/v1/desk/signals/today`

Engine Trade Cards for **today only** (no fallback to older journals). Compare this to broker fills in Gate 5.

```json
{
  "day": "2026-08-14",
  "signals": [
    {
      "time": "09:30:00",
      "underlying": "NIFTY",
      "sleeve": "fade",
      "action": "BUY",
      "option_type": "PE",
      "target_strike": 25000,
      "target_lots": 10,
      "gap_pts": 110.5,
      "status": "EXECUTED",
      "notes": "ok",
      "symbol": "NIFTY2581425000PE"
    }
  ],
  "count": 1
}
```

`status`: `PENDING` | `EXECUTED` | `SKIPPED` | `REJECTED`

Do **not** use `/signals/last-cycle` in MVP.

---

## 10. Force broker sync

`POST /api/v1/desk/sync`

Empty body. Re-fetches positions, open orders, and cash from Dhan and rebuilds lab `execution_state` from shadow journals.

```json
{
  "accepted": true,
  "message": "Desk state synchronized with broker.",
  "sync_stats": {
    "positions_updated": 1,
    "orders_updated": 0,
    "cash_updated": true,
    "shadow_rebuilt": ["NIFTY", "BANKNIFTY"],
    "shadow_errors": []
  }
}
```

Partial broker failure: still HTTP 200, `accepted: false`, `message` explains which leg failed.

---

## 11. Locked backtest catalog

`GET /api/v1/desk/research/stable`

Selection is **server-side**: lowest peak DD among client-locked paper packs. UI does not pick “most stable”.

`data.most_stable.NIFTY` / `data.most_stable.BANKNIFTY`  
`data.overall_most_stable`: `{ "underlying", "pack_id", "peak_dd_pct", "return_pct" }`

Metrics use **percent points** (`214.9`, `20.28`), not fractions.

---

## 12. Locked pack for one book

`GET /api/v1/desk/research/stable/{NIFTY|BANKNIFTY}`

`data.selected`:

- `pack_id`, `role`, `span`
- `metrics`: `return_pct`, `peak_dd_pct`, `net_pnl`, `n_trades`
- `summary` — KPI widget (returns/DD as fractions for charts)
- `chart.points` — `{ date, timestamp, total_equity, drawdown_pct }`

---

## 13. Optional live tick

`WS /ws/desk?api_key=...`

```json
{ "type": "health.tick", "server_time": "…", "data": { "trading_active": false, "token_ok": true } }
```

If WebSocket is painful, poll `GET /status` every 5–15s. Do not require both.

---

## Out of MVP (do not build screens)

Keep on the server for ops / later. UI must not call these for MVP:

| Path | Why |
|---|---|
| `/health/full` | Nested; use `/status` |
| `GET /runner` | Redundant with `/status` |
| `/signals/last-cycle`, `/signals/rejected` | Use `/signals/today` |
| `/safety/*` | Start/Stop is enough; kill is read-only on `/status` |
| `/audit/*` | Forensics |
| `/orders/queue` | Internal |
| `/cycle/tick` | Runner-internal |
| `/system/token*` | Token OK is on `/status` |
| `:8090` jobs | Locked tapes only |
| `:8081` | One desk |

---

## Suggested screens

1. **Status** — `GET /status` + Start/Stop + `POST /sync`
2. **Backtest** — `GET /research/stable` + book toggle
3. **Book** — positions + open orders
4. **Day** — `GET /signals/today` + `GET /trades/today`
5. **Order** — paper place + cancel

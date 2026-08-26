# Edge desk — backend endpoint requirements

**Audience:** Options Edge Desk (FastAPI) engineers  
**Frontend:** `my-options-trader` (this repo)  
**Desk process:** `Options-Edge-Desk` on `http://127.0.0.1:8080`  
**Date:** 2026-08-15  
**Status:** Source of truth for the Edge UI MVP. Implement these fields and codes even if an older route already exists.

This document is additive to `Options-Edge-Desk/docs/MVP_UI_API.md`. Where they conflict, **this file wins**. Do not invent alternate field names. If a rename is required, change this document and the frontend Zod schemas together.

---

## 0. Product lock (do not violate)

| Rule | Meaning |
|------|---------|
| One desk | NIFTY and BANKNIFTY only. No equity desk, no second process, no `:8081`, no `:8090` job runner. |
| Paper MVP | Default Start is `mode: "paper"`. `live` is allowed (Dhan live credentials). |
| Start/Stop arms trading | uvicorn / token renew stay up. Start does **not** boot the VPS. Stop does **not** kill it. |
| Engine signals vs auto | **Manual:** do not auto-place from TRADEABLE; trigger is an approval interrupt. **Auto:** desk places at signal time; UI gets `role: fill_notice`. |
| Two books | NIFTY wallet and BANKNIFTY wallet are separate capital / gates / halt. |
| Qty | Always `lots × lot_size`. Never send lots without resolving lot size. |
| No secrets in the browser | `DESK_API_KEY`, Dhan PIN, TOTP never go to the client. The Next.js BFF injects `X-API-Key`. |
| No token UI | Show `token_ok` only. Ops refresh tokens on the host. |
| Kill is read-only | UI reads `kill_switch_active`. No Safety page. No `POST /safety/kill-switch` from the app. |
| Cancel always allowed | `POST /orders/cancel` works while paper is stopped. Kill/halt may still refuse with a coded reject. |
| Timezone | All timestamps in JSON are **UTC** (`…Z`). The UI formats IST (`Asia/Kolkata`). `day` is the **NSE cash session calendar date in IST**. |
| NSE session | Cash hours 09:15–15:30 IST. After close, review is allowed; new place is refused. |

UI screens (no extra tabs): **Auth → Home (Status) → Book → Day → Order → Lab**.

---

## 1. Transport

### 1.1 Base

| Item | Value |
|------|--------|
| JSON base | `http://127.0.0.1:8080/api/v1/desk` |
| Health (no key) | `GET http://127.0.0.1:8080/healthz` |
| WebSocket | `ws://127.0.0.1:8080/ws/desk?api_key=…` (server-to-server / BFF only) |
| Auth | Header `X-API-Key: $DESK_API_KEY` on every JSON route except `/healthz` |
| CORS | Allow the Next origin. Credentials unused for desk key. |

Missing or wrong key → **HTTP 401**:

```json
{ "ok": false, "server_time": "2026-08-15T10:00:00Z", "code": "unauthorized", "detail": "invalid or missing API key" }
```

UI maps this to Auth **Sign in error** / session unlock, never to an order ticket.

### 1.2 Envelope (every JSON route)

Success and **business rejects** use **HTTP 200**:

```json
{ "ok": true, "server_time": "2026-08-15T10:00:00Z", "data": {} }
```

`ok: true` means “the desk answered”. It does **not** mean the order was accepted.

Transport / auth failure uses HTTP 4xx/5xx:

```json
{ "ok": false, "server_time": "2026-08-15T10:00:00Z", "code": "error", "detail": "…" }
```

**Never throw a 200 that omits `data`.** Use `null` only where this spec marks a field nullable.

### 1.3 Mutation result shape (Start, Stop, Place, Cancel, Sync)

Every mutation `data` MUST include:

```json
{
  "accepted": true,
  "code": "OK",
  "message": null
}
```

| `accepted` | `code` | UI card |
|------------|--------|---------|
| `true` | `OK` | Success card for that verb |
| `false` | see §12 | Matching result card. **Nothing was placed/cancelled/armed.** |

Do not use HTTP 409/422 for gate/broker/halt. Keep HTTP 200 + `accepted: false` so the UI does not treat it as a network crash.

### 1.4 Polling

| Resource | Interval | Notes |
|----------|----------|--------|
| `GET /status` | 5–15 s while signed in | Home tape, banners, armed flag |
| `GET /quotes/option` | 1 s while ticket open | Live LTP / bid / ask |
| `GET /triggers/active` | 2–5 s if WS is down | Center alert |
| Book / Day | On tab focus + after place/cancel/sync | |
| Lab | On tab focus | Locked packs; no live poll required |

WebSocket is optional. If implemented, it **does not** replace REST for place/cancel. If omitted, polling above is mandatory.

### 1.5 What the Next.js BFF owns (not the desk)

The browser never calls `8080` with the desk key.

| BFF route (this app) | Desk call |
|----------------------|-----------|
| `POST /api/auth/login` | Invite email + password → httpOnly session. **Not** Dhan. **Not** `DESK_API_KEY`. |
| `POST /api/auth/logout` | Clear session |
| `GET /api/auth/session` | `{ email, fingerprint_enabled }` |
| All `/api/desk/*` proxies | Forward to FastAPI with `X-API-Key` |

Desk team: do **not** add email/password, PIN, or TOTP routes for the trader app.

Fingerprint / WebAuthn is client + BFF session. Desk is unaware.

---

## 2. Canonical enums

```
underlying     = NIFTY | BANKNIFTY
side           = BUY | SELL
option_type    = CE | PE
sleeve         = fade | orb
mode           = paper            (MVP)
runner_state   = RUNNING | STOPPED
market_session = pre | open | closed
trigger_kind   = buy | sell
signal_status  = PENDING | EXECUTED | SKIPPED | REJECTED
order_status   = TRANSIT | PENDING | TRADED | REJECTED | CANCELLED | … (pass broker status through; UI shows raw + Cancel when cancellable)
```

`sleeve` in JSON is lowercase. UI title-cases Fade / ORB.

---

## 3. Endpoints the UI will call

### Inventory

| # | Method | Path | Screen | Must for MVP |
|---|--------|------|--------|--------------|
| 0 | GET | `/healthz` | Connectivity | yes |
| 1 | GET | `/status` | Home | yes — **extend** |
| 2 | POST | `/runner/start` | Home confirm | yes — add `accepted`/`code` |
| 3 | POST | `/runner/stop` | Home confirm | yes — add `accepted`/`code` |
| 4 | GET | `/positions` | Home + Book | yes — **extend rows** |
| 5 | GET | `/orders/open` | Book | yes — **extend rows** |
| 6 | POST | `/orders/paper` | Ticket + Order | yes — **extend body + result** |
| 7 | POST | `/orders/cancel` | Book | yes — add `code` |
| 8 | GET | `/trades/today` | Day | yes — **extend fill quality** |
| 9 | GET | `/signals/today` | Day compass | yes |
| 9b | GET | `/signals/rejected` | Decision log | yes |
| 9c | GET | `/signals/last-cycle` | Decision log + funnel | yes |
| 10 | POST | `/sync` | Home broker banner | yes — add `code` |
| 11 | GET | `/research/stable` | Lab | yes |
| 12 | GET | `/research/stable/{underlying}` | Lab | yes |
| 12b | GET | `/research/g5` | G5 readiness meter (not fills today) | yes |
| 12b2 | GET | `/research/oos` | Lab Trust train/OOS | yes |
| 12b3 | GET | `/research/cost-honesty` | Lab cost honesty (BN) | yes |
| 12b4 | GET | `/research/scale` | Lab capital scale (BN) | yes |
| 12b5 | GET | `/research/brief` | Pre-market trade card | yes |
| 12c | GET | `/safety/circuit-breaker` | Home Risk (pre-halt) | yes |
| 12d | GET | `/audit/tail` | What-happened panel | yes |
| 13 | GET | `/contracts` | Order + ticket | **new** |
| 14 | GET | `/quotes/option` | Ticket live price | **new** |
| 15 | GET | `/quotes/spot` | Tape (optional if on `/status`) | **new or fold into status** |
| 16 | GET | `/gates` | Order banner + ticket gate line | **new** |
| 17 | GET | `/triggers/active` | Center alert | **new** |
| 18 | POST | `/triggers/ack` | Dismiss alert | **new** (optional persist) |
| 19 | WS | `/ws/desk` | Live tape + triggers | optional |

Paths below are relative to `/api/v1/desk` except `/healthz` and `/ws/desk`.

---

## 4. `GET /healthz` (no API key)

```json
{
  "ok": true,
  "service": "options-edge-desk",
  "desk_process": "alive",
  "trading_active": false,
  "runner_state": "STOPPED"
}
```

UI: process up/down only. Do not use this for PnL.

---

## 5. `GET /status` — Home snapshot (**extend**)

Poll this. Drive banners, Start/Stop enablement, Today net, spots.

```json
{
  "desk_process": "alive",
  "trading_active": false,
  "runner_state": "STOPPED",
  "mode": "paper",
  "token_ok": true,
  "kill_switch_active": false,
  "shadow_book_halted": false,
  "halted_underlyings": ["NIFTY"],
  "broker_reachable": true,
  "market_session": "open",
  "session_label": "NSE 09:15–15:30 IST",
  "available_cash": 185000.5,
  "nifty_spot": 24812.4,
  "nifty_change_pct": 0.42,
  "banknifty_spot": 51204.15,
  "banknifty_change_pct": -0.18,
  "open_positions": 2,
  "realized_pnl_today": 34012.4,
  "unrealized_pnl": 3572.0,
  "today_net": 34012.4,
  "last_error": null,
  "last_cycle_at": "2026-08-15T04:01:00Z",
  "last_sync_at": "2026-08-15T08:32:00Z",
  "books": [
    {
      "underlying": "NIFTY",
      "label": "Rs 1L book",
      "capital": 100000,
      "equity": 104812,
      "open_mtm": 4812,
      "open_lots": 10,
      "halted": false,
      "gates": [
        {
          "sleeve": "fade",
          "allow": true,
          "lots": 10,
          "reason": null,
          "dd_mode": "live",
          "dd_pct": 0.018,
          "day_pnl": -120.5,
          "month_pnl": 4200.0,
          "daily_cap": 2000.0,
          "monthly_cap": 15000.0,
          "premium_budget": 25000.0,
          "deploy_frac": 0.25
        },
        {
          "sleeve": "orb",
          "allow": false,
          "lots": 0,
          "reason": "ORB is denied after a fade loss",
          "dd_mode": "live",
          "dd_pct": 0.018,
          "day_pnl": -120.5,
          "month_pnl": 4200.0,
          "daily_cap": 2000.0,
          "monthly_cap": 15000.0,
          "premium_budget": 25000.0,
          "deploy_frac": 0.25
        }
      ]
    },
    {
      "underlying": "BANKNIFTY",
      "label": "Rs 2L book",
      "capital": 200000,
      "equity": 227243,
      "open_mtm": -1240,
      "open_lots": 2,
      "halted": false,
      "gates": [
        {
          "sleeve": "fade",
          "allow": true,
          "lots": 4,
          "reason": null,
          "dd_mode": "live",
          "dd_pct": 0.01,
          "day_pnl": 0.0,
          "month_pnl": 800.0,
          "daily_cap": 4000.0,
          "monthly_cap": 30000.0,
          "premium_budget": 50000.0,
          "deploy_frac": 0.25
        },
        {
          "sleeve": "orb",
          "allow": true,
          "lots": 2,
          "reason": null,
          "dd_mode": "live",
          "dd_pct": 0.01,
          "day_pnl": 0.0,
          "month_pnl": 800.0,
          "daily_cap": 4000.0,
          "monthly_cap": 30000.0,
          "premium_budget": 50000.0,
          "deploy_frac": 0.25
        }
      ]
    }
  ]
}
```

| Field | Type | Required | UI |
|-------|------|----------|-----|
| `trading_active` | bool | yes | Place enabled; Home Stop vs Start |
| `runner_state` | enum | yes | Pill RUNNING / STOPPED |
| `mode` | `"paper"` | yes | MVP always paper |
| `token_ok` | bool | yes | Pill; never a token form |
| `kill_switch_active` | bool | yes | Treat like halt for **place**. Cancel may still work unless `code: KILL_SWITCH` on cancel. |
| `shadow_book_halted` | bool | yes | Home **Trading halted** if any book halted |
| `halted_underlyings` | string[] | yes | Which book is in DD halt |
| `broker_reachable` | bool | yes | Home **Broker unreachable** |
| `market_session` | enum | yes | Home **Market closed** when `closed` |
| `session_label` | string \| null | yes | Optional subtitle |
| `available_cash` | number \| null | yes | Tape cash |
| `nifty_spot` / `banknifty_spot` | number \| null | yes | Tape LTP |
| `nifty_change_pct` / `banknifty_change_pct` | number \| null | yes | Tape % (signed, already ×100, e.g. `0.42` = +0.42%) |
| `open_positions` | int | yes | Count of non-zero broker rows |
| `realized_pnl_today` | number \| null | yes | Closed PnL today (IST day) |
| `unrealized_pnl` | number \| null | yes | Open MTM sum |
| `today_net` | number \| null | yes | Home KPI. Prefer `realized + unrealized` after costs if you have it; otherwise realized. Idle / no trades → `0`. |
| `last_error` | string \| null | yes | Do not dump stack traces |
| `last_cycle_at` | ISO \| null | yes | |
| `last_sync_at` | ISO \| null | yes | After Sync |
| `books[]` | array length 2 | yes | Home sleeve lines; Order gate copy |

**Banner priority (UI):** kill/halt > broker down > market closed. Backend still returns all flags; UI picks one.

When `broker_reachable` is false: still return last known spots/cash/positions counts if you have them; set numbers null only if never synced.

---

## 6. Start / Stop

### `POST /runner/start`

```json
{ "mode": "paper", "operator_id": "ui" }
```

MVP: `mode` is `paper` \| `mock` \| `live`. Body may include `execution` (`manual` \| `auto`). Live binds to Dhan credentials on the host.

Success `data`:

```json
{
  "accepted": true,
  "code": "OK",
  "command": "start",
  "runner_state": "RUNNING",
  "trading_active": true,
  "desk_process": "alive",
  "message": "trading armed in paper (desk API stays up)"
}
```

UI: **Paper armed**.

Reject examples:

| Condition | `code` | UI |
|-----------|--------|-----|
| Kill switch | `KILL_SWITCH` | **Not started** |
| Both books halted | `SHADOW_HALTED` | **Not started** |
| Already armed | `OK` (idempotent `accepted: true`) | **Paper armed** (“server was already running”) |

**Additive — mock replay:** `mode` may be `"mock"`. Body may include `execution` (`manual` \| `auto`, default `manual`) and `speed` (default `60`). Mock never calls Dhan. Same interrupt pipe as live: manual → `approval`; auto → `fill_notice` on each BUY/SELL. `market_session` follows the **sim clock**. Start again in mock **resets** the replay day. See §27.

### `POST /runner/stop`

```json
{ "operator_id": "ui", "reason": "stop" }
```

Success: `accepted: true`, `trading_active: false`, `runner_state: "STOPPED"`. UI: **Trading stopped**.

Open positions and working orders **must stay**. Cancel remains allowed.

---

## 7. Positions — `GET /positions`

```json
{
  "rows": [ { } ],
  "row_count": 2,
  "snapshot_at": "2026-08-15T10:00:00Z",
  "detail": null
}
```

Broker error: HTTP 200, `rows: []`, `row_count: 0`, `detail` set, and `/status.broker_reachable: false`.

**Each row MUST include:**

```json
{
  "symbol": "NIFTY2581425000PE",
  "tradingsymbol": "NIFTY2581425000PE",
  "underlying": "NIFTY",
  "security_id": "12345",
  "expiry": "2026-08-14",
  "strike": 25000,
  "option_type": "PE",
  "side": "LONG",
  "qty": 650,
  "quantity": 650,
  "lots": 10,
  "lot_size": 65,
  "average_price": 105.5,
  "mark_price": 98.2,
  "ltp": 98.2,
  "unrealized_pnl": 4812.0
}
```

| Field | Notes |
|-------|--------|
| `side` | `LONG` if qty > 0, `SHORT` if qty < 0 |
| `qty` / `quantity` | Signed exchange qty. `lots = abs(qty) / lot_size` (integer) |
| `lot_size` | From scrip master. NIFTY fallback 65; BANKNIFTY from master (do not hardcode 15 if master differs — return the real lot) |
| `ltp` / `mark_price` | Live mark. Same value OK if only one feed |
| `expiry` | `YYYY-MM-DD` |
| `strike` | Number |
| `option_type` | CE / PE |
| `unrealized_pnl` | Signed. UI shows `+4,812` / `-1,240` |

Home **Active trades** and Book **Active trades** use the same rows. Each row is Buy + Sell capable (same ticket, prefilled contract).

Empty: `rows: []` → copy “No positions. Fills will show here.”

---

## 8. Working orders — `GET /orders/open`

```json
{
  "orders": [ { } ],
  "count": 1,
  "snapshot_at": "2026-08-15T10:00:00Z",
  "detail": null
}
```

**Each order MUST include:**

```json
{
  "order_id": "123456",
  "client_order_id": "paper-a1b2c3",
  "symbol": "NIFTY2581425000PE",
  "underlying": "NIFTY",
  "expiry": "2026-08-14",
  "strike": 25000,
  "option_type": "PE",
  "side": "SELL",
  "qty": 65,
  "lots": 1,
  "lot_size": 65,
  "price": 112.4,
  "average_price": 0,
  "filled_qty": 0,
  "filled_quantity": 0,
  "status": "TRANSIT",
  "order_type": "MARKET",
  "placed_at": "2026-08-15T04:01:02Z",
  "cancellable": true
}
```

`cancellable: false` when already TRADED / CANCELLED. UI still may tap Cancel; then cancel returns `ALREADY_FILLED`.

Empty: “No working orders. Cancel stays available when paper is stopped.”

---

## 9. Contracts — `GET /contracts` (**new**)

Query:

| Param | Required | Values |
|-------|----------|--------|
| `underlying` | yes | NIFTY \| BANKNIFTY |
| `expiry` | no | `YYYY-MM-DD`. Default = nearest weekly expiry in the master |

```json
{
  "underlying": "NIFTY",
  "spot": 24812.4,
  "lot_size": 65,
  "expiry": "2026-08-14",
  "expiries": ["2026-08-14", "2026-08-21"],
  "atm_strike": 24800,
  "strike_step": 50,
  "strikes": [24700, 24750, 24800, 24850, 24900, 24950, 25000]
}
```

Return ~ATM ± a handful of strikes (min 5). UI Order page shows a chip row; ticket uses one strike from a trigger or this grid.

---

## 10. Live option quote — `GET /quotes/option` (**new**)

Query (one of):

- `security_id=…` **or**
- `underlying` + `expiry` + `strike` + `option_type`

```json
{
  "underlying": "NIFTY",
  "expiry": "2026-08-14",
  "strike": 25000,
  "option_type": "PE",
  "security_id": "12345",
  "tradingsymbol": "NIFTY2581425000PE",
  "lot_size": 65,
  "ltp": 105.5,
  "bid": 105.4,
  "ask": 105.55,
  "quoted_at": "2026-08-15T04:01:02Z",
  "stale": false
}
```

Ticket polls this. `stale: true` if quote older than 5s. Bid/ask may equal LTP if the feed has no book — still return numbers, do not omit.

`GET /quotes/spot` (optional): `{ "NIFTY": { "ltp", "change_pct" }, "BANKNIFTY": { … } }` if you do not want spots only on `/status`.

---

## 11. Gates — `GET /gates` (**new**)

Query: `underlying` required; `sleeve` optional.

```json
{
  "trading_active": true,
  "market_session": "open",
  "underlying": "NIFTY",
  "lot_size": 65,
  "sleeves": [
    {
      "sleeve": "fade",
      "allow": true,
      "lots": 10,
      "reason": null,
      "dd_mode": "live",
      "dd_pct": 0.018,
      "day_pnl": -120.5,
      "month_pnl": 4200.0,
      "daily_cap": 2000.0,
      "monthly_cap": 15000.0,
      "premium_budget": 25000.0,
      "deploy_frac": 0.25
    },
    {
      "sleeve": "orb",
      "allow": false,
      "lots": 0,
      "reason": "ORB is denied after a fade loss",
      "dd_mode": "live",
      "dd_pct": 0.018,
      "day_pnl": -120.5,
      "month_pnl": 4200.0,
      "daily_cap": 2000.0,
      "monthly_cap": 15000.0,
      "premium_budget": 25000.0,
      "deploy_frac": 0.25
    }
  ]
}
```

Headroom fields (`dd_*`, caps, `premium_budget`, `deploy_frac`) are pass-through from lab `GateDecision` — do not invent defaults when null. Same shape on `/status` → `books[].gates[]`.

Order page copy: “NIFTY fade ALLOW 10 lots” / “ORB denied today. Lot size 65.”  
Ticket line: `Gate ALLOW · max 10 lots · est. costs Rs …` (costs from dry_run).

If `trading_active` is false, UI disables Place with “Start trading first. Place stays off until paper is armed.” Backend must still reject `dry_run: false` with `TRADING_STOPPED`.

---

## 12. Paper place — `POST /orders/paper` (**extend**)

### Request

```json
{
  "underlying": "NIFTY",
  "side": "BUY",
  "lots": 10,
  "option_type": "PE",
  "strike": 25000,
  "expiry": "2026-08-14",
  "sleeve": "fade",
  "dry_run": false,
  "expected_ltp": 105.5,
  "price_tolerance": 0.5,
  "operator_id": "ui",
  "trace_id": "ui-uuid"
}
```

| Field | Required | Notes |
|-------|----------|--------|
| `underlying` | yes | |
| `side` | yes | BUY / SELL |
| `lots` | yes | Integer ≥ 1. Desk computes `quantity = lots × lot_size` |
| `option_type` | yes | CE / PE |
| `strike` | yes | |
| `expiry` | yes | `YYYY-MM-DD` |
| `sleeve` | yes | `fade` \| `orb` — gate uses this |
| `dry_run` | yes | `true` = Preview only. `false` = send to broker paper |
| `expected_ltp` | yes when `dry_run: false` | LTP shown on the ticket at tap |
| `price_tolerance` | no | Absolute points. Default **0.5**. If live LTP differs by more than this, **do not place** |
| `security_id` | no | Desk resolves if omitted |
| `quantity` | no | Ignore if `lots` present |

**Idempotency:** same `trace_id` within 30s must not double-place. Return the original result.

**Engine must not call this.** Only the UI after Buy/Sell on the ticket.

### Preview (`dry_run: true`)

Always allowed when the desk is up (even if disarmed), so Order **Preview** works. Do not hit the broker.

```json
{
  "accepted": true,
  "code": "OK",
  "message": "simulated only (dry_run)",
  "gate": { "allow": true, "lots": 10, "reason": null, "sleeve": "fade" },
  "quote": { "ltp": 105.5, "bid": 105.4, "ask": 105.55, "quoted_at": "…" },
  "contract": {
    "security_id": "…",
    "tradingsymbol": "NIFTY2581425000PE",
    "lot_size": 65,
    "quantity": 650,
    "lots": 10,
    "strike": 25000,
    "option_type": "PE",
    "expiry": "2026-08-14"
  },
  "estimate": {
    "premium_value": 68575,
    "est_costs": 275,
    "notional": 68575
  }
}
```

If gate deny on preview: `accepted: false`, `code: GATE_DENY`, still include `contract` if resolved. UI **Not sent (gate)** — nothing to the broker.

### Place (`dry_run: false`)

Requires `trading_active`. Send to Dhan paper. While in flight the UI shows **Placing…** (client-only). Do not add a placing endpoint.

Success:

```json
{
  "accepted": true,
  "code": "OK",
  "message": null,
  "order": {
    "client_order_id": "paper-a1b2c3",
    "broker_order_id": "123456",
    "side": "BUY",
    "lots": 10,
    "lot_size": 65,
    "quantity": 650,
    "price": 105.5,
    "status": "TRANSIT"
  },
  "contract": { },
  "gate": { "allow": true, "lots": 10, "reason": null, "sleeve": "fade" },
  "quote": { "ltp": 105.5, "bid": 105.4, "ask": 105.55 }
}
```

UI: **Order sent** with Size, Price, Id `client_order_id`, link Book.

### Place rejects (`accepted: false`)

Always HTTP 200. Include `message` (human, one sentence) plus `code`.

| `code` | When | Extra `data` | UI |
|--------|------|----------------|-----|
| `TRADING_STOPPED` | Not armed | | Gated Order / **Not started** if from trigger |
| `KILL_SWITCH` | Kill on | | **Cannot place** |
| `SHADOW_HALTED` | That underlying halted | `underlying` | Trigger halted / **Cannot place** |
| `MARKET_CLOSED` | `market_session != open` | | Banner already on Home; ticket should not send |
| `GATE_DENY` | Sleeve blocked | `gate.reason`, `gate.sleeve`, `gate.lots` | **Not sent** gate. Example reason: `ORB is denied after a fade loss` |
| `PRICE_MOVED` | Live LTP vs `expected_ltp` > tolerance | `quote.ltp` was, `quote.ltp` now, `contract`, `lots` | **Price moved** buy or sell. Nothing placed |
| `BROKER_REJECT` | Dhan refused | `order` if any | **Not sent** broker. Edit ticket |
| `CONTRACT_RESOLVE_FAILED` | Unknown expiry/strike | | Not sent broker-style |
| `BROKER_UNREACHABLE` | Timeout / 5xx to Dhan | | Not sent broker |

`PRICE_MOVED` payload:

```json
{
  "accepted": false,
  "code": "PRICE_MOVED",
  "message": "Live price changed before send. Nothing was placed.",
  "side": "BUY",
  "was": { "ltp": 105.5, "value": 68575 },
  "now": { "ltp": 106.2, "value": 69030 },
  "contract": { },
  "lots": 10,
  "lot_size": 65
}
```

Do **not** place at the new price unless the user taps Buy/Sell again with the new `expected_ltp`.

Suggested lots on a trigger may exceed gate max: clamp or GATE_DENY. Prefer GATE_DENY with `gate.lots` so the user can edit the ticket.

---

## 13. Cancel — `POST /orders/cancel`

```json
{ "order_id": "123456", "operator_id": "ui" }
```

Allowed when `trading_active` is false.

Success: `accepted: true`, `code: OK`. UI **Order cancelled**.

| `code` | UI |
|--------|-----|
| `ALREADY_FILLED` | **Not cancelled** — already filled. Check Active trades |
| `ORDER_NOT_FOUND` | **Not cancelled** |
| `KILL_SWITCH` | **Not cancelled** |
| `BROKER_REJECT` | **Not cancelled** |

Include `order_id` in `data` on every cancel result.

---

## 14. Sync — `POST /sync`

Empty body. Refresh positions, open orders, cash, rebuild shadow state.

Success: `accepted: true`, `code: OK`, `last_sync_at` (also on next `/status`).

Failure: `accepted: false`, `code: SYNC_FAILED`, `message` which leg failed. UI **Sync failed**. Positions may be stale.

```json
{
  "accepted": false,
  "code": "SYNC_FAILED",
  "message": "Broker positions did not refresh.",
  "sync_stats": {
    "positions_updated": 0,
    "orders_updated": 0,
    "cash_updated": false,
    "shadow_rebuilt": [],
    "shadow_errors": ["NIFTY:…"]
  }
}
```

---

## 15. Day blotter — `GET /trades/today`

IST calendar day. Include open rounds (`exit_reason: "open"`).

```json
{
  "day": "2026-08-15",
  "total_realized_pnl": 34012.4,
  "total_costs": 275,
  "total_net_pnl": 34012.4,
  "trade_count": 2,
  "closed_count": 1,
  "lots_traded": 12,
  "trades": [
    {
      "trade_id": "paper-a1b2c3",
      "underlying": "NIFTY",
      "sleeve": "fade",
      "symbol": "NIFTY2581425000PE",
      "side": "BUY",
      "qty": 650,
      "lots": 10,
      "lot_size": 65,
      "entry_price": 105.5,
      "exit_price": 158.25,
      "exit_reason": "take_profit",
      "realized_pnl": 34287.5,
      "costs": 275,
      "net_pnl": 34012.4,
      "lab_entry": 104.8,
      "broker_entry": 105.5,
      "lab_exit": 158.0,
      "broker_exit": 158.25,
      "slip_entry": 0.7,
      "slip_exit": 0.25,
      "closed_at": "2026-08-15T04:12:15Z"
    }
  ]
}
```

Empty: `trades: []`, totals `0`. UI: “No trades today. Closed fills will list here.”

`exit_reason: "open"` → Day table may show net as `"open"`. `realized_pnl` null.

---

## 16. Compass — `GET /signals/today`

Today’s engine cards only. No last-cycle fallback.

```json
{
  "day": "2026-08-15",
  "count": 2,
  "signals": [
    {
      "signal_id": "nifty-fade-2026-08-15-1",
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
    },
    {
      "signal_id": "nifty-orb-2026-08-15-1",
      "time": "09:45:00",
      "underlying": "NIFTY",
      "sleeve": "orb",
      "action": "BUY",
      "option_type": "CE",
      "target_strike": 24900,
      "target_lots": 2,
      "status": "REJECTED",
      "notes": "fade loss",
      "symbol": ""
    }
  ]
}
```

`status`: PENDING (tradeable, user has not placed) | EXECUTED | SKIPPED | REJECTED.

PENDING is **not** an auto-order. It should also appear on `GET /triggers/active` until acked or placed or invalidated.

Empty compass: “No signals yet. PENDING can open a ticket when trading is armed.”

---

## 16b. Decision log — `GET /signals/rejected` + `GET /signals/last-cycle`

**Allowlisted for trader UI.** Rejected row:

`{ trace_id, underlying, sleeve, stage, reason, symbol, at, notes }`

- `stage`: `signal` | `gate` | `oms`
- `reason`: lab snake_case (`skip_*` preferred); UI humanizes
- `symbol`: real or `null`

Compass stays on `/signals/today`. Prefer `/signals/rejected` for the decision log alone.

---

## 17. Triggers — `GET /triggers/active` (**new**)

Center alert. **Nothing is placed.** At most **one** active interrupt (newest wins). If a ticket is open, UI shows **New signal** sheet; backend can still return the new trigger.

```json
{
  "active": true,
  "trigger": {
    "trigger_id": "trg_01",
    "kind": "buy",
    "underlying": "NIFTY",
    "expiry": "2026-08-14",
    "strike": 25000,
    "option_type": "PE",
    "sleeve": "fade",
    "suggested_lots": 10,
    "ltp": 105.5,
    "tradingsymbol": "NIFTY  14 Aug  25000 PE",
    "note": "Nothing is placed until you confirm.",
    "placeable": true,
    "created_at": "2026-08-15T04:00:01Z"
  }
}
```

No trigger: `{ "active": false, "trigger": null }`.

| `kind` | UI title | Confirm |
|--------|----------|---------|
| `buy` | Buy trigger | Buy → ticket side BUY |
| `sell` | Sell trigger | Sell → ticket side SELL (close / TP) |

If `placeable: false` (halt / kill / stopped): still show the alert. Confirm button stays visually there at 40% opacity; tap must not place. `meta`: “Trading halted — cannot place.”

Sell trigger includes `suggested_lots` = position lots to close and live LTP of that contract.

### `POST /triggers/ack` (**new**, optional)

```json
{ "trigger_id": "trg_01", "action": "dismiss" }
```

`action`: `dismiss` | `opened_ticket`. Dismiss hides the interrupt until a **new** `trigger_id`. Do not build a pending-inbox screen.

If you skip ack, UI can hide locally; a later poll must not resurrect the same `trigger_id` after dismiss if ack exists.

**Server must never place from a trigger.**

---

## 17b. Gate-5 readiness — `GET /research/g5`

Read-only. Source: `{lab}/reports/shadow/G5_TRACKER.json` per book.  
**Not** fills-today. Soft-fail missing files into `errors[]` (HTTP still 200 / envelope `ok`).

Query: `underlying` optional (`NIFTY` \| `BANKNIFTY`).

`data.books[].gate_G5` drives the unlock meter (`sessions_with_g5_fill`, `remaining`, `pass`, target 20).  
`sessions` capped to last 40 (`sessions_truncated` when truncated). Desk never writes the tracker.

---

## 17b2–17b5. Research impress (OOS / cost / scale / brief)

| Route | Notes |
|-------|--------|
| `GET /research/oos` | Normalized train/OOS windows; NIFTY + BN sources |
| `GET /research/cost-honesty` | BN pre-aggregated months; no raw CSV |
| `GET /research/scale` | BN AUM rows; no trades array |
| `GET /research/brief?day=` | `TRADE_CARD_<day>.md` markdown per book |

---

## 17c. Circuit breaker — `GET /safety/circuit-breaker`

**Allowlisted GET only** for Home Risk. Shape:

`{ tripped, soft_halt, trip_reason, peak_dd_pct, limits, books[] }`

- `peak_dd_pct` / `books[].dd_pct`: **fractions** (0.018 = 1.8%), not percent points  
- `limits.daily_loss_limit_inr` may be `null`; `max_drawdown_from_peak_pct` from lab config  
- **Never** `POST /safety/kill-switch` from trader UI

---

## 17d. Audit tail — `GET /audit/tail`

**Allowlisted.** `?limit=` default 100, max 500. Secrets redacted to `"[redacted]"`.  
`data`: `{ count, limit, events: [{ ts, kind, … }] }`.  
Kinds stay raw (e.g. `trading.start`, `order.paper_place`, `trading.stop`); UI labels them.

---

## 18. Lab — locked research

### `GET /research/stable`

Keep current catalog. UI needs:

- `selection_rule`
- `span` (e.g. `2021-07 → 2026-06`)
- `most_stable.NIFTY` / `most_stable.BANKNIFTY`
- `packs[]` with `pack_id`, `underlying`, `role`, `selection` (`most_stable` \| `alternate`), `metrics`

Metrics (percent **points**, not 0.184):

```json
{
  "return_pct": 18.4,
  "peak_dd_pct": 9.2,
  "net_pnl": 18400,
  "n_trades": 214,
  "avg_lots": 8
}
```

Add `avg_lots` if the tape has it; else omit and UI hides that clause.

### `GET /research/stable/{NIFTY|BANKNIFTY}`

```json
{
  "underlying": "NIFTY",
  "selected": { "pack_id": "…", "role": "…", "span": "…", "metrics": {}, "chart": { "points": [] } },
  "alternates": [ { } ]
}
```

`chart.points[]`: `{ "date", "timestamp", "total_equity", "drawdown_pct" }` for the sparkline.

UI does not pick the pack. Server = lowest peak DD among locked paper packs.

Assumptions line is copy-only on the client (“Aggressor fills · full F&O costs · rules only”). No extra endpoint.

---

## 19. WebSocket (optional)

`WS /ws/desk?api_key=`

Messages:

```json
{ "type": "health.tick", "server_time": "…", "data": { /* subset of GET /status */ } }
{ "type": "quote.option", "data": { /* same as GET /quotes/option */ } }
{ "type": "signal.trigger", "data": { /* same as GET /triggers/active.trigger */ } }
{ "type": "signal.clear", "data": { "trigger_id": "trg_01" } }
```

Do not bump trading cycles as a side effect of a UI socket if that places or advances strategy unexpectedly. Health ticks only.

If WS is not ready, REST polling in §1.4 is enough.

---

## 20. UI result-code map (complete)

Frontend cards. Backend `code` column is mandatory on mutations.

| UI story | Trigger | Success/fail | Backend |
|----------|---------|--------------|---------|
| Placing… | Client, while request in flight | — | no extra API |
| Order sent | Place `accepted` | `OK` | `client_order_id`, size, price |
| Not sent (gate) | Place | `GATE_DENY` | `gate.reason` |
| Not sent (broker) | Place | `BROKER_REJECT` / `BROKER_UNREACHABLE` / `CONTRACT_RESOLVE_FAILED` | `message` |
| Price moved buy/sell | Place | `PRICE_MOVED` | was/now LTP + value |
| Cannot place | Place or trigger | `SHADOW_HALTED` / `KILL_SWITCH` | |
| Not started | Start | `KILL_SWITCH` / `SHADOW_HALTED` | |
| Paper armed | Start | `OK` | |
| Trading stopped | Stop | `OK` | |
| Cancel this order? | Client confirm | — | no API until confirm |
| Order cancelled | Cancel | `OK` | |
| Not cancelled | Cancel | `ALREADY_FILLED` etc. | |
| Sync failed | Sync | `SYNC_FAILED` | |
| New signal | Second trigger while ticket open | `GET /triggers/active` | new `trigger_id` |
| Market closed / broker / halt | `GET /status` flags | — | |

---

## 21. Operator flows → API sequence

### Sign in

BFF only. Desk unused until session exists.

### Home idle

`GET /status` → `today_net: 0`, `open_positions: 0`, `trading_active: false`.  
`GET /positions` → empty.  
`GET /triggers/active` → `active: false`.

### Start paper

Confirm in UI → `POST /runner/start` `{ mode: "paper" }` → **Paper armed**.

### Trigger → ticket → place

1. `GET /triggers/active` or WS `signal.trigger`  
2. User Buy/Sell (no API)  
3. `GET /quotes/option` + `GET /gates` (ticket)  
4. Preview optional: `POST /orders/paper` `dry_run: true`  
5. Place: `dry_run: false` + `expected_ltp`  
6. Success → poll `/orders/open`  
7. Fill → row appears on `/positions`; working order disappears  

Row Buy/Sell on Active trades skips step 1; prefills contract from the position.

### Stop

`POST /runner/stop`. Positions remain. New place → `TRADING_STOPPED`.

### Cancel

UI confirm → `POST /orders/cancel`. Allowed while stopped.

### Lab

`GET /research/stable` then `GET /research/stable/NIFTY` (chip toggle BANKNIFTY).

---

## 22. Out of MVP (do not call from the app)

| Path | Why |
|------|-----|
| `GET /health/full` | Nested ops dump |
| `GET /runner` | Use `/status` |
| `/safety/kill-switch` POST | Forbidden for trader UI |
| `/orders/queue` | Internal |
| `/cycle/tick` | Runner-internal |
| `/system/token*` | No token/PIN/TOTP UI |
| Live start / `confirm_live` | No live screen |

`GET /signals/rejected` and `GET /signals/last-cycle` are **allowlisted** for the decision log (same rejected row shape). Compass still uses `/signals/today`.

`GET /safety/circuit-breaker` is **allowlisted** for Home Risk (read-only). **Never** wire `POST /safety/kill-switch`.

`GET /audit/tail` is **allowlisted** (redacted secrets; default limit 100, max 500).

Keep these on the server for ops if they already exist.

---

## 23. Implementation order (backend)

1. **Extend `/status`** with session, PnL, spots %, `books[]`, `broker_reachable`  
2. **Extend position + open-order rows** (lots, lot_size, strike, expiry, LTP, MTM, cancellable)  
3. **`accepted` + `code` on start/stop/place/cancel/sync**  
4. **`GET /contracts` + `GET /quotes/option` + `GET /gates`**  
5. **`expected_ltp` / `PRICE_MOVED` on place**  
6. **`GET /triggers/active` (+ WS if you can)** — no auto-place  
7. **Extend `/trades/today`** with costs / slip / sleeve  
8. **`avg_lots` on research** if cheap  

Frontend can wire Storybook → live pages as soon as (1)–(5) exist.

---

## 24. Non-functional

| Item | Requirement |
|------|-------------|
| Place latency | Aim < 2s to Dhan ack; UI stays on Placing until then |
| Quote | Fresh < 2s when ticket open |
| Numbers | JSON numbers, not preformatted strings. No `₹`. UI formats `Rs` / `+4,812` |
| `day` | IST session date `YYYY-MM-DD` |
| Logging | Audit place/cancel/start/stop with `operator_id`, `trace_id`, never log API key or TOTP |
| Idempotency | `trace_id` on place |
| Paper vs live | MVP `mode` is paper; Dhan paper product flags stay server-side |

---

## 25. Example env (desk)

```
DESK_API_KEY=…          # same secret the Next BFF uses; never NEXT_PUBLIC_
DESK_MODE=paper
NIFTY_LAB_ROOT=…
BN_LAB_ROOT=…
```

UI env (this repo, server-only):

```
DESK_API_URL=http://127.0.0.1:8080
DESK_API_KEY=…          # BFF only
```

Do not add `NEXT_PUBLIC_DESK_API_KEY`.

---

## 26. Contract freeze

Field names in this file are frozen for MVP. Adding optional keys is fine. Removing or renaming a required key is a breaking change: update this document first.

Questions that would block the UI should be answered as:

- Yes, the field exists and is always present (use `null` if unknown).  
- Yes, `code` is one of the enums in §12 / §13 / §14.  
- Yes, paper/live **auto** places PENDING via the desk (Dhan). Mock auto fills the sim tape only (no broker). Both emit `fill_notice`.

---

## 27. Mock replay (additive)

Optional Home control. Same routes. No new trader paths.

**Start**

```json
{ "mode": "mock", "execution": "manual", "operator_id": "ui", "speed": 60 }
```

`execution` omitted ⇒ `manual`. `mode: "paper"` unchanged.

**Status additive keys** (present when `mode` is `mock`; otherwise `execution`/`replay` may be `null`):

```json
{
  "mode": "mock",
  "execution": "manual",
  "replay": { "day": "2021-08-23", "speed": 60, "sim_time": "2021-08-23T04:00:00Z", "playing": true }
}
```

- Sim session 09:15–15:30 IST on `replay.day`, accelerated by `speed` (60x ≈ 6 minutes wall).
- Quotes/LTP/PnL are **synthetic** interpolations of locked-tape entry→exit (not 1m bars).
- Manual: `GET /triggers/active` at signal time (`role: approval`); user places.
- Auto: desk fills tape entries; `/triggers/active` and WS emit `role: fill_notice` (FIFO) after each autonomous BUY/SELL including overlay while auto, tape exit, and 15:30. Overlay still `POST /orders/paper`. Tape exit sells `tape_qty` only.
- Mock `POST /orders/paper` success always includes `broker_order_id` (`mock_broker_{uuid}`).
- Ledger mutations are serialized with `asyncio.Lock`. A background `asyncio` loop ticks the sim independent of UI polling.
- `POST /sync` in mock: `accepted: true` without Dhan.
- Stop freezes the ledger; process stays up. Next mock Start resets the day.

**Mode × execution (mock / paper / live × manual / auto), who places, and which APIs carry tick/PnL/trades:** [`docs/MODE_SCENARIO_MATRIX.md`](./MODE_SCENARIO_MATRIX.md).


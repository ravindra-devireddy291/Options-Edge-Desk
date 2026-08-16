# Options Edge Desk — UI API contract

**Freeze:** [`docs/BACKEND_REQUIREMENTS.md`](./BACKEND_REQUIREMENTS.md) (§§0–21, §24). This file is the caller cheat-sheet. Where they conflict, **BACKEND_REQUIREMENTS wins**. Do not add extra trader-facing routes. Optional keys may be added; renaming or dropping a required field is a breaking change.

**Audience:** `my-options-trader` (Next.js BFF)  
**Handshake (as-built modes, inventory, ticket rules):** [`UI_COLLAB.md`](./UI_COLLAB.md)  
**Desk origin:** `{DESK_API_URL}` (local `http://127.0.0.1:8080` or HTTPS tunnel)  
**JSON base:** `{DESK_API_URL}/api/v1/desk`  
**Implemented:** 2026-08-16  
**Status:** Frozen field names for MVP. Matches `BACKEND_REQUIREMENTS.md` (that file wins on conflict).

The browser never calls the desk origin. The BFF injects `X-API-Key`. Do not send `DESK_API_KEY`, Dhan PIN, or TOTP to the client.

---

## Transport

| Item | Value |
|------|--------|
| Auth | Header `X-API-Key: $DESK_API_KEY` on every JSON route except `/healthz` |
| WebSocket | `{ws\|wss}://{desk-host}/ws/desk?api_key=$DESK_API_KEY` (BFF only; `wss` when origin is `https`) |
| CORS | Open for the Next origin. No cookies / credentials for the desk key |
| Timestamps | UTC ISO-8601 with `Z` |
| `day` | NSE cash session calendar date in **IST** (`YYYY-MM-DD`) |
| Numbers | JSON numbers. No `₹`. UI formats `Rs` / `+4,812` |

### Success envelope (HTTP 200)

Every JSON route under `/api/v1/desk`:

```json
{ "ok": true, "server_time": "2026-08-16T04:30:00Z", "data": {} }
```

`ok: true` means the desk answered. It does **not** mean an order was accepted. Mutations use `data.accepted` + `data.code`.

Never treat HTTP 200 + `accepted: false` as a network crash.

### Auth failure (HTTP 401)

```json
{ "ok": false, "server_time": "2026-08-16T04:30:00Z", "code": "unauthorized", "detail": "invalid or missing API key" }
```

Map to Auth **Sign in error** / session unlock. Never to an order ticket.

### Other transport errors (HTTP 4xx/5xx)

```json
{ "ok": false, "server_time": "2026-08-16T04:30:00Z", "code": "error", "detail": "…" }
```

### Mutation `data` (Start, Stop, Place, Cancel, Sync, Ack)

Always includes:

| Field | Type | Notes |
|-------|------|--------|
| `accepted` | bool | `false` = nothing armed / placed / cancelled / synced |
| `code` | string | `OK` or a reject code below |
| `message` | string \| null | One human sentence |

---

## Canonical enums

```
underlying     = NIFTY | BANKNIFTY
side           = BUY | SELL          (orders)
position.side  = LONG | SHORT
option_type    = CE | PE
sleeve         = fade | orb          (lowercase in JSON)
mode           = paper | mock | live
execution      = manual | auto
runner_state   = RUNNING | STOPPED
market_session = pre | open | closed
trigger_kind   = buy | sell
trigger_role   = approval | fill_notice
signal_status  = PENDING | EXECUTED | SKIPPED | REJECTED
order_status   = broker raw (TRANSIT | PENDING | TRADED | REJECTED | CANCELLED | …)
```

---

## Inventory (UI must call)

| # | Method | Path | Screen | Auth |
|---|--------|------|--------|------|
| 0 | `GET` | `/healthz` | Connectivity | none |
| 1 | `GET` | `/api/v1/desk/status` | Home | key |
| 2 | `POST` | `/api/v1/desk/runner/start` | Home confirm | key |
| 3 | `POST` | `/api/v1/desk/runner/stop` | Home confirm | key |
| 4 | `GET` | `/api/v1/desk/positions` | Home + Book | key |
| 5 | `GET` | `/api/v1/desk/orders/open` | Book | key |
| 6 | `POST` | `/api/v1/desk/orders/paper` | Ticket + Order | key |
| 7 | `POST` | `/api/v1/desk/orders/cancel` | Book | key |
| 8 | `GET` | `/api/v1/desk/trades/today` | Day | key |
| 9 | `GET` | `/api/v1/desk/signals/today` | Day compass | key |
| 10 | `POST` | `/api/v1/desk/sync` | Home broker banner | key |
| 11 | `GET` | `/api/v1/desk/research/stable` | Lab | key |
| 12 | `GET` | `/api/v1/desk/research/stable/{underlying}` | Lab | key |
| 13 | `GET` | `/api/v1/desk/contracts` | Order + ticket | key |
| 14 | `GET` | `/api/v1/desk/quotes/option` | Ticket live price | key |
| 15 | `GET` | `/api/v1/desk/quotes/spot` | Tape (optional) | key |
| 16 | `GET` | `/api/v1/desk/gates` | Order banner + ticket | key |
| 17 | `GET` | `/api/v1/desk/triggers/active` | Center alert | key |
| 18 | `POST` | `/api/v1/desk/triggers/ack` | Dismiss alert | key |
| 19 | `WS` | `/ws/desk` | Live tape + triggers | query `api_key` |

### Polling (if WS is unused)

| Resource | Interval |
|----------|----------|
| `GET /status` | 5–15 s signed in; **~1 s** while `mode=mock` and `replay.playing` |
| `GET /quotes/option` | 1 s while ticket open |
| `GET /triggers/active` | 2–5 s if WS is down |
| Book / Day | On tab focus + after place/cancel/sync |
| Lab | On tab focus |

WebSocket does **not** replace REST for place/cancel.

---

## 0. `GET /healthz`

No API key. Process up/down only. Do not use for PnL.

**Response** (not wrapped in `data`):

```json
{
  "ok": true,
  "service": "options-edge-desk",
  "desk_process": "alive",
  "trading_active": false,
  "runner_state": "STOPPED"
}
```

---

## 1. `GET /api/v1/desk/status`

Home snapshot. Poll this.

**Request:** no body, no query.

**`data`:**

```json
{
  "desk_process": "alive",
  "trading_active": false,
  "runner_state": "STOPPED",
  "mode": "paper",
  "token_ok": true,
  "kill_switch_active": false,
  "shadow_book_halted": false,
  "halted_underlyings": [],
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
  "today_net": 37584.4,
  "last_error": null,
  "last_cycle_at": "2026-08-15T04:01:00Z",
  "last_sync_at": "2026-08-15T08:32:00Z",
  "execution": "auto",
  "replay": null,
  "paper_auto": true,
  "signals_today": 4,
  "trades_today": 2,
  "log_events_today": 18,
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
        { "sleeve": "fade", "allow": true, "lots": 10, "reason": null },
        { "sleeve": "orb", "allow": false, "lots": 0, "reason": "ORB is denied after a fade loss" }
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
        { "sleeve": "fade", "allow": true, "lots": 4, "reason": null },
        { "sleeve": "orb", "allow": true, "lots": 2, "reason": null }
      ]
    }
  ]
}
```

| Field | Type | UI |
|-------|------|-----|
| `trading_active` | bool | Place enabled; Home Stop vs Start |
| `runner_state` | enum | Pill RUNNING / STOPPED |
| `token_ok` | bool | Pill only — never a token form |
| `kill_switch_active` | bool | Treat like halt for **place** |
| `shadow_book_halted` | bool | Home **Trading halted** if any book halted |
| `halted_underlyings` | string[] | Which book is in DD halt |
| `broker_reachable` | bool | Home **Broker unreachable** |
| `market_session` | enum | Home **Market closed** when `closed` |
| `*_change_pct` | number \| null | Signed percent points (`0.42` = +0.42%) |
| `today_net` | number | `realized_pnl_today + unrealized_pnl` (idle → `0`) |
| `execution` | `manual` \| `auto` \| null | Who sends strategy orders. Always send on Start. |
| `replay` | object \| null | Mock only: `{ day, speed, sim_time, playing }`. Paper/live → `null`. |
| `paper_auto` | bool | `true` when weekday paper-auto is wanted **and** `execution` is `auto`. False/absent in mock. |
| `signals_today` | number | Compass count (paper/live). Mock uses `/signals/today`. |
| `trades_today` | number | Blotter count (paper/live). |
| `log_events_today` | number | Audit lines today. Bind on Home/Day. |
| `last_error` | string \| null | Token / last desk error. Banner only. |
| `books` | array length 2 | Home sleeve lines; Order gate copy |

Mock `GET /status`: `token_ok` is `true` (no Dhan). `market_session` follows **sim clock**. Quotes/PnL are synthetic. Same field names as paper/live.

**Banner priority (UI):** kill/halt > broker down > market closed.

---

## 2. `POST /api/v1/desk/runner/start`

**Body:**

```json
{ "mode": "paper", "operator_id": "ui" }
```

| Field | Required | Notes |
|-------|----------|--------|
| `mode` | yes (UI) | `"paper"` \| `"mock"` \| `"live"` |
| `execution` | no | `manual` (default) or `auto` on all modes |
| `speed` | no | Mock only. Default `60` (session compressed ~6 min) |
| `operator_id` | no | Default `"ops"` if omitted; send `"ui"` |

**Success `data`:**

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

Idempotent: already armed → `accepted: true`, `code: OK`, message `"server was already running"`. UI: **Paper armed**.

| `code` | `accepted` | UI |
|--------|------------|-----|
| `OK` | true | Armed (`mode` + `execution` on `data`) |
| `KILL_SWITCH` | false | **Not started** |
| `SHADOW_HALTED` | false | **Not started** (both books halted) |

Start/Stop only arm trading. They do not boot or kill uvicorn.

**One runner.** The desk has a single `mode`. Starting mock while paper-auto is running **pauses desk paper-auto** (no new Dhan places). It does **not** flatten existing Dhan paper positions. Starting paper/live **discards** the mock ledger. Live is never auto-armed by the weekday scheduler.

---

## 3. `POST /api/v1/desk/runner/stop`

**Body:**

```json
{ "operator_id": "ui", "reason": "stop" }
```

**Success `data`:**

```json
{
  "accepted": true,
  "code": "OK",
  "command": "stop",
  "runner_state": "STOPPED",
  "trading_active": false,
  "desk_process": "alive",
  "message": "trading stopped (desk API + token renew stay online)"
}
```

UI: **Trading stopped**. Open positions and working orders stay. Cancel remains allowed. New place → `TRADING_STOPPED`.

If `mode` was `paper` when Stop was sent, the weekday scheduler **pauses paper-auto for the rest of that IST day** (`paused_day`). Mock off-hours may still auto-arm. Kill switch is the only way to halt everything.

---

## 4. `GET /api/v1/desk/positions`

**Request:** no body.

**`data`:**

```json
{
  "rows": [
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
  ],
  "row_count": 2,
  "snapshot_at": "2026-08-15T10:00:00Z",
  "detail": null
}
```

| Field | Notes |
|-------|--------|
| `side` | `LONG` if qty > 0, `SHORT` if qty < 0 |
| `qty` / `quantity` | Signed exchange qty. `lots = abs(qty) / lot_size` |
| `lot_size` | From scrip master (NIFTY fallback 65) |
| `expiry` | `YYYY-MM-DD` |
| `unrealized_pnl` | Signed |

Broker error: HTTP 200, `rows: []`, `row_count: 0`, `detail` set. `/status.broker_reachable` will be false.

Empty copy: “No positions. Fills will show here.”

Each row is Buy + Sell capable (same ticket, prefilled contract).

---

## 5. `GET /api/v1/desk/orders/open`

**`data`:**

```json
{
  "orders": [
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
  ],
  "count": 1,
  "snapshot_at": "2026-08-15T10:00:00Z",
  "detail": null
}
```

`cancellable: false` when already TRADED / CANCELLED / REJECTED / EXPIRED. UI may still tap Cancel; then cancel returns `ALREADY_FILLED`.

Empty copy: “No working orders. Cancel stays available when paper is stopped.”

---

## 6. `GET /api/v1/desk/contracts`

Order chip row + ticket strike grid.

**Query:**

| Param | Required | Values |
|-------|----------|--------|
| `underlying` | yes | `NIFTY` \| `BANKNIFTY` |
| `expiry` | no | `YYYY-MM-DD`. Default = nearest weekly expiry in the master |

Example: `GET /api/v1/desk/contracts?underlying=NIFTY`

**`data`:**

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

~ATM ± a handful of strikes (min 5 when the master has them).

---

## 7. `GET /api/v1/desk/quotes/option`

Ticket live price. Poll ~1s while the ticket is open.

**Query — one of:**

- `security_id=12345`
- `underlying=NIFTY&expiry=2026-08-14&strike=25000&option_type=PE`

**`data`:**

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

`ltp` / `bid` / `ask` may be `null` (weekend, replay stopped, Dhan down, unknown contract). `stale: true` if the quote could not be refreshed. Bid/ask equal LTP when the feed has no book. **Expiry must come from `/contracts`**, not a hardcoded date.

---

## 8. `GET /api/v1/desk/quotes/spot` (optional)

Use if you do not want spots only on `/status`.

**`data`:**

```json
{
  "NIFTY": { "ltp": 24812.4, "change_pct": 0.42 },
  "BANKNIFTY": { "ltp": 51204.15, "change_pct": -0.18 }
}
```

---

## 9. `GET /api/v1/desk/gates`

**Query:** `underlying` required; `sleeve` optional (`fade` \| `orb`).

Example: `GET /api/v1/desk/gates?underlying=NIFTY`

**`data`:**

```json
{
  "trading_active": true,
  "market_session": "open",
  "underlying": "NIFTY",
  "lot_size": 65,
  "sleeves": [
    { "sleeve": "fade", "allow": true, "lots": 10, "reason": null },
    { "sleeve": "orb", "allow": false, "lots": 0, "reason": "ORB is denied after a fade loss" }
  ]
}
```

Order copy: “NIFTY fade ALLOW 10 lots” / “ORB denied today. Lot size 65.”  
Ticket: `Gate ALLOW · max 10 lots · est. costs Rs …` (costs from dry_run).

If `trading_active` is false, disable Place: “Start trading first.” Backend still rejects `dry_run: false` with `TRADING_STOPPED`. Preview (`dry_run: true`) still works.

---

## 10. `POST /api/v1/desk/orders/paper`

**Only the UI** after Buy/Sell on the ticket. The engine never places from a TRADEABLE card.

**Body:**

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
| `underlying` | yes | `NIFTY` \| `BANKNIFTY` |
| `side` | yes | `BUY` \| `SELL` |
| `lots` | yes | Integer ≥ 1. Desk computes `quantity = lots × lot_size` |
| `option_type` | yes | `CE` \| `PE` |
| `strike` | yes | number |
| `expiry` | yes | `YYYY-MM-DD` |
| `sleeve` | yes | `fade` \| `orb` |
| `dry_run` | yes | `true` = Preview (no broker). `false` = send to Dhan paper |
| `expected_ltp` | yes when `dry_run: false` | LTP shown on the ticket at tap |
| `price_tolerance` | no | Absolute points. Default **0.5** |
| `security_id` | no | Desk resolves if omitted |
| `quantity` | no | **Ignored** if `lots` is present |
| `operator_id` | no | Send `"ui"` |
| `trace_id` | no | Same id within 30s returns the original result (no double-place) |

While in flight the UI shows **Placing…** (client-only). No placing endpoint.

Desk never places at a new price after `PRICE_MOVED`. User must tap Buy/Sell again with the new `expected_ltp`.

### Preview (`dry_run: true`)

Allowed while disarmed. Does not hit the broker. Does not write a live fill.

```json
{
  "accepted": true,
  "code": "OK",
  "message": "simulated only (dry_run)",
  "gate": { "allow": true, "lots": 10, "reason": null, "sleeve": "fade" },
  "quote": { "ltp": 105.5, "bid": 105.4, "ask": 105.55, "quoted_at": "2026-08-15T04:01:02Z" },
  "contract": {
    "security_id": "12345",
    "tradingsymbol": "NIFTY2581425000PE",
    "lot_size": 65,
    "quantity": 650,
    "lots": 10,
    "strike": 25000,
    "option_type": "PE",
    "expiry": "2026-08-14",
    "underlying": "NIFTY"
  },
  "estimate": {
    "premium_value": 68575,
    "est_costs": 294.3,
    "notional": 68575
  }
}
```

`est_costs` is a desk estimate (not an exchange bill). Gate deny on preview: `accepted: false`, `code: GATE_DENY`, `contract` still present if resolved. UI **Not sent (gate)**.

### Place success (`dry_run: false`)

Requires `trading_active` and `market_session == open`.

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
  "contract": {},
  "gate": { "allow": true, "lots": 10, "reason": null, "sleeve": "fade" },
  "quote": { "ltp": 105.5, "bid": 105.4, "ask": 105.55 }
}
```

UI: **Order sent** with Size, Price, Id `client_order_id`, link Book.

### Place rejects (always HTTP 200)

| `code` | When | Extra `data` | UI |
|--------|------|----------------|-----|
| `TRADING_STOPPED` | Not armed | | Gated Order / **Not started** |
| `KILL_SWITCH` | Kill on | | **Cannot place** |
| `SHADOW_HALTED` | That underlying halted | `underlying` | **Cannot place** |
| `MARKET_CLOSED` | `market_session != open` | | Banner already on Home |
| `GATE_DENY` | Sleeve blocked or lots > max | `gate.reason`, `gate.sleeve`, `gate.lots` | **Not sent** gate |
| `PRICE_MOVED` | Live LTP vs `expected_ltp` > tolerance | `was`, `now`, `contract`, `lots` | **Price moved** |
| `BROKER_REJECT` | Dhan refused | `order` if any | **Not sent** broker |
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
  "contract": {},
  "lots": 10,
  "lot_size": 65
}
```

---

## 11. `POST /api/v1/desk/orders/cancel`

Allowed when paper is stopped.

**Body:**

```json
{ "order_id": "123456", "operator_id": "ui" }
```

**Success:**

```json
{
  "accepted": true,
  "code": "OK",
  "message": null,
  "order_id": "123456",
  "result": {}
}
```

UI: **Order cancelled**.

| `code` | UI |
|--------|-----|
| `ALREADY_FILLED` | **Not cancelled** — already filled. Check Active trades |
| `ORDER_NOT_FOUND` | **Not cancelled** |
| `KILL_SWITCH` | **Not cancelled** |
| `BROKER_REJECT` | **Not cancelled** |
| `BROKER_UNREACHABLE` | **Not cancelled** |

`order_id` is present on every cancel result.

---

## 12. `POST /api/v1/desk/sync`

**Body:** empty (`{}` or omit).

Refreshes positions, open orders, cash, rebuilds shadow state.

**Success:**

```json
{
  "accepted": true,
  "code": "OK",
  "message": "Desk state synchronized with broker.",
  "last_sync_at": "2026-08-15T08:32:00Z",
  "sync_stats": {
    "positions_updated": 1,
    "orders_updated": 0,
    "cash_updated": true,
    "shadow_rebuilt": ["NIFTY", "BANKNIFTY"],
    "shadow_errors": []
  }
}
```

**Failure:** `accepted: false`, `code: SYNC_FAILED`. UI **Sync failed**. Positions may be stale.

---

## 13. `GET /api/v1/desk/trades/today`

IST calendar day. Includes open rounds (`exit_reason: "open"`).

Optional `?day=YYYY-MM-DD` (same path; default is today). If lab journals are empty, the desk returns the VPS snapshot `data/paper/{day}.json`. Mock without `day` still returns the sim blotter.

**`data`:**

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

Empty: `trades: []`, totals `0`. Copy: “No trades today. Closed fills will list here.”

`exit_reason: "open"` → Day table may show net as `"open"`. `realized_pnl` is `null`.

---

## 14. `GET /api/v1/desk/signals/today`

Today’s engine cards only. No last-cycle fallback. **PENDING is not an auto-order.**

**`data`:**

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
    }
  ]
}
```

`status`: `PENDING` (tradeable, user has not placed) | `EXECUTED` | `SKIPPED` | `REJECTED`.

PENDING also appears on `GET /triggers/active` until acked, placed, or invalidated.

Empty: “No signals yet. PENDING can open a ticket when trading is armed.”

---

## 15. `GET /api/v1/desk/triggers/active`

Center alert. **Nothing is placed.** At most **one** interrupt is returned at a time.

Priority: unacked `fill_notice` (FIFO queue — oldest first) then, if `execution` is `manual`, newest PENDING `approval`. Auto never returns `approval`.

Acking a `fill_notice` reveals the next queued buy/sell notice. Do not skip ack or later fills stay hidden.

**Active:**

```json
{
  "active": true,
  "trigger": {
    "trigger_id": "nifty-fade-2026-08-15-1",
    "kind": "buy",
    "role": "approval",
    "underlying": "NIFTY",
    "expiry": "2026-08-14",
    "strike": 25000,
    "option_type": "PE",
    "sleeve": "fade",
    "suggested_lots": 10,
    "ltp": 105.5,
    "tradingsymbol": "NIFTY2581425000PE",
    "note": "Nothing is placed until you confirm.",
    "placeable": true,
    "created_at": "2026-08-15T04:00:01Z",
    "meta": null,
    "filled_qty": null,
    "filled_price": null,
    "side": "BUY"
  }
}
```

**None:** `{ "active": false, "trigger": null }`

| `kind` | UI title | Confirm |
|--------|----------|---------|
| `buy` | Buy trigger | Buy → ticket side BUY |
| `sell` | Sell trigger | Sell → ticket side SELL |

| `role` | UI |
|--------|-----|
| `approval` (or omitted) | Center alert → ticket if `placeable` |
| `fill_notice` | Info only. `placeable` is always false. Do **not** open a place ticket. Show `note` / `filled_qty` / `filled_price` / `side` (`BUY` or `SELL`). Toast or info sheet. Ack `dismiss`. |

Mock **auto** emits `fill_notice` for every desk-placed fill: tape entry (buy), tape exit (sell), overlay place while auto, and 15:30 square-off (sell). Same JSON as paper/live auto after a Dhan fill.

If `placeable: false` and `role` is `approval` (halt / kill / stopped): still show the alert. Confirm at 40% opacity; tap must not place. `meta`: `"Trading halted — cannot place."`

WS `health.tick.data.trigger` is the same `{ active, trigger }` object as this route.

---

## 16. `POST /api/v1/desk/triggers/ack`

**Body:**

```json
{ "trigger_id": "nifty-fade-2026-08-15-1", "action": "dismiss" }
```

`action`: `dismiss` | `opened_ticket`.

Dismiss hides that `trigger_id` until a **new** id appears. Do not build a pending-inbox screen.

**`data`:**

```json
{
  "accepted": true,
  "code": "OK",
  "message": null,
  "trigger_id": "nifty-fade-2026-08-15-1",
  "action": "dismiss"
}
```

Server **never** places from a trigger.

---

## 17. `GET /api/v1/desk/research/stable`

Locked catalog. Server picks lowest peak DD. UI does not pick the pack.

**`data` (subset UI needs):**

- `selection_rule` (string)
- `span` (e.g. `2021-07 → 2026-06`)
- `most_stable.NIFTY` / `most_stable.BANKNIFTY`
- `packs[]` with `pack_id`, `underlying`, `role`, `selection` (`most_stable` \| `alternate`), `metrics`

**Metrics** (percent **points**, not 0.184):

```json
{
  "return_pct": 18.4,
  "peak_dd_pct": 9.2,
  "net_pnl": 18400,
  "n_trades": 214,
  "avg_lots": 8
}
```

`avg_lots` is omitted when the tape has no lots — hide that clause.

Assumptions line is copy-only on the client. No extra endpoint.

---

## 18. `GET /api/v1/desk/research/stable/{NIFTY|BANKNIFTY}`

**`data`:**

```json
{
  "underlying": "NIFTY",
  "selected": {
    "pack_id": "nifty_tier1_conservative",
    "role": "Institutional DD-first (most stable)",
    "span": "2021-07 → 2026-06",
    "metrics": {},
    "chart": {
      "points": [
        { "date": "2021-07-01", "timestamp": "2021-07-01T09:15:00+05:30", "total_equity": 200000, "drawdown_pct": 0 }
      ]
    }
  },
  "alternates": []
}
```

Chip toggle: `NIFTY` vs `BANKNIFTY`.

---

## 19. `WS /ws/desk?api_key=`

Optional. Health ticks only — connecting does **not** advance trading cycles or place orders.

```json
{ "type": "connected", "server_time": "…", "channels": ["health.tick", "signal.trigger", "signal.clear"] }
{ "type": "health.tick", "server_time": "…", "data": { } }
{ "type": "signal.trigger", "server_time": "…", "data": { } }
{ "type": "signal.clear", "server_time": "…", "data": { "trigger_id": "…" } }
```

`health.tick.data` is a subset of `GET /status` plus `trigger` (same object as `GET /triggers/active`).  
`signal.trigger.data` matches `GET /triggers/active.trigger`.  
Tick interval: **~1 s in mock**, ~5 s in paper/live.

---

## Result-code map (UI cards)

| UI story | Trigger | `code` |
|----------|---------|--------|
| Placing… | Client, request in flight | — |
| Order sent | Place `accepted` | `OK` |
| Not sent (gate) | Place | `GATE_DENY` |
| Not sent (broker) | Place | `BROKER_REJECT` / `BROKER_UNREACHABLE` / `CONTRACT_RESOLVE_FAILED` |
| Price moved buy/sell | Place | `PRICE_MOVED` |
| Cannot place | Place or trigger | `SHADOW_HALTED` / `KILL_SWITCH` |
| Not started | Start | `KILL_SWITCH` / `SHADOW_HALTED` |
| Paper armed | Start | `OK` |
| Trading stopped | Stop | `OK` |
| Order cancelled | Cancel | `OK` |
| Not cancelled | Cancel | `ALREADY_FILLED` / `ORDER_NOT_FOUND` / `KILL_SWITCH` / `BROKER_REJECT` |
| Sync failed | Sync | `SYNC_FAILED` |
| New signal | Second trigger while ticket open | new `trigger_id` on `/triggers/active` |

---

## Operator flows → API sequence

### Sign in

BFF only (`POST /api/auth/login`). Desk unused until the session exists.

### Home idle

`GET /status` → `today_net: 0`, `open_positions: 0`, `trading_active: false`  
`GET /positions` → empty  
`GET /triggers/active` → `active: false`

### Start paper

Confirm → `POST /runner/start` `{ "mode": "paper", "operator_id": "ui" }` → **Paper armed**

### Trigger → ticket → place

1. `GET /triggers/active` or WS `signal.trigger`
2. User Buy/Sell (no API)
3. `GET /quotes/option` + `GET /gates`
4. Optional preview: `POST /orders/paper` `dry_run: true`
5. Place: `dry_run: false` + `expected_ltp` + `trace_id`
6. Success → poll `/orders/open`
7. Fill → row on `/positions`; working order disappears

Row Buy/Sell on Active trades skips step 1; prefills contract from the position.

### Stop

`POST /runner/stop`. Positions remain.

### Cancel

UI confirm → `POST /orders/cancel`. Allowed while stopped.

### Lab

`GET /research/stable` then `GET /research/stable/NIFTY` (chip toggle BANKNIFTY).

---

## Out of MVP (do not call from the trader app)

Keep on the server for ops. Do not wire screens to these.

| Path | Why |
|------|-----|
| `GET /api/v1/desk/health/full` | Nested ops dump |
| `GET /api/v1/desk/runner` | Use `/status` |
| `/signals/last-cycle`, `/signals/rejected` | Use `/signals/today` |
| `/safety/*` | Kill is read-only on `/status` |
| `/audit/*` | Forensics |
| `/orders/queue` | Internal |
| `/cycle/tick` | Runner-internal |
| `/system/token*` | No token/PIN/TOTP UI |

---

## Env

Desk:

```
DESK_API_KEY=…
DESK_MODE=paper
NIFTY_LAB_ROOT=…
BN_LAB_ROOT=…
```

UI BFF (server-only):

```
DESK_API_URL=https://…   # or http://127.0.0.1:8080 for a local desk
DESK_API_KEY=…
DESK_HOP_TIMEOUT_MS=15000
```

Do not add `NEXT_PUBLIC_DESK_API_KEY`.

---

## Mock replay (additive)

Same 19 trader routes. Mock is **live-shaped**: same Start body, same `/orders/paper`, same interrupt pipe. The only difference is **no broker APIs** (synthetic marks + sim ledger).

**Full mode × execution matrix:** [`MODE_SCENARIO_MATRIX.md`](./MODE_SCENARIO_MATRIX.md). Handshake: [`UI_COLLAB.md`](./UI_COLLAB.md).

```json
{ "mode": "mock", "execution": "auto", "operator_id": "ui", "speed": 60 }
```

| `execution` | Desk | UI |
|-------------|------|-----|
| `manual` | `role: approval` at tape `entry_at`; user `POST /orders/paper` | Center sheet → ticket if `placeable` |
| `auto` | Desk fills tape (and overlay places while auto); **`role: fill_notice`** for each BUY and SELL | Info toast/sheet. **Do not** place. Ack to see the next queued fill |

- `GET /status` includes `execution` and `replay: { day, speed, sim_time, playing }`. `market_session` follows sim time.
- Mock place always returns `broker_order_id` like `mock_broker_{uuid}`.
- Positions may include additive `tape_qty` / `overlay_qty` (UI may ignore).
- Tape `exit_at` closes **tape qty** only; overlay qty stays until user SELL or 15:30 square-off.
- **sync:** HTTP 200 `OK` without Dhan.
- Next mock Start resets the replay day. Stop freezes the ledger; process stays up.

---

## Weekday session schedule (as-built, `DESK_PAPER_AUTO=1`)

Process stays up overnight. **Never arms `live`.** One runner (see Start).

| Clock (IST) | Desk | UI |
|-------------|------|-----|
| Weekend / before ~09:10 Mon–Fri / after ~15:45 | Arms **mock + auto** (60x) if not already trading | Mock Auto; fill_notice on sim fills |
| Mon–Fri ~09:10 | Discards mock; arms **paper + auto** both books | Paper Auto; Dhan marks; fill_notice on PENDING place |
| 09:15–15:30 | Places newest PENDING compass cards on Dhan paper | Do not also POST `/orders/paper` for those cards |
| 15:30–15:45 | One EOD flatten of leftover longs + fill_notice sell | Info only |
| after 15:45 | Disarms paper; arms **mock + auto** again | Back to mock |

UI **Stop** while paper: pause paper-auto **that IST day only**. Kill switch: no schedule arms.

Home/Day bind `today_net`, `signals_today`, `trades_today`, `log_events_today`, `paper_auto`, `execution`, `mode`.


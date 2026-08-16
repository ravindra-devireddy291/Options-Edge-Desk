# UI collaboration handshake

**Audience:** `my-options-trader` (Next.js BFF + screens)  
**Source of truth for field names:** [`BACKEND_REQUIREMENTS.md`](./BACKEND_REQUIREMENTS.md)  
**Shapes / codes:** [`UI_API_CONTRACT.md`](./UI_API_CONTRACT.md)  
**Who places / who fills:** [`MODE_SCENARIO_MATRIX.md`](./MODE_SCENARIO_MATRIX.md)

This file is the **as-built** desk the UI must wire to. Same 19 trader routes in every mode. Mode only changes **data source** and **who sends** the strategy order.

---

## 1. How the UI talks to the desk

| Rule | Detail |
|------|--------|
| Browser | Only `/api/desk/*` on the Next origin. Never the desk host. Never `X-API-Key` in JS. |
| BFF | Server env `DESK_API_URL` + `DESK_API_KEY`. Header `X-API-Key` on every JSON route except `/healthz`. |
| Origin | Local desk `http://127.0.0.1:8080`. Hosted desk `https://…` (Cloudflare). No `:8080` from Vercel. |
| Envelope | `{ ok, server_time, data }` on `/api/v1/desk/*`. `ok: true` = desk answered, **not** “order filled”. |
| Mutations | HTTP 200 + `data.accepted` + `data.code`. Map `accepted: false` to a result card, not a network crash. |
| WS | Optional. BFF only: `ws://` or `wss://{host}/ws/desk?api_key=`. Prefer `GET /snapshot` + WS deltas; does not replace REST place/cancel. |

Do **not** set `NEXT_PUBLIC_DESK_API_KEY`, `NEXT_PUBLIC_API_BASE_URL`, or `NEXT_PUBLIC_DESK_USE_MOCK`.

---

## 2. Trader inventory (call only these)

JSON paths are relative to `{DESK_API_URL}/api/v1/desk` except `/healthz` and `/ws/desk`.

| # | Method | Path | Screen | Auth |
|---|--------|------|--------|------|
| 0 | GET | `/healthz` | Connectivity | none |
| 1 | GET | `/status` | Home | key |
| 1b | GET | `/snapshot` | Boot + reconcile | key |
| 2 | POST | `/runner/start` | Start confirm | key |
| 3 | POST | `/runner/stop` | Stop confirm | key |
| 4 | GET | `/positions` | Home + Book | key |
| 5 | GET | `/orders/open` | Book | key |
| 6 | POST | `/orders/paper` | Ticket (all modes, including live) | key |
| 7 | POST | `/orders/cancel` | Book | key |
| 8 | GET | `/trades/today` | Day | key |
| 9 | GET | `/signals/today` | Compass | key |
| 10 | POST | `/sync` | Broker banner | key |
| 11 | GET | `/research/stable` | Lab catalog | key |
| 12 | GET | `/research/stable/{NIFTY\|BANKNIFTY}` | Lab book | key |
| 13 | GET | `/contracts?underlying=` | Ticket chain | key |
| 14 | GET | `/quotes/option` | Ticket LTP | key |
| 15 | GET | `/quotes/spot` | Optional tape | key |
| 16 | GET | `/gates?underlying=` | Ticket / Order banner | key |
| 17 | GET | `/triggers/active` | Center interrupt | key |
| 18 | POST | `/triggers/ack` | Dismiss interrupt | key |
| 19 | WS | `/ws/desk` | `health.tick` + trigger | query key |

**Do not call from the trader UI:** `/health/full`, `/runner` GET, `/cycle/tick`, `/orders/queue`, `/signals/last-cycle`, `/signals/rejected`, `/safety/*`, `/system/token*`, `/audit/*`.

### Polling if WS unused

| Resource | When |
|----------|------|
| `/status` | 5–15 s signed in (mock playing: ~1 s) |
| `/quotes/option` | 1 s while ticket open |
| `/triggers/active` | 2–5 s if WS down |
| Book / Day | Tab focus + after place / cancel / sync / ack |
| Lab | Tab focus |
| `/contracts` | Ticket open / underlying change — **do not hardcode expiry** |

---

## 3. Architecture the UI must model

Two independent axes on Start:

```json
{ "mode": "mock", "execution": "manual", "operator_id": "ui", "speed": 60 }
```

| Axis | Values | Meaning |
|------|--------|---------|
| `mode` | `mock` \| `paper` \| `live` | Where marks and fills come from |
| `execution` | `manual` \| `auto` | Who sends the **strategy** order |

Send `execution` on **all three** modes. Overlay (user scale-in / early exit) is always the user: same `POST /orders/paper`.

```
                 MANUAL                              AUTO
MOCK    Approval → ticket → /orders/paper     Desk fills tape (no Dhan); fill_notice BUY/SELL
PAPER   PENDING approval → user places        Desk places PENDING on Dhan; fill_notice
LIVE    Same as paper, live Dhan              Same as paper-auto, live Dhan
```

Mock uses the **same routes and trigger JSON as live**. Only the data source changes (sim ledger vs Dhan).

**One runner:** Start mock while paper is armed pauses desk paper-auto (Dhan positions are not flattened). Start paper discards mock. The weekday scheduler never arms live.

| `GET /status` | Mock | Paper / live |
|---------------|------|----------------|
| `mode` | `mock` | `paper` or `live` |
| `execution` | `manual` \| `auto` | `manual` \| `auto` |
| `replay` | `{ day, speed, sim_time, playing }` | `null` |
| `token_ok` | true (no Dhan for books) | Dhan fund ping — may be false until token refresh |
| Quotes / PnL | Synthetic tape | Dhan (null LTP when market closed or token stale) |
| `POST /sync` | Snapshot ledger, no broker | Dhan + shadow rebuild |

Process boot is always **STOPPED**. Start/Stop only arm trading; uvicorn stays up.

`POST /orders/paper` is the only place route for mock, paper, **and** live. There is no `/orders/live`.

---

## 4. One interrupt pipe, two roles

Same object on `GET /triggers/active`, WS `signal.trigger`, and `health.tick.data.trigger`.

| `role` | When | UI |
|--------|------|-----|
| `approval` (or omitted) | Manual: strategy wants BUY/SELL | Center sheet → ticket if `placeable`. Ack `opened_ticket` or `dismiss`. |
| `fill_notice` | Auto/engine **already** filled (buy or sell) | Info only. `placeable` is always `false`. **Do not** open a place ticket. Show `note` / `filled_qty` / `filled_price` / `side`. Ack `dismiss` to receive the **next** queued fill. |

If `placeable: false` and `role` is `approval` (halt / kill / stopped): show the alert, disable confirm, do not place.

Never `POST /orders/paper` just because a trigger appeared in **auto** (that double-fills mock tape / double-places paper).

Ack with the real `trigger_id` from the payload (not a fixture id). Fill notices are a FIFO queue.

---

## 5. Ticket chain and quotes (do not freeze calendar)

1. `GET /contracts?underlying=NIFTY` (or BANKNIFTY). Use `data.expiry` (nearest weekly), `atm_strike`, `strikes`, `lot_size`.
2. `GET /quotes/option?underlying=&expiry=&strike=&option_type=` using **those** fields (or `security_id`).
3. Treat `ltp` / `bid` / `ask` as **number or null**. `stale: true` and nulls are valid HTTP 200 (weekend, replay stopped, Dhan down, wrong expiry).
4. Keep fixture LTP only as last-resort display; do not fail Zod on null.
5. Place body still uses `expected_ltp` when you have a number; if LTP is null, do not pretend the fixture is the live mark.

Wrong: hardcoded `expiry=2026-08-14`. Desk nearest NIFTY expiry moves (e.g. `2026-08-18`).

---

## 6. Positions / books (additive keys)

Mock positions may include `tape_qty` and `overlay_qty`. Ignore if unused.

Empty books are valid: `rows: []`, `orders: []`, `trades: []`.

---

## 7. UI checklist vs this desk

| Item | Desk | UI should |
|------|------|-----------|
| `mode` includes `live` | Yes | Parse + Start venue Live |
| `execution` on paper/live | Yes | Send on Start; show Manual/Auto for all modes |
| Fill notice | Yes (queue, buy and sell) | Skip ticket; info toast/sheet; ack to show next |
| `paper_auto`, `signals_today`, `trades_today`, `log_events_today` | Yes on `/status` | Home/Day counts |
| Contracts-driven expiry | Yes | Bind ticket to `/contracts` |
| Nullable option quotes | Yes | Zod `number \| null`; `stale` |
| Real `trigger_id` on ack | Yes | Copy from `/triggers/active` |
| BFF HTTPS + key | Yes | Server env only |
| Dhan token refresh | Ops (`token_ok`) | Banner only — no PIN/TOTP in trader UI |
| Weekday paper-auto | Desk scheduler | Show Paper Auto in cash window; mock auto off-hours |

---

## 8. Hosted desk notes

- Desk listens on `127.0.0.1:8080` on the VPS. Public access is HTTPS tunnel / named hostname → BFF `DESK_API_URL`.
- Quick `trycloudflare.com` hostnames change if that process restarts — update `.env.local` and bounce Next.
- Paper/live quotes stay empty until Dhan token is valid (`token_ok`). Mock does not need Dhan.
- Lab `/research/stable*` is **mode-independent**. Mock tape is always the locked `most_stable` pack, not the Lab chip.

## 9. Weekday schedule (`DESK_PAPER_AUTO=1`)

Set `DESK_PAPER_AUTO=1` on the desk. The process stays up overnight. **Never arms live.**

| Clock (IST) | Desk |
|-------------|------|
| Weekend, before ~09:10 weekdays, after ~15:45 | **mock + auto** (sim tape, no Dhan). Fill_notice on every auto BUY/SELL |
| Mon–Fri ~09:10 | Discard mock; arm **paper + auto** for **both** NIFTY and BANKNIFTY |
| 09:15–15:30 | Place newest PENDING compass cards on Dhan paper; fill_notice |
| 15:30–15:45 | One EOD flatten of leftover longs |
| after 15:45 | Disarm paper; arm mock + auto again |

Stop in the UI while **paper** pauses paper-auto **only that IST day**. Kill switch blocks all schedule arms.

`GET /status` additive: `execution`, `replay`, `paper_auto`, `signals_today`, `trades_today`, `log_events_today`, `last_error`.

Events append to `data/audit/events_YYYY-MM-DD.jsonl` and order lines to `orders_YYYY-MM-DD.jsonl` (IST session day). Paper/live also overwrite `data/paper/YYYY-MM-DD.json` (positions, open orders, Day blotter, compass, Dhan trade book) on every place, ~30s while armed, and at session end. Survives mock overnight and desk restart. `GET /trades/today` and `/signals/today` optional `?day=YYYY-MM-DD`; if journals are empty the desk returns that archive.

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
| WS | Optional. BFF only: `ws://` or `wss://{host}/ws/desk?api_key=`. Does not replace REST place/cancel. |

Do **not** set `NEXT_PUBLIC_DESK_API_KEY`, `NEXT_PUBLIC_API_BASE_URL`, or `NEXT_PUBLIC_DESK_USE_MOCK`.

---

## 2. Trader inventory (call only these)

JSON paths are relative to `{DESK_API_URL}/api/v1/desk` except `/healthz` and `/ws/desk`.

| # | Method | Path | Screen | Auth |
|---|--------|------|--------|------|
| 0 | GET | `/healthz` | Connectivity | none |
| 1 | GET | `/status` | Home | key |
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
MOCK    Approval → ticket → /orders/paper     Desk fills tape; fill_notice
PAPER   PENDING approval → user places        Desk places PENDING on Dhan; fill_notice
LIVE    Same as paper, live Dhan              Same as paper-auto, live Dhan
```

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
| `fill_notice` | Auto/engine **already** filled | Info only. `placeable` is always `false`. **Do not** open a place ticket. Show `note` / `filled_qty` / `filled_price` / `side`. Ack `dismiss`. |

If `placeable: false` and `role` is `approval` (halt / kill / stopped): show the alert, disable confirm, do not place.

Never `POST /orders/paper` just because a trigger appeared in **auto** (that double-fills mock tape).

Ack with the real `trigger_id` from the payload (not a fixture id).

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
| Fill notice | Yes | Skip ticket; optional info sheet |
| Contracts-driven expiry | Yes | Bind ticket to `/contracts` |
| Nullable option quotes | Yes | Zod `number \| null`; `stale` |
| Real `trigger_id` on ack | Yes | Copy from `/triggers/active` |
| BFF HTTPS + key | Yes | Server env only |
| Dhan token refresh | Ops (`token_ok`) | Banner only — no PIN/TOTP in trader UI |
| Paper/live Start on VPS | Armed until Stop | Do not leave auto running unattended |

---

## 8. Hosted desk notes

- Desk listens on `127.0.0.1:8080` on the VPS. Public access is HTTPS tunnel / named hostname → BFF `DESK_API_URL`.
- Quick `trycloudflare.com` hostnames change if that process restarts — update `.env.local` and bounce Next.
- Paper/live quotes stay empty until Dhan token is valid (`token_ok`). Mock does not need Dhan.
- Lab `/research/stable*` is **mode-independent**. Mock tape is always the locked `most_stable` pack, not the Lab chip.

## 9. Paper auto (weekday session)

Set `DESK_PAPER_AUTO=1` on the desk. The process stays up overnight.

| Clock (IST, Mon–Fri) | Desk |
|----------------------|------|
| ~09:10 | Arms `mode: paper`, `execution: auto` for **both** NIFTY and BANKNIFTY books |
| 09:15–15:30 | Places newest PENDING compass cards on Dhan paper; fill_notice on the interrupt pipe |
| 15:30–15:45 | One EOD flatten of leftover longs |
| after 15:45 | Disarms. Next morning arms again |

Stop in the UI pauses **only that IST day**. Live is never auto-armed.

Events append to `data/audit/events_YYYY-MM-DD.jsonl` and order lines to `orders_YYYY-MM-DD.jsonl`. Home/Day bind `today_net`, compass, blotter, `signals_today`, `trades_today`, `log_events_today`.

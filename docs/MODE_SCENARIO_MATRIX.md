# Mode × execution matrix — what the desk does vs what the product needs

**Audience:** Client architects + UI/OMS  
**Desk:** `Options-Edge-Desk` `/api/v1/desk`  
**UI handshake:** [`UI_COLLAB.md`](./UI_COLLAB.md)  
**Companions:** [`BACKEND_REQUIREMENTS.md`](./BACKEND_REQUIREMENTS.md) (field freeze), [`UI_API_CONTRACT.md`](./UI_API_CONTRACT.md) (shapes), [`BACKEND_BUSINESS_LOGIC.md`](./BACKEND_BUSINESS_LOGIC.md) (accounting)

This file is the **scenario source of truth**. Cells below are **AS-BUILT** after Phases 1–3 (ledger lock, live/paper-auto, fill notices).

---

## 0. Two independent axes

| Axis | Values | Meaning |
|------|--------|---------|
| **`mode`** | `mock` \| `paper` \| `live` | Where money/marks come from |
| **`execution`** | `manual` \| `auto` | Who is allowed to **send** the strategy order |

Start body:

```json
{ "mode": "mock", "execution": "manual", "operator_id": "ui", "speed": 60 }
```

| Field | AS-BUILT |
|-------|----------|
| `mode: "mock"` | Arms sim ledger. No Dhan for quotes/place/PnL. |
| `mode: "paper"` | Arms Dhan paper + lab shadow. Honors `execution`. |
| `mode: "live"` | Arms Dhan live credentials. Honors `execution`. |
| `execution` | `manual` \| `auto` on **all** modes. |

```
                    MANUAL                         AUTO
MOCK     Approval trigger → ticket         Desk fills tape; fill_notice
         → POST /orders/paper              Overlay still /orders/paper
PAPER    Shadow PENDING → approval         Desk places PENDING on Dhan
         → user places                     fill_notice after fill
LIVE     Same as paper, live Dhan          Same as paper-auto, live Dhan
```

---

## 1. Two kinds of center interrupt (same JSON family)

The UI already has **one** interrupt pipe: `GET /triggers/active` + WS `signal.trigger` / `signal.clear` + `POST /triggers/ack`.

Product needs **two roles** on that same pipe. Do **not** add a new trader route.

| Role | When | User action | `placeable` | `note` (intent) |
|------|------|-------------|----------------|-----------------|
| **`approval`** | Manual: strategy wants a BUY or SELL | Open ticket / dismiss | `true` if trading open | `Nothing is placed until you confirm.` |
| **`fill_notice`** | Auto: desk **already** bought or sold | Dismiss only (info) | **`false` always** | e.g. `Desk bought 100 lots NIFTY 24000 PE at 12.40.` |

```json
{
  "active": true,
  "trigger": {
    "trigger_id": "…",
    "kind": "buy",
    "role": "approval",
    "underlying": "NIFTY",
    "expiry": "2026-06-25",
    "strike": 24000,
    "option_type": "PE",
    "sleeve": "fade",
    "suggested_lots": 100,
    "ltp": 12.4,
    "tradingsymbol": "…",
    "note": "Nothing is placed until you confirm.",
    "placeable": true,
    "created_at": "…Z",
    "meta": null
  }
}
```

| Field | AS-BUILT | Intended additive |
|-------|----------|-------------------|
| `kind` | `buy` \| `sell` | Unchanged |
| `placeable` | Manual: gate/kill/session. Fill notice: always `false` | — |
| `role` | `approval` \| `fill_notice` | Shipped |
| `filled_qty` / `filled_price` / `side` | On fill_notice (nullable on approval) | Shipped |

**UI rule:**

- `role` missing or `approval` + `placeable` → existing center alert → Order ticket.
- `role: fill_notice` → **info** toast/sheet (“Bought …” / “Sold …”). **Do not** open a place ticket. Ack dismisses it.
- Overlay (user scale-in / early exit) is **never** a trigger. User opens Order themselves and `POST /orders/paper`.

**AS-BUILT vs that rule:**

| Cell | Approval trigger | Fill notice |
|------|------------------|-------------|
| Mock manual | Yes, at `entry_at`, kind `buy`. Tape `exit_at` is fill_notice sell (not approval). | Tape exit + 15:30 |
| Mock auto | Off | Entry, tape exit, EOD |
| Paper / live manual | Newest PENDING shadow card | No (user placed) |
| Paper / live auto | Off | After desk Dhan fill + EOD flatten |

### Overlay vs strategy (all modes)

| Event | Approval? | Fill notice? |
|-------|-----------|----------------|
| Strategy entry (manual) | Yes | No (user just placed) |
| Strategy entry (auto) | No | Yes |
| Strategy exit / SL / TP (manual mock) | No — tape qty closed by engine | Yes, kind `sell` |
| Strategy exit (auto) | No | Yes, kind `sell` |
| User overlay BUY/SELL | No (paper/live; user initiated) | **Mock auto: yes** `fill_notice`. Paper/live overlay: no |
| 15:30 session square-off | No | Yes, kind `sell`, reason `session_close` |

---

## 2. Cell-by-cell behavior

### 2.1 Mock + Manual — AS-BUILT

| Step | Desk | UI |
|------|------|-----|
| Start | `{ mode: mock, execution: manual, speed }` resets sim day | Mock + Manual |
| Clock | Sim 09:15–15:30 IST, accelerated | `status.replay` |
| Before `entry_at` | Compass `PENDING`; trigger **not** active | No alert |
| At `entry_at` | `/triggers/active` kind `buy`, `placeable` if armed | Center alert → ticket |
| User ignore until `skip_at` | `SKIPPED` | Alert gone; no position |
| User `POST /orders/paper` BUY | Tape qty; `broker_order_id` = `mock_broker_{uuid}` | Order sent |
| At `exit_at` | Auto-sell **`tape_qty` only**; overlay stays | Day reason; fill_notice sell |
| 15:30 | Flatten leftover tape + overlay, `session_close` | Session closed |
| Overlay | Extra BUY = overlay qty; SELL overlay-first | Same ticket API |

### 2.2 Mock + Auto — AS-BUILT

| Step | AS-BUILT |
|------|----------|
| Start | `execution: auto` |
| `/triggers/active` | `fill_notice` after desk BUY/SELL (entry, tape exit, EOD). Not approval. |
| Entry | Keeper fills tape lots; compass `EXECUTED` / `auto` |
| Overlay | User `/orders/paper` still allowed |
| Tape exit | Sells `tape_qty` only; fill_notice sell |
| WS | `health.tick.trigger` + `signal.trigger` with `role: fill_notice` |

Keeper (`asyncio` loop ~0.25s) runs **without UI polling**. GET does not drive fills.

### 2.3 Paper + Manual — AS-BUILT (production MVP)

| Step | Desk | UI |
|------|------|-----|
| Start | `{ mode: paper, execution, operator_id }` | Paper armed. Bind `execution` from `/status` |
| Clock | Wall IST 09:15–15:30 | `market_session` from wall clock |
| Signals | Today’s lab shadow journals | Compass |
| Trigger | Newest unacked `PENDING` | Approval alert; `kind` from signal `action` |
| Place | **Only** user `POST /orders/paper`. Engine **must not** place | Ticket |
| Marks | Dhan quotes / positions | Live LTP, MTM |
| Day | Shadow blotter | Trades + compass |
| Ignore / skip window | **No** mock-style 8-minute skip. Card stays PENDING until journal/fill | User dismiss via ack |

### 2.4 Paper + Auto — AS-BUILT

`execution: auto` with `mode: paper`. `_broker_auto_keeper` (~1s) places the newest PENDING compass card on Dhan (gates/kill/session still apply). `trace_id` `auto:{signal_id}` → Dhan `correlationId`. Then `fill_notice`. Overlay still `/orders/paper`. After cash close, one EOD flatten attempt of leftover longs (`force_session_close`).

### 2.5 Live + Manual / Auto — AS-BUILT

Start `mode: live` → `OK` (same halt/kill rules as paper). Manual = user places. Auto = same keeper as paper-auto against live Dhan credentials. `tag` `edge-desk-live`. Process boot still **STOPPED** (does not auto-resume live).

---

## 3. Same REST inventory — what changes per cell

All trader screens use the **same routes**. Mode only changes **data source** and **who places**.

| # | Route | Mock manual | Mock auto | Paper manual | Paper auto | Live |
|---|--------|-------------|-----------|--------------|------------|------|
| 0 | `GET /healthz` | Process up. Not PnL | same | same | same | same |
| 1 | `GET /status` | Sim spots, mock books, `execution`, `replay`, `today_net` from ledger | same | Dhan spots + shadow PnL; `execution` | same | live Dhan + `execution` |
| 2 | `POST /runner/start` | Reset tape | Reset tape, auto fills | Arm Dhan + execution | Arm Dhan auto | Arm live + execution |
| 3 | `POST /runner/stop` | Freeze ledger, clock pause | same | Disarm; positions remain at Dhan | same | same |
| 4 | `GET /positions` | Mock rows; additive `tape_qty`/`overlay_qty` | same | Dhan non-zero rows | same | same |
| 5 | `GET /orders/open` | Working mock only (fills are already `TRADED` → usually empty) | same | Dhan working | same | same |
| 6 | `POST /orders/paper` | User overlay + manual tape fill | Overlay only (tape already filled) | User strategy + overlay | Overlay (desk placed strategy) | same as paper |
| 7 | `POST /orders/cancel` | `ALREADY_FILLED` if mock fill | same | Dhan cancel | same | same |
| 8 | `GET /trades/today` | Mock blotter | same | Shadow journals | same | same |
| 9 | `GET /signals/today` | Tape rows PENDING/EXECUTED/SKIPPED | EXECUTED/auto on fill | Today’s journals | same | same |
| 10 | `POST /sync` | Snapshot sim; no Dhan | same | Dhan + shadow rebuild | same | same |
| 11–12 | `GET /research/stable*` | Lab packs (does **not** pick mock tape) | same | same | same | same |
| 13 | `GET /contracts` | Tape strikes / dummy expiry | same | Dhan master | same | same |
| 14 | `GET /quotes/option` | Synthetic LTP=bid=ask (null if replay idle / unknown) | same | Dhan marketfeed (often null off-session) | same | same |
| 15 | `GET /quotes/spot` | Dummy index path | same | Dhan spots | same | same |
| 16 | `GET /gates` | Simplified mock sleeves | same | Lab `check_gate` | same | same |
| 17 | `GET /triggers/active` | Approval buy at `entry_at` | `fill_notice` after fills | Approval from PENDING | `fill_notice` after Dhan fill | same as paper |
| 18 | `POST /triggers/ack` | Hides that `trigger_id` | same | same | same | same |
| 19 | `WS /ws/desk` | `health.tick` + `signal.trigger` (approval or fill_notice) | same | same | same | same |

Lab research is **mode-independent**. Mock tape is always `most_stable`, not the Lab chip.

---

## 4. Tick, PnL, and “changed” data (no extra APIs)

There is **no** dedicated tick WebSocket for option LTP and **no** delta/diff endpoint. The UI reconstructs “live” from poll + the existing WS.

### 4.1 Index / Home tape (spots + session + net)

| Channel | Payload | Cadence |
|---------|---------|---------|
| `GET /status` | spots, `%`, `today_net`, `unrealized_pnl`, `realized_pnl_today`, `open_positions`, books, session | 5–15 s |
| `WS health.tick` | **Subset:** process, trading, mode, token, kill, halt, broker, session, two spots, `today_net`, `open_positions`, mock `execution`/`replay` | ~5 s |
| `GET /quotes/spot` | Optional extra spots | As needed |

`health.tick` is **not** full `/status` (no `books[]`, no full PnL split besides `today_net`). After a fill, poll `/status` + `/positions` (or rely on next health.tick `today_net` / `open_positions`).

### 4.2 Option LTP (ticket)

| Channel | Mock | Paper |
|---------|------|-------|
| `GET /quotes/option` | Interpolated tape premium; poll **1 s** while ticket open | Dhan LTP/bid/ask; same poll |
| WS | **None** for option LTP | **None** |

### 4.3 Position MTM / live PnL

| Channel | Mock | Paper |
|---------|------|-------|
| `GET /positions` | `ltp`, `unrealized_pnl`, `average_price`, qty, `tape_qty`, `overlay_qty` | Dhan MTM |
| `GET /status` | Desk `unrealized_pnl`, `today_net`, `books[].open_mtm` | Shadow realized + broker MTM |
| Mock keeper | Re-marks all open rows every ~0.25 s **even if UI is closed** | N/A — broker is source of truth; poll/sync |

### 4.4 Trades / compass (“what filled”)

| Channel | Use |
|---------|-----|
| `GET /trades/today` | Day blotter: open + closed rounds, `exit_reason`, `net_pnl` |
| `GET /signals/today` | Compass: PENDING / EXECUTED / SKIPPED (mock) or journal statuses (paper) |
| Fill notice | Toast at the moment of auto BUY/SELL; blotter remains the system of record |

There is no `/pnl/stream` and no “changed since cursor” API. **GAP (optional):** client may ask for `updated_at` on position rows; not required for MVP if they poll Book on focus + after trigger/fill.

### 4.5 Who must keep polling

| UI closed / laptop sleep | Mock auto/manual | Paper |
|--------------------------|------------------|-------|
| Engine still runs? | **Yes** (keeper) | Paper: Dhan/lab continue; desk does not auto-place |
| UI state | Stale until next `/status` / WS reconnect | Same |
| Missed approval trigger | Next `/triggers/active` shows newest PENDING (if not skipped) | Newest PENDING |
| Missed auto fill | Positions/Day already updated; newest unacked fill_notice on `/triggers/active` | Same |

---

## 5. Who is allowed to send an order

| Cell | Strategy BUY | Strategy SELL / exit | Overlay BUY/SELL |
|------|----------------|----------------------|------------------|
| Mock manual | User `/orders/paper` after approval | Desk auto `tape_qty` at `exit_at`; user may SELL overlay/tape early | User `/orders/paper` |
| Mock auto | Desk (keeper) | Desk `tape_qty` at `exit_at`; EOD all leftover | User `/orders/paper` |
| Paper manual | User `/orders/paper` only | User `/orders/paper` (desk does not auto-exit paper) | User |
| Paper auto | Desk `_broker_auto_keeper` | EOD flatten attempt after cash close | User `/orders/paper` |
| Live manual | User `/orders/paper` | User | User |
| Live auto | Same keeper, live Dhan | EOD flatten | User |

---

## 6. Start / status fields the UI should bind

| Key | Mock | Paper | Live |
|-----|------|-------|------|
| `mode` | `mock` | `paper` | `live` |
| `execution` | `manual` \| `auto` | `manual` \| `auto` | `manual` \| `auto` |
| `replay` | `{ day, speed, sim_time, playing }` | `null` | `null` |
| `market_session` | Sim clock | Wall IST | Wall IST |
| `token_ok` | Forced true for mock accounting | Dhan fund ping | Dhan fund ping |
| `broker_reachable` | true (no Dhan) | Dhan ping | Dhan ping |

UI should show Manual/Auto on Start for **all** modes and send `execution` on the body.

---

## 7. Gap register (review this list)

Client: mark **Need** / **Defer** / **OK as-built**. Desk will only implement **Need**.

| ID | Gap | Why it matters | Suggested fix (additive) |
|----|-----|----------------|--------------------------|
| G1 | Mock auto fill_notice | **Shipped** | REST + WS `role: fill_notice` |
| G2 | Tape exit / 15:30 sell info | **Shipped** | fill_notice `kind: sell` |
| G3 | `role` on trigger | **Shipped** | `approval` \| `fill_notice` + filled_* / side |
| G4 | Paper `execution: auto` | **Shipped** | `_broker_auto_keeper` |
| G5 | Paper auto engine | **Shipped** | PENDING → Dhan; overlay still UI |
| G6 | Live disabled | **Removed** | Start `mode: live` accepted |
| G7 | No option-LTP WS | Keep REST poll | Ticket polls 1 s |
| G8 | `health.tick` subset | **Shipped additive** | `data.trigger` same as `/triggers/active` |
| G9 | No sell **approval** on mock tape exit | Keep | fill_notice only |
| G10 | Paper has no 8-min skip | Keep | PENDING until journal/fill |

---

## 8. Recommended UI wiring (all modes)

1. Bind **mode** and **execution** from `/status` (all modes).
2. Poll `/status` for tape, `today_net`, banners. Use WS `health.tick` as a hint, not as the only PnL source.
3. Poll `/triggers/active` (or WS) for **one** interrupt.
4. If `placeable === true` (and `role !== fill_notice`) → approval → ticket → `POST /orders/paper`.
5. If `role === fill_notice` **or** `placeable === false` with a fill note → toast only → `POST /triggers/ack`.
6. Book/Day: `/positions`, `/orders/open`, `/trades/today`, `/signals/today` on focus and after place/ack/sync.
7. Ticket chain: `/contracts` then `/quotes/option` 1 s. Gates: `/gates`. Null LTP is valid.
8. Never auto-call `/orders/paper` from the UI because a trigger appeared in **auto** (that would double-fill mock tape).

Until fill_notice is acked, Auto users also see Book/Day. Toast comes from `/triggers/active` / WS.

---

## 9. How to use this file in client review

1. Confirm the **six-cell** table in §0 (mock/paper/live × manual/auto).
2. Confirm interrupt split: **approval vs fill_notice** (§1).
3. G1–G6 are shipped. Remaining: G7 option-LTP WS (defer — poll), G9 no sell approval on tape exit (keep fill_notice), G10 paper has no 8-min skip (keep).
4. Field names stay frozen in `BACKEND_REQUIREMENTS.md`. `role` / fill fields are **optional additive** — safe for old UIs that ignore unknown keys.
5. Frontend wiring checklist: [`UI_COLLAB.md`](./UI_COLLAB.md).

# UI handshake — live ticks (backend locked)

**Date:** 2026-08-25  
**Desk:** `Options-Edge-Desk` `/ws/desk`  
**UI:** `my-options-trader`  
**Status:** Backend is the source of truth. Do not add REST poll cadence to “make it feel live.” Apply WS frames.

Companion: [`DESK_SNAPSHOT_WS.md`](./DESK_SNAPSHOT_WS.md).

---

## What the desk now does (locked)

| Event | Cadence | Bumps `seq` | Purpose |
|-------|---------|-------------|---------|
| `connected` | Once per socket | no | `channels` + current `seq` |
| `mark.batch` | ~250 ms mock; ~250 ms paper/live when Dhan feed ticks | **no** | Spots, position LTP/MTM, book equity, today_net |
| `health.tick` | ~1 s mock / ~5 s paper | **no** | Process/session/token/kill/cash/books snapshot |
| `signal.trigger` | **Immediate** on fill_notice (and next-in-queue after ack). Backup on health if a new trigger appears | **no** | Auto fill cards + manual approval |
| `signal.clear` | **Immediate** on ack when the queue is empty | **no** | Dismiss interrupt |
| `position.*` / `order.*` / `trade.append` | On place/fill/cancel/EOD only | **yes** | Book mutations |

`mark.batch` and `health.tick` **never** bump `seq`. Do not treat them as snapshot gaps.

One desk ticker fans out to all clients. Connecting does **not** run extra Dhan REST per tab.

---

## `mark.batch` payload (apply this every frame)

```json
{
  "type": "mark.batch",
  "server_time": "2026-08-25T06:00:00Z",
  "seq": 1842,
  "data": {
    "nifty_spot": 24812.4,
    "nifty_change_pct": 0.42,
    "banknifty_spot": 51204.15,
    "banknifty_change_pct": -0.18,
    "unrealized_pnl": 3572.0,
    "realized_pnl_today": 34012.4,
    "today_net": 37584.4,
    "open_positions": 2,
    "marks": [
      { "key": "44118", "ltp": 91.2, "unrealized_pnl": -1700.0 }
    ],
    "books": [
      {
        "underlying": "NIFTY",
        "label": "Rs 1L book",
        "capital": 100000,
        "equity": 104812,
        "open_mtm": 4812,
        "open_lots": 10,
        "halted": false,
        "gates": []
      }
    ]
  }
}
```

| Field | UI must |
|-------|---------|
| `nifty_spot` / `banknifty_spot` / `%` | Patch Home tape **this frame**. Null = keep previous. |
| `marks[]` | Patch **position rows** by `key` (`security_id` if present, else `UNDERLYING\|strike\|CE\|PE\|expiry`). Update `ltp` + `unrealized_pnl`. |
| `unrealized_pnl` / `today_net` / `realized_pnl_today` | Patch status KPIs **this frame**. Same numbers as the marked rows. |
| `books[]` | Patch book cards (equity / `open_mtm` already include this tick’s MTM). |
| `open_positions` | Count only. Do not add/remove rows from this field — wait for `position.*`. |

Identical batches are suppressed on the desk. A frame means something changed.

---

## `signal.trigger` / `signal.clear` (auto cards)

Desk emits `signal.trigger` **at fill time** (not on the next 5 s health tick).

`data` is the trigger object (`trigger_id`, `role`, `kind`, `side`, `filled_qty`, `filled_price`, …).

| `role` | UI |
|--------|-----|
| `fill_notice` | Info card only. `placeable` is false. **Do not** open a ticket. Ack `dismiss` to receive the next queued fill (`signal.trigger` follows ack immediately if another fill is waiting). |
| `approval` | Manual sheet → ticket. |

`signal.clear.data.trigger_id` means the interrupt is gone.

Do **not** `GET /snapshot` just because a fill card appeared. `position.upsert` / `trade.append` already follow the fill. Snapshot only on seq **gap**, reconnect, or mutation REST success.

---

## What the UI must stop doing

1. Full snapshot every 1 s (mock) / 5 s (paper) while the wire is up — that was a workaround for missing `mark.batch`.
2. Splitting KPI MTM (`status.unrealized_pnl`) from table MTM (`positions[].unrealized_pnl`). After `mark.batch`, they are the same tick.
3. Double snapshot on fill notice (immediate + 800 ms).
4. Treating `health.tick` / `mark.batch` `seq` as a gap (`next > prev + 1` is only meaningful across **book** events).

---

## Required UI reconcile cadence (after this desk)

| State | Snapshot |
|-------|----------|
| EventSource up + `mark.batch` flowing | **30–60 s** safety net only |
| Wire down + trading | ~3 s |
| Idle / stopped | 15–20 s |
| Boot, reconnect (`false` → `true`), Sync, place/cancel/start/stop success | Once |

Ticket `GET /quotes/option` may still poll at 1 s while the ticket is open (no option-LTP channel).

---

## Apply order (one EventSource message)

1. Parse frame.
2. Book events (`position.*` / `order.*` / `trade.append`): merge lists; remember `seq`.
3. `mark.batch`: `patchStatusFromRaw(status, data)` **and** `applyMarkToPositions(positions, data.marks)` in the **same** turn.
4. `health.tick`: patch status (do not wipe books if omitted — existing rule). `data.trigger` is backup only; prefer `signal.trigger`.
5. `signal.trigger` / `signal.clear`: overlay cards.
6. Seq gap (`next < prev` or `next > prev + 1`) **and** the frame is a book mutation: soft snapshot. Ignore gaps on mark/health/signal.

---

## Acceptance (desk is done when)

1. Mock auto, open position: Home NIFTY tape, book equity, KPI Open MTM, and the position LTP/MTM column move together within **250 ms** of the sim tick — **without** a snapshot GET.
2. Mock/paper auto fill: fill card appears within **300 ms**; book row appears via `position.upsert`, not via a snapshot storm.
3. Paper: NIFTY/BANKNIFTY spots move from Dhan feed (`mark.batch`), not from 5 s REST.
4. Two browser tabs: still **one** Dhan status fetch per health interval (not per tab).
5. `/ws/desk` `connected.channels` still lists `mark.batch`. Frames actually arrive.

---

## Out of scope (still REST)

Place / cancel / start / stop. Option chain LTP on the ticket. Lab packs.

`account.patch` remains reserved. Live account numbers ride on `mark.batch` (`today_net`, `unrealized_pnl`, `books`).

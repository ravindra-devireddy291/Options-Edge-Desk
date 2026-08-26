# Desk snapshot + WebSocket event model

**Status:** FastAPI ships `GET /api/v1/desk/snapshot`, mutation WS deltas, **and** conflated `mark.batch`. `account.patch` is reserved (live PnL/spots/books ride on `mark.batch`).

**UI handshake (locked):** [`UI_HANDSHAKE_LIVE_TICK.md`](./UI_HANDSHAKE_LIVE_TICK.md)  
**UI companion:** keep [`my-options-trader/docs/DESK_SNAPSHOT_WS.md`](../../my-options-trader/docs/DESK_SNAPSHOT_WS.md) in sync for BFF/`DESK_SNAPSHOT_UPSTREAM=1`.

---

## Runtime

1. Boot / reconnect / Sync → `GET /api/v1/desk/snapshot` (one envelope: status + positions + orders + trades + signals + triggers + `seq`).
2. Runtime → `WS /ws/desk`:
   - `mark.batch` ~250 ms (mock ledger / Dhan feed) — spots + position marks + book MTM
   - `health.tick` ~1 s mock / ~5 s paper — process + session + cash
   - `signal.trigger` / `signal.clear` immediate on fill/ack
   - `position.*` / `order.*` / `trade.append` on place/fill/cancel
3. Soft reconcile snapshot on a **slow** timer (30–60 s) while the live wire is up.

Place / cancel / start / stop stay REST.

One ticker fans out to all sockets. Connecting does not extra-poll Dhan per client.

---

## Snapshot shape

Same as UI contract §1b. `seq` is monotonic on the desk process (`RUNNER.seq`); **book** WS frames bump it. `mark.batch` / `health.tick` / `signal.*` do **not** bump `seq`.

---

## WS deltas (emitted today)

| Event | Source | Bump seq |
|-------|--------|----------|
| `health.tick` | Central ticker | no |
| `mark.batch` | Mock keeper 250 ms; paper/live Dhan feed conflated 250 ms | no |
| `signal.trigger` / `signal.clear` | Fill notice / ack (immediate); health backup | no |
| `position.upsert` / `position.remove` | Mock ledger buy/sell; paper place row match; EOD | yes |
| `order.upsert` / `order.remove` | Paper TRANSIT place; cancel; mock instant fills remove | yes |
| `trade.append` | Mock open/close rounds | yes |

Position key: `security_id` if present, else `UNDERLYING|strike|CE|PE|expiry`. Same key on `mark.batch.data.marks[].key`.

### `mark.batch.data`

`nifty_spot`, `banknifty_spot`, `%`, `unrealized_pnl`, `realized_pnl_today`, `today_net`, `open_positions`, `marks[]` (`key`, `ltp`, `unrealized_pnl`), `books[]` (equity / `open_mtm` already include this tick).

---

## Not yet

- `account.patch` as a separate frame (fields already on `mark.batch`)
- Option LTP stream for the ticket (still `GET /quotes/option` while open)

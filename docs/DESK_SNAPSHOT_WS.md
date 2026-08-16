# Desk snapshot + WebSocket event model

**Status:** FastAPI ships native `GET /api/v1/desk/snapshot` and mutation WS deltas (`position.*` / `order.*` / `trade.append`). `mark.batch` / `account.patch` are advertised on `connected.channels` but not emitted yet.

**UI companion:** keep [`my-options-trader/docs/DESK_SNAPSHOT_WS.md`](../../my-options-trader/docs/DESK_SNAPSHOT_WS.md) in sync for BFF/`DESK_SNAPSHOT_UPSTREAM=1`.

---

## Runtime

1. Boot / reconnect / Sync → `GET /api/v1/desk/snapshot` (one envelope: status + positions + orders + trades + signals + triggers + `seq`).
2. Runtime → `WS /ws/desk` `health.tick` (~1 s mock / ~5 s paper) + push deltas on place/fill/cancel/EOD.
3. Soft reconcile snapshot on a slow timer while the live wire is up.

Place / cancel / start / stop stay REST.

---

## Snapshot shape

Same as UI contract §1b. `seq` is monotonic on the desk process (`RUNNER.seq`); book WS frames bump it.

---

## WS deltas (emitted today)

| Event | Source |
|-------|--------|
| `health.tick` | WS loop |
| `signal.trigger` / `signal.clear` | WS loop vs trigger store |
| `position.upsert` / `position.remove` | Mock ledger buy/sell; paper place row match; EOD |
| `order.upsert` / `order.remove` | Paper TRANSIT place; cancel; mock instant fills remove |
| `trade.append` | Mock open/close rounds |

Position key: `security_id` if present, else `UNDERLYING|strike|CE|PE|expiry`.

---

## Not yet

- Conflated `mark.batch` / `account.patch`
- Continuous paper MTM stream (Dhan remains source of truth between reconciles)

# Execution Armor (Desk OMS)

Shared **NIFTY + BANKNIFTY** live execution layer. Strategy stays in each Edge Lab; Desk owns broker I/O.

## Module map

| Path | Role |
|------|------|
| `app/execution/armor.py` | Spread gate + limit entry/exit placement |
| `app/execution/chase.py` | Modify working limits until fill or timeout |
| `app/execution/reconcile.py` | REST poll fallback if order WS misses events |
| `app/execution/sessions.py` | Partial-fill registry; exchange SL + TP; OCO |
| `app/execution/dhan_ws_feed.py` | Dhan FULL packet WS + depth cache |
| `app/execution/dhan_ws_orders.py` | Dhan order-update WS |
| `app/execution/runner.py` | Lifespan keeper (WS + chase + reconcile) |
| `app/oms.py` | `place_armed_entry` BUY / `place_armed_exit` SELL |

## Env flags

| Variable | Default | Meaning |
|----------|---------|---------|
| `DESK_EXECUTION_ARMOR` | `1` | Enable spread gate + limit chase + protective legs |
| `DESK_MAX_SPREAD_PCT` | `0.03` | Refuse if (ask-bid)/mid exceeds |
| `DESK_MAX_TICK_AGE_MS` | `500` | WS tick staleness abort |
| `DESK_MAX_TICK_AGE_MS_REST` | `5000` | REST quote staleness abort |
| `DESK_CHASE_TIMEOUT_S` | `90` | Cancel unfilled remainder after this |
| `DESK_CHASE_INTERVAL_MS` | `800` | Limit modify cadence |
| `DESK_CHASE_MAX_SLIPPAGE_PCT` | `0.015` | Max chase away from anchor mid |
| `DESK_USE_LIMIT_ENTRY` | `1` | LIMIT entry (else MARKET) |
| `DESK_USE_LIMIT_EXIT` | `1` | LIMIT exit (else MARKET) |
| `DESK_ATTACH_EXCHANGE_SL` | `1` | `STOP_LOSS_MARKET` on fill qty |
| `DESK_ATTACH_EXCHANGE_TP` | `1` | LIMIT TP on fill qty; OCO vs SL |
| `DESK_RECONCILE_INTERVAL_S` | `15` | REST order poll cadence |
| `DESK_MOCK_SPREAD_GATE` | `1` | Apply spread gate in mock replay |

## Flow

1. Lab shadow journal → Desk compass signal (unchanged)
2. `place_paper` BUY → `place_armed_entry` (limit @ bid+offset, spread check)
3. Chase loop modifies limit toward market until fill or `DESK_CHASE_TIMEOUT_S`
4. Order-update WS (or REST reconcile) → `sessions.handle_order_update`
5. Partial fill → resize SL + TP to **filled qty only**
6. Full fill → exchange SL + TP; first leg to trade cancels the other (OCO)
7. SELL flatten → `place_armed_exit` (limit @ ask-offset, same chase)
8. Mock mode → optional spread gate via `DESK_MOCK_SPREAD_GATE`

See also: Nifty Lab `docs/EXECUTION_BOUNDARY.md`.

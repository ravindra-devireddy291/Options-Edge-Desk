# Paper 360 — freeze matrix (Desk)

UI freeze was Playwright (happy / chaos / negative / harvest). This is the **Desk paper** equivalent. **Live is not a client path.** Paper runs until Gate 5 (20 Alpha `desk_paper` fill sessions) **and** fill forensics **and** a written pick of the final Nifty / BN model.

Robot: `py -3 scripts/run_qa.py`  
Harvest: `reports/qa/harvest/paper_360_matrix.json`

## Rule

`DESK_LIVE_ENABLED=0`. Place always uses paper OMS (`oms=paper`). Dhan money is unreachable until G5 + sign-off. Alpha vs Stable is still dual-track; **do not** pick a final model before forensics.

## A. Happy

| ID | Case | Robot |
| --- | --- | --- |
| P1 | Buy fills @ LTP, `oms=paper`, position open | `test_happy_buy_fills_paper_oms` |
| P2 | Sell closes round, position 0 | `test_happy_sell_closes_round` |
| P3 | `dry_run` previews, no fill | `test_dry_run_does_not_fill` |
| P4 | Same `trace_id` does not double-fill | `test_idempotent_trace_does_not_double_fill` |
| P5 | Nifty Alpha: fade allow, ORB lots 0 | `test_nifty_fade_allows_orb_denied` |
| P6 | BN Alpha: fade 6 + ORB 3 when healthy | `test_bn_alpha_allows_fade_and_orb` |
| P6b | BN fade fill stores trail 20@20 / TP 40; sell closes | `test_bn_fade_buy_stores_trail` / `test_bn_sell_closes` |
| P6c | All four packs take paper fills (Alpha + Stable × Nifty/BN) | `test_four_packs_take_paper_fills` / `test_alpha_and_stable_both_fill_same_sid` |
| P7 | Home four books Alpha/Stable | existing `test_home_books_are_four` |
| P8 | Readonly envelopes 200 | existing `test_readonly_routes_envelope` |
| P9 | Every `/api/v1` route probed; never 500; Dhan HTTP forbidden | `tests/qa/test_qa_route_matrix.py` |

## B. Edge

| ID | Case | Robot |
| --- | --- | --- |
| E1 | G5 = 20 + live book flags, **live still off** → paper | `test_g5_full_still_paper_when_desk_live_off` |
| E2 | Live flags on, G5 = 0 → paper | `test_live_flags_without_g5_stay_paper` |
| E3 | G5 = 19 + flags → paper | `test_g5_minus_one_not_enough` |
| E4 | Requested lots > gate max | `test_lots_exceed_gate` |
| E5 | Auto tick is noop in `execution=manual` | `test_manual_tick_is_noop` |
| E6 | Trail never below 30% floor / freak tick | existing chaos trail tests + `test_freak_tick_keeps_peak_then_trails` |
| E7 | Ledger reload / corrupt JSON | existing crash tests |
| E8 | Fill idempotent in lab brakes | Nifty/BN lab QA |
| E9 | Paper stop / TP / BN trail on LTP | `tests/qa/test_qa_no_leaks.py` YAML exits |
| E10 | EOD flatten + archive use paper ledger | `test_eod_flatten_uses_paper_ledger` / archive capture |
| E11 | Cancel `paper_*` is filled; live `desk-*` still Dhan | `test_cancel_paper_oid_is_already_filled` / `test_cancel_desk_prefix_without_fill_hits_dhan` |
| E12 | Feed subscribes paper sids after restart | `test_feed_instruments_include_paper_ledger` |
| E13 | Auto PENDING once; schedule paper not live; HTTP start/stop/kill/WS | `TestAutoAndSchedule` / `TestHttpMutations` |

## C. Negative

| ID | Case | Robot |
| --- | --- | --- |
| N1 | Place without API key → 401 | `test_place_401_without_key` |
| N2 | Place while STOPPED → `TRADING_STOPPED` (HTTP 200 envelope) | `test_place_stopped_rejects_inside_ok_envelope` |
| N3 | Kill switch | `test_kill_switch` |
| N4 | Session closed | `test_market_closed` |
| N5 | `mode=live` + `DESK_LIVE_ENABLED=0` → `LIVE_DISABLED` | `test_live_mode_disabled` |
| N6 | Book halted | `test_shadow_halted` |
| N7 | Sleeve blocked (`GATE_DENY`) | `test_gate_deny` |
| N8 | Null LTP → `BROKER_UNREACHABLE` | `test_stale_quote_blocks_send` |
| N9 | LTP vs ticket → `PRICE_MOVED` | `test_price_moved` |
| N10 | Sell with no position | `test_sell_without_position` |
| N11 | `virtual_paper` does not count to G5 | `test_virtual_paper_does_not_count` |
| N12 | Live auto tick noop when live off | `test_live_auto_noop_when_live_off` |
| N13 | Broker timeout classifies unreachable | `test_timeout_classifies_unreachable` |
| N14 | Status `uses_dhan=false`, G5 < 20 | `test_status_cutover_is_paper` |

## D. Not in robot (session-day / Monday)

These need an IST cash session. Walk them the first paper week; they do not unblock freeze of **code**. Tick the row in `DEBUG_LOG.md` the same day (pass / fail / evidence).

| ID | Case | How we track | Evidence |
| --- | --- | --- | --- |
| M1 | Auto places PENDING for **each** pack that fires (Nifty Alpha+Stable fade; BN Alpha fade+ORB, BN Stable fade) | Home compass → paper fill; four cards | `desk_paper` fill + open lot on that pack |
| M2 | Panic double-click still one fill (`trace_id`) | Repeat place same card | One position, not two |
| M3 | Trail 20@20 on BN open fade; Nifty stop stays 30% | Watch LTP vs recipe on open lots | Exit reason `trail_stop` / `stop` / `take_profit` |
| M4 | Lab journal `source=desk_paper` matches blotter | Trades vs shadow jsonl per pack | Same qty / LTP / pack_id |
| M5 | After close: G5 +1 **per pack that filled** (not lab tape) | `/research/g5` + cutover | `g5_fills` up only on packs with a desk_paper session |
| M6 | UI 504 / GATE_DENY / kill | Already in UI QA | — |

## After G5 (not now)

1. Deep forensic of the 20 Alpha fill sessions per underlying.
2. Decide final Nifty model (Alpha vs Stable) and final BN model.
3. Written sign-off, then `DESK_LIVE_ENABLED` — **not before**.

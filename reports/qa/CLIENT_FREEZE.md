# Client freeze — Desk + labs (handoff)

Research closed for **Nifty buy-side** on Groww lake (2026-09-21 standards discovery, 102 cells).  
Sell-side is deferred (separate blackbox). BN books unchanged. Live 10% stays hard-blocked until Gate 5 (20 **Alpha** fills) + written sign-off.

## What is frozen

| Book | Lab YAML | Role | Source |
| --- | --- | --- | --- |
| Nifty Alpha | `config/rungs/nifty_alpha.yaml` | Gate 5 paper · Groww PRIMARY `E_g80_tp60_st25_h2` | replaces Dhan Alpha |
| Nifty Stable | `config/rungs/nifty_stable.yaml` | Dual-track · Groww STABLE `E_g80_tp60_st25_h0` | replaces Dhan CE400 |
| BN Alpha | `config/rungs/bn_alpha.yaml` | Gate 5 paper | unchanged |
| BN Stable | `config/rungs/bn_stable.yaml` | Dual-track | unchanged |

UI pack_ids stay: `nifty_tier2_recommended`, `nifty_ce400_secondary`, `bn_f6o3_sm400_mce2`, `bn_rs30_tp40_secondary`.

### Nifty model (Groww)

- Fade: gap80 · smart200/0.25 · CE300 · **stop 25% / TP 60%** · chop_only
- Alpha: `month_ce_stop_halt_n: 2` · Stable: `0`
- Sizing: `risk_budget` · risk ₹40k · premium 30% · DD halt 15% · daily DD governor
- Lake: **`data_lake_groww`** (set `DATA_LAKE_ROOT=.../data_lake_groww` for lab replay)
- ~5y @ ₹2L: Alpha **+355.6%** (DD 11.1%, 206 trades) · Stable **+356.0%** (DD 11.9%, 230 trades)
- Prior Dhan YAMLs archived under `config/rungs/archive/*_dhan_20260901.yaml`

VPS / desk env must be:

```
NIFTY_CONFIG=config/rungs/nifty_alpha.yaml
BN_CONFIG=config/rungs/bn_alpha.yaml
DESK_MODE=paper
DESK_PAPER_AUTO=1
DESK_LIVE_ENABLED=0
```

Lab replay / tape export:

```
DATA_LAKE_ROOT=/root/Options-Nifty-Edge-Lab/data_lake_groww
```

## Robots (green before client)

| Stack | Command | Last local |
| --- | --- | --- |
| Desk | `py -3 scripts/run_qa.py` | paper 360 + freeze board |
| Nifty lab | `py -3 scripts/replay_locked_5y.py --all` (Groww lake) | snapshot match |
| BN lab | `py -3 scripts/run_qa.py` | trail passthrough + live lock |
| UI | `node scripts/run-qa.mjs` in my-options-trader | do not redo unless UI changed |

Verdict: `reports/nifty_enrich/GROWW_STANDARDS_VERDICT.md`.  
Paper 360: `reports/qa/PAPER_360.md`.  
Non-live scope: `reports/qa/SCOPE_NON_LIVE.md`.

## Monday (first paper week)

1. Confirm public healthz + UI sign-in.
2. Home shows **Alpha / Stable** on all four books.
3. Armed YAMLs are Alpha; live flags off; paper auto on.
4. Walk N1–N14 / B1–B14 and paper 360 M1–M6 on a session day.
5. After close: lab journal vs desk blotter (`source=desk_paper`).
6. Do **not** enable live.

## After G5 (not now)

1. Deep forensic of the 20 Alpha fill sessions per underlying.
2. Decide final Nifty model (Alpha vs Stable) and final BN model.
3. Written sign-off, then `DESK_LIVE_ENABLED` — **not before**.

## Leftover YAMLs (kept on purpose)

Live freeze + size ladder + UI aliases. Not client-facing. Do not delete live-lock files.  
Dhan-era Nifty Alpha/Stable kept only in `config/rungs/archive/`.

# Client freeze — Desk + labs (handoff)

Research is closed. Client books are the four locked YAMLs. Live 10% stays hard-blocked until Gate 5 (20 **Alpha** fills) + written sign-off.

## What is frozen

| Book | Lab YAML | Role |
| --- | --- | --- |
| Nifty Alpha | `config/rungs/nifty_alpha.yaml` | Gate 5 paper |
| Nifty Stable | `config/rungs/nifty_stable.yaml` | Dual-track |
| BN Alpha | `config/rungs/bn_alpha.yaml` | Gate 5 paper |
| BN Stable | `config/rungs/bn_stable.yaml` | Dual-track |

UI pack_ids stay: `nifty_tier2_recommended`, `nifty_ce400_secondary`, `bn_f6o3_sm400_mce2`, `bn_rs30_tp40_secondary`.

VPS / desk env must be:

```
NIFTY_CONFIG=config/rungs/nifty_alpha.yaml
BN_CONFIG=config/rungs/bn_alpha.yaml
DESK_MODE=paper
DESK_PAPER_AUTO=1
DESK_LIVE_ENABLED=0
```

## Robots (green before client)

| Stack | Command | Last local |
| --- | --- | --- |
| Desk | `py -3 scripts/run_qa.py` | paper 360 + freeze board |
| Nifty lab | `py -3 scripts/run_qa.py` | freeze board + live lock |
| BN lab | `py -3 scripts/run_qa.py` | trail passthrough + live lock |
| UI | `node scripts/run-qa.mjs` in my-options-trader | do not redo unless UI changed |

Paper 360 (happy / edge / negative, UI-depth): `reports/qa/PAPER_360.md`.  
Lab matrices: `Options-Nifty-Edge-Lab/reports/qa/FREEZE_TEST_PLAN.md` and `Options-Edge-Lab/reports/qa/FREEZE_TEST_PLAN.md`.

## Monday (first paper week)

1. Confirm public healthz + UI sign-in.
2. Home shows **Alpha / Stable** on all four books.
3. Armed YAMLs are Alpha; live flags off; paper auto on.
4. Walk N1–N14 / B1–B14 and paper 360 M1–M6 on a session day.
5. After close: lab journal vs desk blotter (`source=desk_paper`).
6. Do **not** enable live. 5-year compound was re-run 2026-09-06 (4/4 YAML match); do not treat that as a Monday fill walk.

## After G5 (not now)

1. Deep forensic of the 20 Alpha fill sessions per underlying.
2. Decide final Nifty model (Alpha vs Stable) and final BN model.
3. Written sign-off, then `DESK_LIVE_ENABLED` — **not before**.


## Leftover YAMLs (kept on purpose)

Live freeze + size ladder + UI aliases. Not client-facing. Do not delete live-lock files.

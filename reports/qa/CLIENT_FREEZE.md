# Client freeze — Desk + labs (handoff)

Research closed for **Nifty buy-side** on Groww (2026-09-21) and **BANKNIFTY buy-side** on Groww (2026-09-23).  
**2026-09-24:** Dhan open-fallback applied on `data_lake_groww` → open exclusions **Nifty 0.08% / BN 0.25%**; locked packs re-replayed (see `reports/exclusion_audit/NIFTY_BN_POST_FALLBACK_VERDICT.md`).  
Sell-side Groww Nifty = NO-EDGE (do not promote). Live 10% stays hard-blocked until Gate 5 (20 **Alpha** fills) + written sign-off.

## What is frozen

| Book | Lab YAML | Role | Source |
| --- | --- | --- | --- |
| Nifty Alpha | `config/rungs/nifty_alpha.yaml` | Gate 5 paper · Groww PRIMARY `E_g80_tp60_st25_h2` | replaces Dhan Alpha |
| Nifty Stable | `config/rungs/nifty_stable.yaml` | Dual-track · Groww STABLE `E_g80_tp60_st25_h0` | replaces Dhan CE400 |
| BN Alpha | `config/rungs/bn_alpha.yaml` | Gate 5 paper · Groww PRIMARY `BN_E_g150_tp40_st25_h2` | replaces Dhan Alpha |
| BN Stable | `config/rungs/bn_stable.yaml` | **First paper sleeve** · Groww STABLE `BN_E_g150_tp50_st25_h2` | replaces Dhan Stable |

UI pack_ids stay: `nifty_tier2_recommended`, `nifty_ce400_secondary`, `bn_f6o3_sm400_mce2`, `bn_rs30_tp40_secondary` (alias → new YAMLs).

### Nifty model (Groww)

- Fade: gap80 · smart200/0.25 · CE300 · **stop 25% / TP 60%** · chop_only · **Friday off** (`trade_on_friday: false`)
- Alpha: `month_ce_stop_halt_n: 2` · Stable: `0`
- Sizing: `risk_budget` · risk ₹40k · premium 30% · DD halt 15% · daily DD governor
- Lake: **`data_lake_groww`** (+ Dhan 09:15–09:40 open fallback on G5 holes; residual exclude **0.08%**)
- Locked snapshot @ ₹2L (**Friday off 2026-09-27**): Alpha **+434.1%** (DD 15.0%, 184t) · Stable **+271.2%** (DD 14.8%, 194t)
- Prior post-fallback Friday-on print: Alpha +435.7% / Stable +417.2% (do not revive Friday-on for Nifty)

### BANKNIFTY model (Groww)

- Fade-only: gap150 · smart300/0.25 · CE300 · **stop 25%** · strike 100 · CE-halt 2
- Alpha TP **40%** · Stable TP **50%** (no trail)
- Sizing: `risk_budget` · risk ₹40k · premium 30% · DD halt 15% · daily DD governor
- Lake: **`data_lake_groww` BANKNIFTY** · window **2021-09-09→2026-06-30** (+ Dhan open fallback; residual exclude **0.25%**)
- ~4.8y @ ₹2L (**post-fallback 2026-09-24**): Alpha **+582.1%** (DD 17.1%, 247t) · Stable **+507.4%** (DD 17.1%, 242t)
- Prior pre-fallback: Alpha +550.6% / Stable +500.4% (~12% sessions excluded)
- Data: G5 residual flat days only where Dhan also lacks open bars; spot still Dhan-joined; options Groww master + disclosed open fallback
- Verdict: `reports/banknifty_enrich/GROWW_BN_STANDARDS_VERDICT.md` · post-fallback: `reports/exclusion_audit/NIFTY_BN_POST_FALLBACK_VERDICT.md`

VPS / desk env must be:

```
NIFTY_CONFIG=config/rungs/nifty_alpha.yaml
BN_CONFIG=config/rungs/bn_stable.yaml
DESK_MODE=paper
DESK_PAPER_AUTO=1
DESK_LIVE_ENABLED=0
```

Lab replay:

```
DATA_LAKE_ROOT=/root/Options-Nifty-Edge-Lab/data_lake_groww
# Nifty: Options-Nifty-Edge-Lab/scripts/replay_locked_5y.py --all
# BN:    Options-Edge-Desk/scripts/replay_bn_groww_locked.py --all
```

## Robots (green before client)

| Stack | Command | Expect |
| --- | --- | --- |
| Desk | `py -3 scripts/run_qa.py` | paper 360 + freeze board |
| Nifty lab | `replay_locked_5y.py --all` (Groww) | snapshot match |
| BN Groww | `replay_bn_groww_locked.py --all` | snapshot match |
| UI | `node scripts/run-qa.mjs` | only if UI changed |

## Monday (first paper week)

1. Confirm public healthz + UI sign-in.
2. Home shows Alpha / Stable on all four books.
3. Armed: Nifty Alpha + **BN Stable** (stronger holdout); live off; paper auto on.
4. Walk N1–N14 / B1–B14 and paper 360 on a session day.
5. After close: lab journal vs desk blotter (`source=desk_paper`).
6. Do **not** enable live. Disclose ATM-excluded days + Dhan spot join if client asks.

## After G5 (not now)

1. Deep forensic of 20 Alpha fill sessions per underlying.
2. Decide final Nifty / BN model (Alpha vs Stable).
3. Written sign-off, then `DESK_LIVE_ENABLED` — **not before**.

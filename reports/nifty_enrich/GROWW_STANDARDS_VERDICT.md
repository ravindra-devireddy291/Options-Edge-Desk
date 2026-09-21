# Groww Standards Verdict (buy-side blackbox)

Sell-side deferred. Capital Rs 200,000. Lake `data_lake_groww`. Sizing r40/p30/d15.
Merged candidates: **102** across geom/exit/orb/base.

## Proposed standards

- **PRIMARY:** `E_g80_tp60_st25_h2` (track=exit) — 206 trades (41.23/yr), CAGR 35.46%, DD 11.09%, Calmar 32.061, Sharpe 0.832; holdout 355.5% / DD 10.47%; oos2024 216.15%
  - fade: `{"min_gap_pts": 80.0, "regime_mode": "chop_only", "skip_ce_fade_min_gap_pts": 300.0, "smart_skip_gap_pts": 200.0, "smart_skip_near_extreme_frac": 0.25, "stop_pct": 0.25, "strike_step": 50, "take_profit_pct": 0.6}`
- **STABLE:** `E_g80_tp60_st25_h0` (track=exit) — 230 trades (46.03/yr), CAGR 35.48%, DD 11.94%, Calmar 29.819, Sharpe 0.769; holdout 356.42% / DD 11.76%; oos2024 216.15%
  - fade: `{"min_gap_pts": 80.0, "regime_mode": "chop_only", "skip_ce_fade_min_gap_pts": 300.0, "smart_skip_gap_pts": 200.0, "smart_skip_near_extreme_frac": 0.25, "stop_pct": 0.25, "strike_step": 50, "take_profit_pct": 0.6}`

## Top 25 by gates

| ID | track | trades | t/yr | CAGR% | DD% | Calmar | Hold% | HoldDD | OOS24% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `E_g80_tp60_st25_h2` | exit | 206 | 41.23 | 35.46 | 11.09 | 32.061 | 355.5 | 10.47 | 216.15 |
| `E_g80_tp60_st25_h0` | exit | 230 | 46.03 | 35.48 | 11.94 | 29.819 | 356.42 | 11.76 | 216.15 |
| `E_g125_tp50_st25_h2` | exit | 93 | 18.61 | 30.12 | 9.35 | 29.17 | 258.66 | 8.62 | 31.06 |
| `E_g125_tp50_st25_h0` | exit | 94 | 18.81 | 28.76 | 9.35 | 27.118 | 222.53 | 8.62 | 31.06 |
| `E_g80_tp60_st30_h2` | exit | 218 | 43.63 | 36.32 | 13.72 | 26.988 | 294.94 | 13.97 | 220.44 |
| `E_g80_tp60_st30_h0` | exit | 230 | 46.03 | 35.6 | 13.54 | 26.441 | 269.47 | 14.08 | 220.44 |
| `G_g60_s200` | geom | 302 | 60.44 | 35.97 | 13.98 | 26.053 | 271.75 | 6.65 | 224.36 |
| `E_g80_tp50_st25_h2` | exit | 206 | 41.23 | 36.32 | 14.48 | 25.575 | 208.9 | 12.32 | 203.23 |
| `G_g60_s150` | geom | 292 | 58.44 | 16.91 | 5.81 | 20.363 | 180.8 | 5.72 | 177.72 |
| `E_g100_tp50_st25_h2` | exit | 140 | 28.02 | 25.98 | 10.7 | 20.283 | 210.67 | 9.24 | 64.19 |
| `E_g125_tp60_st25_h2` | exit | 93 | 18.61 | 21.78 | 8.83 | 18.992 | 345.45 | 8.71 | 5.22 |
| `G_g80_s200` | geom | 218 | 43.63 | 27.86 | 14.56 | 16.587 | 163.1 | 14.69 | 189.34 |
| `E_g80_tp50_st30_h2` | exit | 218 | 43.63 | 27.86 | 14.56 | 16.587 | 163.1 | 14.69 | 189.34 |
| `B_alpha80` | base | 218 | 43.63 | 27.86 | 14.56 | 16.587 | 163.1 | 14.69 | 189.34 |
| `G_g125_s200` | geom | 94 | 18.81 | 25.17 | 12.92 | 16.022 | 212.68 | 12.77 | 65.9 |
| `E_g125_tp50_st30_h2` | exit | 94 | 18.81 | 25.17 | 12.92 | 16.022 | 212.68 | 12.77 | 65.9 |
| `E_g125_tp60_st25_h0` | exit | 94 | 18.81 | 19.19 | 8.83 | 15.903 | 320.18 | 8.71 | 5.22 |
| `E_g80_tp50_st30_h0` | exit | 230 | 46.03 | 26.1 | 14.56 | 15.012 | 141.37 | 13.73 | 189.34 |
| `E_g125_tp50_st30_h0` | exit | 94 | 18.81 | 23.81 | 12.92 | 14.763 | 196.42 | 12.77 | 65.9 |
| `E_g100_tp40_st25_h2` | exit | 140 | 28.02 | 20.91 | 10.91 | 14.5 | 165.31 | 10.65 | 63.77 |
| `E_g80_tp50_st25_h0` | exit | 226 | 45.23 | 32.5 | 21.64 | 14.231 | 200.34 | 12.87 | 203.23 |
| `E_g100_tp50_st25_h0` | exit | 153 | 30.62 | 24.23 | 13.98 | 13.994 | 188.49 | 13.35 | 64.19 |
| `E_g125_tp40_st25_h2` | exit | 93 | 18.61 | 18.03 | 9.59 | 13.441 | 207.23 | 8.58 | 48.55 |
| `E_g80_tp40_st25_h2` | exit | 206 | 41.23 | 24.18 | 14.87 | 13.117 | 152.8 | 12.29 | 180.22 |
| `E_g125_tp40_st25_h0` | exit | 94 | 18.81 | 17.18 | 9.59 | 12.597 | 190.97 | 8.58 | 48.55 |

## Decision rules

- PRIMARY needs denser fills than g150/g175 thin winners (target >=100 trades / ~20/yr).
- STABLE is the next viable denser or more conservative twin.
- If no PRIMARY clears >=100 trades with DD/holdout gates, do **not** promote thin Calmar heroes.

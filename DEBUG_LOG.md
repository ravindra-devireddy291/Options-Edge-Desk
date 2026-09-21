# DEBUG_LOG

Session scratchpad for multi-step debugging. Keep entries short.
Agent updates this file; start a new chat when history gets long and continue from here.

## Current issue

Paper Home equity = capital + PnL since DESK_PAPER_BOOK_START (2026-08-17). Trades history APIs documented.

**Sequels (not this repo):** futures PA + FinNifty/Midcap options. Workspace: `D:\Futures-PA-Lab`. New chat there: `Read DEBUG_LOG.md and continue`. Do not add sequel code, desk routes, or UI here.

## Log

<!-- Append: date | tried | error/result | next hypothesis -->
2026-08-25 | curl tunnel /healthz | error code 1033 | restart cloudflared on VPS
2026-08-25 | local desk + UI .env.local | uvicorn :8080 OK | restart Next dev to pick up .env.local
2026-08-25 | books_snapshot paper equity | NIFTY ₹1L / BN ₹1,96,405 (−3595, 2 closes since 17) | deploy desk to VPS when tunnel up
2026-08-25 | index % wrong + on capital card | prev-day close → NIFTY +115.5 (0.48%), BN −11.75 (−0.02%); cards = Book ±% since paper | refresh UI; deploy desk when VPS up
2026-08-26 | open trade shown as EOD closed + net moving | blotter used lab planned exit; stay open until broker_fill.exit | restart desk; refresh Trades
2026-08-26 | no PnL / empty Book while Trades showed open | lab-only card on blotter; Dhan positions=0; blotter=broker-only; fills=closed_count | restart desk; arm paper to place real fills
2026-08-26 | paper≠live confusion | paper≡live same contracts; mock is only fork; idle copy + desk- oid; docs Paper≡Live | arm paper for real Dhan fills; audit remaining name debt (place_paper)
2026-08-26 | implement internal paper OMS + G5 per-book live | place→desk_paper fill@LTP; Dhan only if LIVE_*+G5≥20; status.live_cutover | arm paper; clients see Book/Trades from paper ledger
2026-08-26 | promote lab ok → desk_paper | 3 fills (BN -970, BN -2625, NIFTY +16246); G5 1+2; Trades API shows today | refresh UI Calendar/Today
2026-08-26 | lab-only eod shown closed while session open | journal has no broker_fill; lab writes provisional eod+MTM | treat lab eod as open until market close; restart desk; refresh Trades
2026-08-26 | D1 widen sleeve_gates | pass-through dd/caps/budget; mock+contract+test | UI can show risk headroom; next D2 G5 endpoint
2026-08-26 | D2 GET /research/g5 | read G5_TRACKER.json soft-fail; sessions cap 40 | UI U5 allowlist; next D3 rejected signals
2026-08-26 | D3 rejected/last-cycle | normalize row shape; allowlist docs; fixture test | next D4 circuit-breaker
2026-08-26 | D4 circuit-breaker GET | books[] + fraction peak_dd; limits from config | next D5 audit tail
2026-08-26 | D5 audit/tail | redact secrets; durable prefer; contract 3 kinds | D-P1 done; next D6 OOS if wanted
2026-08-26 | D6–D8 research impress | oos/cost/scale/brief endpoints + tests + contract | Desk D1–D8 complete; UI next
2026-08-27 | close non-ticket gaps | restart desk; smoke D1–D8 OK; UI allowlist+Zod+docs | plumbing 100%; UI screens U7–U15 remain
2026-08-27 | sync git local→origin | desk+UI feat+master pushed 7934e34/afad1a3 | VPS SSH:22 unreachable from admin; retry deploy when host up
2026-08-27 | VPS SSH not 22 | EDGE_VPS_PORT=443; deploy no-chroot to /root | connected; files synced; edge-desk restarted; verify D routes
2026-08-27 | UI desk unreachable | local :8080 down; VPS edge-desk active; cloudflared missing | started local uvicorn; tunnel needs CLOUDFLARE_TUNNEL_TOKEN install
2026-08-27 | tunnel restore | installed cloudflared; quick tunnel OK; deskapi 1033 | add CLOUDFLARE_TUNNEL_TOKEN → restore_named_tunnel_vps.py
2026-08-27 | named tunnel restore | token OK; wrote /etc/cloudflared/token; Type=simple unit | deskapi healthz 200; options-desk-api Healthy
2026-08-27 | HA harden | edge-desk+cloudflared StartLimit=0; desk-watchdog every 2m | local+public healthz 200; timer enabled
2026-08-28 | Peak DD 53% after sync | merge overwrote June month + investor DD | YAML locked DD on KPI; merge keeps existing months; table sort chips
2026-08-28 | lake not EOD | keeper only during cash+paper | EOD ingest after 15:35 + download API; TOTP not never-expire JWT
2026-08-28 | sync reload old trades | tape saved; UI To stuck at 2026-06-30 | follow tape_last_day when To is at locked end
2026-08-28 | sync button still on | last trade ≠ last closed day | watermark synced_through; button Up to date
2026-09-02 | UI desk unreachable | probed public+local+VPS | VPS+tunnel+deskapi 200; localhost:3000 BFF → 127.0.0.1:8080 fetch failed (local uvicorn down; DESK_API_URL unset) | use desk.ravindra-devireddy.com or set DESK_API_URL to deskapi + restart Next
2026-09-02 | 24/7 CF-only | stripped BOM on my-options-trader/.env.local; DESK_API_URL already deskapi | Next was ignoring URL and defaulting :8080 | restart Next; daily use desk.ravindra-devireddy.com; VPS HA already on
2026-09-05 | client desk unreachable | deskapi 1033/530; Vercel UI 200; BFF hop fails | SSH 87.232.72.137:443 TimeoutError 10060 | VPS host/network down — cloudflared cannot register; watchdog cannot run until VM is up; start VPS from provider panel then restart_public_tunnel_vps.py
2026-09-05 | desk QA robot + Alpha/Stable lock | aligned PAPER_VARIANTS to nifty_alpha/stable + bn_alpha/stable; lab_sync runs all 4; trail YAML fallback; stale tape overlays YAML metrics (Nifty 53% DD, BN pre-trail) | 101 tests pass `py -3 scripts/run_qa.py` | Monday: set local+VPS `NIFTY_CONFIG=config/rungs/nifty_alpha.yaml` `BN_CONFIG=config/rungs/bn_alpha.yaml`; VPS still Suspended — unsuspend then deploy
2026-09-05 | VPS unsuspended | CloudOnFire 1189 Running, not suspended; deskapi healthz 200 STOPPED | BN `fade_params_from_config` dropped trail (shadow would ignore 20@20) — patched | deploy labs+desk, arm Alpha env, restart tunnel
2026-09-05 | paper 360 freeze | UI-depth happy/edge/negative robot; `place_paper` crashed on audit `trace_id` kwarg | 130 tests pass; live stays off at G5=20 | deploy oms.py to VPS before Monday paper
2026-09-05 | paper no-leak close | IndentError in `_sell_locked`; 600 tick was TP not freak; `desk-` cancel short-circuited live | YAML stop/TP/trail + EOD ledger + cancel + feed sids + HTTP robot green | deploy desk; live stays off
2026-09-05 | blackbox public harden | G5 counted any entry+exit; `/docs` open; `?api_key=` in HTTP logs; token prefix+client id | docs off, header-only, token view, lab G5=0, every /api/v1 401 | deploy; live stays off
2026-09-05 | UI-only desk lock | deskapi curlable with API key; CORS allowed browsers | X-Desk-BFF + empty CORS when secret set; UI BFF sends header | copy DESK_BFF_SECRET to Vercel then deploy UI
2026-09-06 | close endpoint test gaps | skipped Dhan/long-job routes left 500s unproven | route matrix + BN place_paper; 179 pass `py -3 scripts/run_qa.py` | Monday cash-session walk still ops, not robot
2026-09-06 | four packs paper fills | freeze had only Alpha OMS | desk_books=4 in paper; pack-scoped ledger; 181 pass | deploy desk before Monday
2026-09-06 | deploy four-pack desk | `deploy_desk_vps.py` | edge-desk active, healthz 200, desk_books=4 packs; runner STOPPED | arm paper Monday; live stays off
2026-09-06 | Monday seamless VPS | deploy + `_monday_seamless_vps.py` | paper-only env, kill off, 1 uvicorn :8080, token_ok ~24h + keeper 15m, scrip N/BN, 4 packs paper OMS, deskapi 200, labs import | Vercel Production `DESK_BFF_SECRET` must match `data/_vercel_desk_bff_secret.txt`; do not arm until Mon 09:10 IST; live stays off
2026-09-06 | Vercel BFF | operator: Production `DESK_BFF_SECRET` already set | public UI 307, `/api/desk/healthz` 401 Sign in required (session gate, not desk) | after login Home should hop; live stays off
2026-09-06 | load soak | inproc + `_load_desk_vps.py` | healthz 200/200 p95 75ms; status 24/24 (cache); public 40/40 p95 796ms; spots ok, weekend option LTP empty | 1s status cache + 5s fund/spots lock; live stays off
2026-09-06 | lab 360 robots | BN then Nifty `run_qa.py` | BN 26 pass; Nifty 22 pass; deterministic fills/costs/brakes; perf harvest | labs are pure functions on fixture; 5Y not rerun; Monday paper still desk
2026-09-06 | 5Y four-pack replay | tmux `four_pack_5y` VPS nproc=10 parallel BN+Nifty alpha/stable | ALL_MATCH True; 4/4 delta 0 vs YAML; wall 17.6 min; desk stayed active | freeze holds; Monday paper still desk
2026-09-06 | freeze lock git+VPS+Vercel | desk `b507d4a` master+feat; BN `a152a81`; Nifty `95c4db3`; UI origin `0b94670` already Vercel prod 10:24 IST | VPS 4 packs healthz 200 paper-only live=0; BN stamp 09:15Z; Nifty SMOKE_OK 60/60 | Monday M1–M5 still ops; do not enable live
2026-09-06 | public prod gate | curl desk + deskapi | UI `/` 307 Sign in; `/api/desk/healthz` 401; deskapi GET healthz ok runner STOPPED | signed-in Home walk still operator before client “verify all”; live stays off
2026-09-06 | four-repo leftover check | git status all | lock remotes current; local only DEBUG_LOG / research tmp / UI `.vercelignore` | do not CLI `vercel deploy`; git push master ships UI
2026-09-06 | sequels A+B isolated | new lab `D:\Futures-PA-Lab` (B active, A parked in docs) | desk/Nifty/BN/UI untouched for sequels | continue B only in that folder; live stays off here
2026-09-07 | Monday cash-session walk | public healthz RUNNING paper auto; 4 books; live=0; token_ok | signals only Stable SKIPPED skip_small_gap/orb lots_zero; Alpha journal clobber | pack-scoped shadow jsonl + restart; re-probe compass
2026-09-07 | pack-scoped journals on VPS | 8 compass cards all 4 packs; all SKIPPED (gap/lots); trades 0; G5 fill 0/20 | M1 wait for fireable lab; M2–M5 after a desk_paper fill; live stays off
2026-09-07 | leftovers robots + 4-repo QA | session_day on status; pack journal fallback/period keys; token renew branches; SCOPE_NON_LIVE.md | Desk 190 OK; Nifty 22; BN 26; UI units 130 | residual = M1–M5 + signed-in Home + prod EOD/overnight only; live stays off
2026-09-07 | deploy leftovers VPS | main+adapters+lab_sync | session_day present; paper RUNNING | wait fireable fade for M1
2026-09-08 | Groww paid historical API probe | auth + expiries/contracts/candles for Nifty/BN/FinNifty/MidcpNifty | fixed-contract 1m OHLCV+OI works back to 2020; spot+futures present; FinNifty 2021 sparse; OI/vendor differences need audit | build validated raw importer before rerunning results
2026-09-08 | Groww full archive paused at daily auth rollover | 35,624 jobs saved; 76 auth failures after 06:00 IST; stopped retry storm | renew approval token/secret, then resume idempotently
2026-09-09 | Groww NIFTY archive complete | 190,537 candle jobs / 67,775 contracts; sample hash OK | BANKNIFTY download started
2026-09-10 | PLAN_GROWW_NIFTY_ENRICH revised | G0 NSE reference lock; lot keyed by (underlying,expiry); ContractBar stays lot-free; window 2021-06-01+ | next = G1 inventory only
2026-09-10 | G1 inventory lock done | Groww 190537/190537; spot 64 months 2021-05→2026-08; window 2021-06-01→2026-06-30; May-2021 excluded | next = G0 NSE reference lock
2026-09-10 | Power-off recovery | BN stopped at 116805/185601 jobs; G0 refs intact; G2/G3 never started | BN harvest resumed; next enrich = G2 after G0 sign-off
2026-09-10 | G2+G3 done | 267/267 expiry lots mapped; spot extract 471210 rows / 1260 sessions; sha a9d0faf3… | next = G4 Groww→ContractBar ingest
2026-09-10 | G4 pilot OK + full started | May2024 pilot 2.73M bars; full dataset nifty_groww_enriched_20260910 writing gzip shards | BN still downloading (~122k jobs)
2026-09-10 | Groww BANKNIFTY archive complete | 185601 candle jobs, 0 failures | G4 Nifty ingest still running
2026-09-10 | BankNifty G0-G3 prep done | inventory 185601; lot map passed; spot extract + calendar/specs created | wait Nifty G4 then BN G4
2026-09-10 | Nifty G4 ingest complete | 61/61 shards; 118.3M bars; 56226 symbols; missing_spot 157035 (~0.13%); sha eb355885… | next G5 QA then BN G4
2026-09-10 | missing_spot OK | locked policy skip_bar; ~0.13% | started G5 streaming qa_groww_nifty.py
2026-09-10 | G5 FAILED | tape OK (118.3M, 0 validate/dup/spot-mismatch, lots complete) but ATM±2@09:30+09:50 failed 343 days; Groww sparse at 09:50; a few calendar-only missing sessions | relax signal gate or treat 09:50 as soft
2026-09-10 | G5 gate fixed | hard=ATM±2@09:30; soft=09:50; calendar-only sessions warn | re-running qa_groww_nifty.py
2026-09-10 | BankNifty G4 started | ingest_groww_nifty.py --underlying BANKNIFTY dataset banknifty_groww_enriched_20260910 | parallel with Nifty G5 re-run; ~50GB free
2026-09-10 | BN G4 aborted high missing_spot | Dhan BN spot missing 2021-06/07; Aug starts 10:00 (~331m/day) until ~2021-09-09 | restart window_start=2021-09-09
2026-09-10 | BN missing_spot plateau ~111k | early Sep-2021 Dhan holes (e.g. 2021-09-20 absent) + short days; miss stopped rising while kept grows → final %% will drop toward ~0.1–0.2% | optional tighten window to 2021-10-01
2026-09-10 | G5 re-run FAILED again | 130 ATM@09:30 fails; tape still green | ROOT: nifty spot extract contaminated — e.g. 2022-02-15 09:30 spot=36973 (BN-level) vs day median ~17075; ~237 days have outlier minutes | need clean spot + re-G4
2026-09-10 | Nifty spot cleaned | dropped 16927/471210 (3.59%) outlier mins; dirty backup kept; 2022-02-15 09:30 removed | G4 restart dataset nifty_groww_enriched_20260911
2026-09-10 | BN G4 stopped+spot cleaned | deleted dirty dataset; dropped 14008/444458 (3.15%); residual 0; window 2021-09-09 | G4 restart banknifty_groww_enriched_20260911
2026-09-10 | G0 NSE reference lock | calendar 1260 sessions; lot_by_expiry 267 rows; contract_specs+circulars+nifty_data.yaml verified | next = G2 expiry lot join map / G3 spot extract
2026-09-09 | Groww Nifty enrich plan handed to desk | docs/PLAN_GROWW_NIFTY_ENRICH.md created (G1-G6); master=Groww options + Dhan spot/lot join; no Dhan options hive patch | desk/data agent starts at G1 inventory
2026-09-12 | G5 gate aligned to engine bar_at | engine `bar_at()` uses `>=` (snaps forward); Groww gate hard-required exact 09:30 — gate was stricter than its consumer | patched qa_groww_nifty.py + smoke_groww_nifty_g6.py to ENTRY_WINDOW 09:30..09:35; record resolved minute
2026-09-12 | Nifty G5 re-run PASSED | qa_status=passed, error_count=0, atm_fail_day_count=0; sessions=1254; excluded 122→112 (8.89%); resolved 09:30:1132 09:31:5 09:32:2 09:33:2 09:35:1 | manifest re-frozen manifests/nifty/nifty_groww_enriched_20260911.json sha c63cd278…; old 122-exclusion manifest archived
2026-09-12 | Nifty G6 smoke PASSED | g6_status=passed, error_count=0; 1127 resolved / 127 unresolved; 1127 trades, −3654.8 index pts (no lot sizing); resolved 09:30:1118 09:31:4 09:32:2 09:33:2 09:35:1 | reports/nifty_enrich/g6_smoke.json; 127 = 112 G5-excluded + 15 calendar-only/no-exit-tape
2026-09-12 | recovery diagnostic was an artifact | _diag_g5_recover_window.py searched only 09:31..09:35 (skipped 09:30) → false "101 recovered" | true engine parity recovery = 10 days; 102 days have 09:30 option bars but no pair on any expiry → engine pick_leg also skips
2026-09-12 | BankNifty G5+G6 deferred | QA script still lacks --underlying for BN; BN dataset banknifty_groww_enriched_20260911 not yet QA'd | separate task: add --underlying to qa_groww_nifty.py then run BN G5+G6
2026-09-12 | Groww->parquet lake adapter built | scripts/build_groww_lake.py streams per-shard (one month buffer, write, gc) to bound memory; maps ContractBar -> engine schema (timestamp_ns, tradingsymbol, instrument_type, lot_size from lot_join_map, bid/ask=0 -> close-based fill fallback) | first version OOM'd on full 5y; rewritten streaming
2026-09-12 | Groww lake build COMPLETE | 61 shards 2021-06..2026-06; 113,988,288 option bars + 453,242 spot bars; lot_miss=0 skipped=0; 2702.9s; schema+dtypes identical to Dhan lake | data_lake_groww; report reports/nifty_enrich/groww_lake_build_full.json
2026-09-12 | Groww standards backtest done | nifty_alpha 197.71% / DD 28.68% / Calmar 6.894 / 213 trades; nifty_stable 203.39% / DD 27.75% / Calmar 7.329 / 214 trades; holdout 34.61% / 40.29% | engine untouched; only lake root swapped
2026-09-12 | Groww vs Dhan month-by-month | nifty_alpha 54/60 (90.0%) same-sign; nifty_stable 53/60 (88.33%); Groww systematically lower (~-1.2L) due to denser tape + no quotes (close-based fills) + more halt months (7 vs 1) | reports/nifty_enrich/groww_vs_dhan_standards.{md,json}
2026-09-12 | Client submission doc written | reports/nifty_enrich/CLIENT_SUBMISSION_GROWW_VERIFICATION.md covers both YAML specs, methodology, engine parity, adapter field map, headline + month-by-month results, diagnosis, reproducibility | edge is data-source-robust
2026-09-13 | Groww lake + runners synced to VPS | data_lake_groww 1.7G / 122 parquet (61 spot + 61 opt); engine smoke reads 61+61; scripts/run_groww_blackbox_sweep.py + run_groww_trail_blackbox.py portable (EDGE_LAB_ROOT + sys.path) | launch full sweep with --jobs 8
2026-09-13 | Groww full variant sweep COMPLETE on VPS | 336 blackbox + 109 trail = 445 variants replayed vs Groww lake, 5 spans each, exit=0; blackbox 336/336, trail 109/109 | reports/nifty_enrich/groww_sweep/groww_{blackbox_sweep,trail_blackbox}.{json,md}
2026-09-13 | 360-degree ranking | 129/445 survivors (full>0 AND holdout>0); winner G_g150_sm200 geometry fade-only: full +190.88% / DD 27.97% / Calmar 6.824, holdout +158.12% / DD 7.57% / Calmar 20.888, positive in ALL 5 spans; runner-up G_g175_sm200 full +217.03% / Calmar 9.424 (2021H2 -0.27%); top raw return B_f14o4_sm200_mce2 +282.32% but DD 58% / worst mo -52.65% | scripts/rank_groww_variants_360.py; reports/nifty_enrich/groww_sweep/GROWW_360_VERDICT.md
2026-09-13 | Trail variants mostly fail on Groww tape | 109 trail (TR1-TR5) produced few survivors; best TR3_be10_t15 full +119.54% / DD 48.95% / Calmar 2.442 — trailing stops cut winners in chop-only regime | geometry gap-gating is the dominant edge
2026-09-13 | 4-model comparison + trade-day gap | existing nifty_alpha +197.71%/DD28.68/Cal6.894/holdout +34.61%/DD74.85/Cal0.462/213 trades/7 halts; nifty_stable +203.39%/DD27.75/Cal7.329/holdout +40.29%/DD68.83/Cal0.585/214 trades; winners G_g150_sm200 +190.88%/DD27.97/Cal6.824/holdout +158.12%/DD7.57/Cal20.888/0 halts, G_g175_sm200 +217.03%/DD23.03/Cal9.424/holdout +126.30%/DD9.10/Cal13.879 | winners differ from alpha ONLY by min_gap_pts 80->150/175; robustness win not return win
2026-09-13 | Groww vs Dhan trade-day gap | Dhan T2_Gate5 ok_fade=241 vs Groww nifty_alpha n_trades=213 => 28 fade days missed (11.6%); ZERO calendar days missing (both 1260 spot sessions, 0 missing vs calendar); Groww G5 excludes 112 sessions (8.89%) all no-pair (atm_fail_day_count=0); Groww 7 halt months vs Dhan 1 | gap = sparse Groww option tape + extra halts; explains -58.8pp return / -1.18L PnL
2026-09-13 | Recommendation | promote G_g150_sm200 primary (only model positive in all 5 spans), G_g175_sm200 aggressive sleeve; retire nifty_alpha/nifty_stable from primary slot | reports/nifty_enrich/groww_sweep/FOUR_MODEL_COMPARISON.md
2026-09-13 | six-doubt clarification (G_g150_sm200) | Q1 trade count: full=57, holdout=17, march_2026=0 (VPS re-run with include_day_trades=True) => +158.12% holdout from only 17 trades; Calmar 20.888 is a 17-sample anomaly | Q2 leverage: engine uses fixed_lots_fade verbatim (compound_book.py:585-587) and qty=lot_size*lots (gap_continuation.py:282) with lot_size read per-row from lake; lake lot_size is time-varying (2024-06=25, 2024-12=75, 2025-06=75) => 10 lots = 250 contracts in mid-2024 but 750 in 2025 = 3x notional, NOT constant rupee-risk | Q3 exclusions: 107/112 (95.5%) inside holdout_freeze (2025-H2=32, 2026-H1=67) => severe selection bias, holdout DD 7.57% artificially suppressed | Q4 march_2026: tape PRESENT (options 814773 rows, spot 7109) but winner took 0 trades (min_gap_pts=150 + chop_only filtered all) => no qualifying gap, not missing tape | Q5 benchmark: 'vs Tier2' subtracts Dhan 256.49% (rolling-ATM artifact); correct Groww-native ref is nifty_alpha +197.71% | Q6 trail crash: transient PYTHONPATH race at 04:59:05, restart 24s later on SAME lake data_lake_groww, trail completed 109/109 exit=0
2026-09-13 | reproducibility note | sweep reproducible ONLY when DATA_LAKE_ROOT=data_lake_groww; paths.py:10-14 falls back to REPO_ROOT/data_lake (Dhan) when unset => desk re-run without env var silently reads wrong lake (full 99.22% vs 190.88%)
2026-09-13 | Recommendation (revised) | DO NOT promote G_g150_sm200 to live paper as-is; first (1) re-run holdout with lot-size-normalised sizing to strip 3x leverage, (2) re-score with 112 excluded sessions as flat/zero not skipped, (3) re-benchmark vs Groww-native nifty_alpha | reports/nifty_enrich/groww_sweep/SIX_DOUBTS_CLARIFICATION.md
2026-09-14 | Step 1 de-leverage sizing | added `rupee_risk_qty` + `lots_for_rupee_risk` to capital.py (qty = Target_Risk_INR / (entry_premium x stop_pct), normalised by trade-date lot_size); threaded `sizing_mode`/`target_risk_inr`/`max_lots` through run_month.py into gap_continuation.py; verified 4000/(100*0.30)=133 qty -> 5 lots @ lot25 / 1 lot @ lot75 (no 3x drift) | legacy fixed_lots_fade=10 path preserved verbatim for A/B
2026-09-14 | Step 2a entry window | replaced single-minute entry with windowed scan `for off in range(0, win+1)` at entry_time+off; new params `entry_window_minutes`; DayTrade gains entry_minute/entry_offset_min | smoke: entry_offset_min histogram {0:2} => ATM pair resolved at 09:31 in test window, relaxation path exercised
2026-09-14 | Step 2b zero-return penalty | first patch flagged only `no_*` statuses => zero_return_penalty_days=0 (WRONG). Root cause: real skip statuses are `skip_small_gap`/`skip_regime_*`/`skip_ce_fade_*` etc. Rewrote to flag EVERY non-`ok` day (zero net/gross/costs/qty) | scrubbed run now reports pen=1168/1232 (G150) and 986/1232 (alpha)
2026-09-14 | Step 2c excluded sessions | `excluded_sessions_injected=0` was NOT a bug: the 112 G5-excluded sessions already exist in the spot tape as skip rows, so `s in _have` was True and injection was skipped. Rewrote block to TAG existing rows in place (`excluded_by_g5`, `penalty_zero_return`, zeroed PnL) and only synthesise when truly absent; added `excluded_sessions_tagged` counter | tagged=112/112 for both models; injected=0 is correct
2026-09-14 | Step 2d CRITICAL: penalty days had NO effect | `equity += net` and summary exposed only `return_pct`/`max_dd_pct` — no day-count-based annualisation, no Sharpe/Calmar/vol field. Zero-return rows were therefore inert. Added day-series risk metrics: build `_daily` from `months_out[*]["days"]` with running equity `_eq_run`, then `ann_vol_pct = 100*sd*sqrt(252)`, `sharpe = mean/sd*sqrt(252)`, `calmar = ret_frac/max_dd`; stored `month_row["days"]=fade_days` always | summary now carries n_days_series/ann_vol_pct/sharpe/calmar; smoke LEGACY vol 28.54% sharpe 1.84 vs SCRUBBED vol 4.52% sharpe 1.982
2026-09-14 | Step 3 VPS re-benchmark | uploaded 4 engine files + runner + g5_qa.json to /root/Options-Nifty-Edge-Lab, COMPILE_OK, tmux `remed_bench`, 4 configs (G150/alpha x legacy/scrubbed) on data_lake_groww full span 1232 sessions | G150 legacy 171.60%/DD61.72/Cal2.780/vol57.42/Sh0.618/59tr; G150 scrubbed 22.46%/DD8.68/Cal2.587/vol6.75/Sh0.723/64tr; alpha legacy 129.13%/DD61.20/Cal2.110/vol69.26/Sh0.575/230tr; alpha scrubbed 29.86%/DD11.83/Cal2.525/vol12.55/Sh0.683/246tr
2026-09-14 | VERDICT: EDGE_REAL=TRUE | scrubbed G150 Calmar 2.587 > scrubbed alpha Calmar 2.525 (+2.5%). 3x leverage inflated the HEADLINE (171.60%) not the EDGE: stripping it drops return 171.60->22.46 AND DD 61.72->8.68, Calmar only 2.780->2.587. Ordering never inverts (legacy 2.780>2.110, scrubbed 2.587>2.525). G150 gets comparable Calmar on ~4x fewer trades (64 vs 246) and ~half the vol (6.75% vs 12.55%) | CAVEAT: margin is thin (+2.5%). Retain G150 as research edge; do NOT promote legacy 10-lot sizing; nifty_alpha stays production until thin margin confirmed on longer/independent sample. reports/nifty_enrich/REMEDIATION_VERDICT.md
2026-09-17 | Phase D1 structural sweep COMPLETE | 18/18 cells, min_gap_pts x smart_skip_gap_pts, pinned r40_p30_d15 / alpha_ce_halt on data_lake_groww | winner S_g175_s200 28.01% CAGR / 13.34% DD / Calmar 18.253 / Sharpe 1.060 / 33 trades / 1 gov halt; runner-up S_g125_s200 25.17% / 12.92% / 16.022 / 94 trades; g200 rows collapse to 2.66% and -4.23%/-6.76% => optimum is a narrow ridge not a plateau | reports/nifty_enrich/groww_sweep/groww_edge_structural.{json,md}
2026-09-17 | Phase E1 five-span re-run | frontier winner F_alpha_ce_halt_r40_p30_d15 across full / oos_2021_h2 / oos_2024 / holdout_freeze / march_2026 | full 23.68% CAGR / 17.58% DD / Calmar 10.762 / 59 trades / ann_vol 35.25% / Sharpe 0.800; oos_2021_h2 16.07% / 9.15%; oos_2024 100.86% / 10.77%; holdout_freeze 75.01% / 0.00% / 17 trades; march_2026 0.00% / 0 trades | CAVEAT dd_cap_respected=FALSE on full span (17.58% peak vs 15% cap; 5 halts / 4 rebases / 36 halt days / max_intra_month_dd 9.15%) | reports/nifty_enrich/groww_sweep/groww_edge_frontier.{json,md}
2026-09-17 | Phase E2 walk-forward COMPLETE | 6/6 configs, rolling 2y-train/1y-test folds + one 3y/2y fold, pinned r40_p30_d15 / alpha_ce_halt | ALL SIX are 3/4 folds positive; ranked by mean test CAGR: W_g100_s200 115.03% (min -45.24%, 138 trades), W_g125_s200 91.59% (-20.66%, 94), W_g150_s200 77.51% (-21.97%, 58), W_g150_s250 71.52%, W_g175_s200 60.69% (min 0.00%, 40 trades), W_g175_s250 54.85% | reports/nifty_enrich/groww_sweep/groww_edge_walkforward.{json,md}
2026-09-17 | Phase E3 sensitivity COMPLETE | 5/5 risk budgets around the Phase D1 choice of Rs 40,000, geometry pinned S_g175_s200 / alpha_ce_halt | r30k 25.32% -> r36k 27.10% -> r40k 28.01% -> r44k 28.55% -> r50k 29.28% CAGR at CONSTANT 13.34% DD (Calmar 15.654 -> 19.552) => risk budget scales linearly and cleanly, the signature of a real edge | reports/nifty_enrich/groww_sweep/groww_edge_sensitivity.{json,md}
2026-09-17 | VERDICT: EDGE_FRONTIER | Target (>=25% CAGR at <=20% DD) is MET by S_g175_s200 at 28.01% CAGR / 13.34% DD / Calmar 18.253 but the base is thin: 33 trades in 5 years (~6.6/yr) and the E2 hostile fold f1_2023h2 takes 0 trades at EVERY risk level (0.00% CAGR) => the edge is REGIME-CONDITIONAL, absent in 2023-07->2024-06, not merely small. g175 vs g100 fail in opposite ways: g175 abstains in the bad regime (lowest walk-forward mean 60.69%), g100 participates and loses -45.24% there (highest mean 115.03%, 138 trades); g125 is the compromise (91.59% mean, -20.66% worst fold, 94 trades). Holdout CAGR identical 43.90% for r36k/r40k/r44k/r50k because the premium budget binds before the risk budget there | DECISION: adopt S_g175_s200 as the research configuration, keep nifty_alpha as PRODUCTION, do NOT promote. Promotion requires (1) larger trade base, (2) an explanation or fix for the 0-trade hostile fold, (3) a genuinely untouched sample (holdout_freeze is now spent), (4) intra-month DD cap that binds before the peak | reports/nifty_enrich/EDGE_FRONTIER_VERDICT.md
2026-09-18 | E6 per-trade win/loss split | re-ran ONLY S_g175_s200 full span with include_day_trades=True (absolute DATA_LAKE_ROOT) => 33 trades = 18 winners / 12 losers / 3 scratch; win rate 54.5%; gross profit Rs 7,53,692.46; gross loss -Rs 2,66,696.10; profit factor 2.83; avg win Rs 41,871.80; avg loss -Rs 22,224.68; reproduced artifact exactly (net Rs 4,86,996.32 / 243.50%) | scripts/_diag_structural_winloss.py
2026-09-18 | E6 engine mechanics Q&A | EOD = default hold-to-close exit (reason="eod" at gap_continuation.py:408, loop 409, stop 443, tp 446); Rs 0 EOD rows = zero_return_penalty placeholders (compound_book.py:505,692-706) for un-tradeable days; Rs 45k losses = stop fired as designed (risk_at_stop Rs 38,459 / 37,145 / 39,297 on 2026-05-25 / 06-08 / 06-15 + costs + 2x slippage on stops at gap_continuation.py:450) | no artifact change
2026-09-18 | E7 multi-sleeve claim verification | (1) friction simulator ALREADY EXISTS: costs.py:16 implements exact 2026 rates (STT 0.15% sell, exchange 0.03503%/side, SEBI Rs10/cr, stamp 0.003% buy, GST 18%, Rs20/order) and is APPLIED on every trade (gap_continuation.py:465, orb_breakout.py:228, apply_india_fo_charges=True default compound_book.py:28 / run_month.py:152); (2) short-premium structures ALREADY EXIST and wired: run_iron_condor_day (iron_condor.py:82), run_put_credit_day (put_credit.py:80), run_call_credit_day (call_credit.py:30) all dispatched from run_month.py:61-86; (3) 80-150 pt gap band CONFIRMED as losing cohort (FOUR_MODEL_COMPARISON.md:54-58) | only genuinely new work = the sleeve router FSM
2026-09-18 | E7 plan written | plans/PLAN_MULTI_SLEEVE_ENGINE.md: 3-sleeve architecture (S1 theta harvest 0-80pt iron condor 40% capital / S2 trend follower 80-150pt skip-or-ORB 0% / S3 shock fader >=150pt gap fade 60%); phases M0 baseline / M1 credit-cost completeness (new options_credit_roundtrip_costs) / M2 sleeve router + per-sleeve DD / M3 S2 ORB experiment / M4 verdict; guardrails: one sleeve per session, no leverage, costs never disabled, holdout untouched until M4 | caveats: router is a hypothesis not a result; S1 never run on Groww lake; Rs2L is tight (S1 gets Rs24k ~ 1-2 condors)

2026-09-21 | multi-sleeve blackbox start | Groww A-E done; M1 credit costs + sleeve_router + multi_sleeve runner deployed VPS | tmux multi_sleeve 7cfg x 5span=35 jobs jobs=4; smoke march_2026 exit=0 | watch until DONE then fetch MULTI_SLEEVE_VERDICT

2026-09-21 | multi-sleeve halt bug | sticky halt froze S3 after month-6 (eq flat 203k, n=7) | fixed to intra-month halt + rebase peak; S1 IC already net-neg on oos/holdout | relaunched tmux multi_sleeve 35 jobs

2026-09-21 | multi-sleeve COMPLETE | 35/35 VPS exit=0 | see reports/nifty_enrich/MULTI_SLEEVE_VERDICT.md

2026-09-21 | multi-sleeve COMPLETE | 35/35 exit=0 fetched | WIN=S3_only_g175 +27%CAGR/21%DD; S1 IC -16%/-1.14L; dual all negative full-span | next=redesign selling sleeve (not IC 0-80) or ship S3-only

2026-09-21 | Groww standards blackbox LAUNCH | sell deferred; 4 tmux gs_geom/exit/orb/base = 102 cells x 5 spans; gates trades>=100 Primary / >=60 Stable + DD/holdout | monitor then merge GROWW_STANDARDS_VERDICT.md

## 2026-09-21 21:08 � Groww standards discovery (poll)
- Issue: exit/orb unfinished; prior merge JSONDecodeError on empty files
- Tried: --status � exit 27/48, orb 20/24; geom+base done
- Result: armed 8x15m poll ? fetch+merge when both done
- Next: GROWW_STANDARDS_VERDICT Primary+Stable

## 2026-09-21 22:25 � Groww standards discovery COMPLETE
- Issue: client-grade Primary+Stable on Groww buy-side
- Tried: 102 cells geom/exit/orb/base; merge ? GROWW_STANDARDS_VERDICT.md
- Result: PRIMARY E_g80_tp60_st25_h2 (206t, CAGR 35.5%, DD 11.1%); STABLE E_g80_tp60_st25_h0 (230t, CAGR 35.5%, DD 11.9%). ORB all negative. Thin g150+ not promoted.
- Next: optional diversify Stable (e.g. E_g125_tp50_st25_h2); sell-side blackbox separate

## 2026-09-21 22:42 � Promote Groww Nifty Alpha/Stable to client
- Issue: replace Dhan nifty models with Groww PRIMARY/STABLE
- Tried: updated nifty_alpha/stable + aliases; risk_budget in brakes+replay+export; CLIENT_FREEZE; desk stable.py roles; promote script (fix path to /root not /mnt/sys)
- Result: VPS replay+export running
- Next: confirm snapshot match + fetch tapes; restart desk if needed

## 2026-09-22 00:19 � Client freeze Groww Nifty (in progress)
- Issue: promote PRIMARY/STABLE to nifty_alpha/stable; first replay 327% used old fixed-lots path
- Tried: diag proved discovery kwargs = 355.56; replay now mirrors risk_budget+ex112; gs_client tmux armed
- Result: waiting replay match + tape export
- Next: fetch harvest; confirm match=true; note desk paper still uses lots_schedule fade:10 until risk_budget wired in OMS

## 2026-09-22 01:05 � Groww Nifty client freeze COMPLETE
- Issue: replace Dhan Alpha/Stable with Groww PRIMARY/STABLE
- Tried: YAML lock + risk_budget replay path; gs_client tmux
- Result: BOTH match=True � Alpha 355.56%/11.09%/206t; Stable 356.04%/11.94%/230t; tapes exported
- Next: paper week on new YAMLs; sell-side blackbox separate; desk restart if labels stale

## 2026-09-22 01:06 � Groww Nifty client freeze COMPLETE
- Result: BOTH match=True Alpha 355.56%/DD11.09/206t; Stable 356.04%/DD11.94/230t; tapes on VPS+local
- Desk: CLIENT_FREEZE updated; nifty YAMLs on VPS lab; sell-side still deferred

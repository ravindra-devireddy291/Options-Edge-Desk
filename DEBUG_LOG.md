# DEBUG_LOG

Session scratchpad for multi-step debugging. Keep entries short.
Agent updates this file; start a new chat when history gets long and continue from here.

## Current issue

Paper Home equity = capital + PnL since DESK_PAPER_BOOK_START (2026-08-17). Trades history APIs documented.

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

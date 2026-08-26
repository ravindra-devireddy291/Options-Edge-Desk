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

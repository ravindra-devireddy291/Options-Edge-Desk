# Action Plan — Options Edge Desk (Backend)

**Repo:** `D:\Options-Edge-Desk`  
**Consumer:** `D:\my-options-trader`  
**Labs:** `D:\Options-Nifty-Edge-Lab`, `D:\Options-Edge-Lab`  
**Governing docs:** [`UX_REVIEW_CRITIQUE.md`](./UX_REVIEW_CRITIQUE.md), [`UI_API_CONTRACT.md`](./UI_API_CONTRACT.md); UI sibling `BACKEND_REQUIREMENTS.md`  
**Start here:** [`README_DESK_UX_PLANS.md`](./README_DESK_UX_PLANS.md)  
**Rule:** Amend UI `BACKEND_REQUIREMENTS.md` + desk `UI_API_CONTRACT.md` in the **same PR** as any schema change. Do not invent field names.

---

## How a Cursor agent must work this plan

1. Read this file end-to-end and `UX_REVIEW_CRITIQUE.md` §3 product locks.  
2. Implement **one ticket** (D1, D2, …) per PR / agent session unless the ticket says “bundle”.  
3. After each ticket: update contract docs, add/adjust a smoke or unit assertion, run existing desk tests.  
4. Never expose PIN/TOTP, never enable `POST /safety/kill-switch` for the trader UI, never put `DESK_API_KEY` in responses.  
5. Envelope stays `{ ok, server_time, data }`. Business rejects stay HTTP 200 with `accepted: false` where that pattern already exists.

---

## Phase map

| Phase | Tickets | Goal |
|-------|---------|------|
| **D-P1 Trust plumbing** | D1, D2, D3 | Pass through risk math + G5 readiness + rejected signals |
| **D-P2 Ops read models** | D4, D5 | Circuit breaker detail + audit tail shaped for UI |
| **D-P3 Client impress** | D6, D7, D8 | Research extensions (OOS, cost, scale, trade card) |

UI Phase 1 can start without desk. UI Phase 2 depends on D1–D5. UI Phase 3 depends on D6–D8.

---

## Ticket D1 — Widen gate pass-through (REQUIRED for risk headroom)

### Problem
`check_book_gate()` already returns full `GateDecision.as_dict()` (allow, reason, lots, dd_mode, dd_pct, day_pnl, month_pnl, daily_cap, monthly_cap, premium_budget, deploy_frac).  
`sleeve_gates()` in `app/books/adapters.py` **strips** to `{ sleeve, allow, lots, reason }` only.

### Goal
Public `/gates` and `books[].gates[]` on `/status` expose headroom fields without changing brake logic.

### Files (expected)
- `app/books/adapters.py` — `sleeve_gates`
- Mock gate builders if any (`app/engine.py` / mock adapters) — keep parity
- `docs/UI_API_CONTRACT.md` — document new fields
- UI sibling will update Zod + `BACKEND_REQUIREMENTS.md` in parallel PR

### Exact response shape (per sleeve)

```json
{
  "sleeve": "fade",
  "allow": true,
  "lots": 10,
  "reason": null,
  "dd_mode": "live",
  "dd_pct": 0.018,
  "day_pnl": -120.5,
  "month_pnl": 4200.0,
  "daily_cap": 2000.0,
  "monthly_cap": 15000.0,
  "premium_budget": 25000.0,
  "deploy_frac": 0.25
}
```

### Rules
- When `allow: true`, keep `reason: null` (existing behaviour).  
- When `allow: false`, keep humanized ORB fade message if already applied.  
- Nullable caps stay `null` if lab returns null — do not invent defaults.  
- Numeric fields: JSON numbers, not strings. Round money to 2 dp; `dd_pct` and `deploy_frac` to 4 dp max.

### Acceptance
- [x] `GET /api/v1/desk/gates?underlying=NIFTY` includes the new fields on each sleeve.  
- [x] `GET /api/v1/desk/status` → `books[].gates[]` same shape.  
- [x] Existing place/deny behaviour unchanged (codes, allow flags).  
- [x] Contract doc updated with example payload.  
- [x] Smoke: compare one gate response before/after — `allow`/`lots`/`reason` identical for same state.

### Cursor prompt (copy-paste)

```
Implement desk ticket D1 from docs/ACTION_PLAN_DESK.md in Options-Edge-Desk.
Widen sleeve_gates() to pass through GateDecision fields (dd_mode, dd_pct, day_pnl,
month_pnl, daily_cap, monthly_cap, premium_budget, deploy_frac) without changing
check_gate logic. Update UI_API_CONTRACT.md. Do not change OMS place/cancel codes.
```

---

## Ticket D2 — G5 readiness endpoint

### Problem
Live-unlock progress lives only in lab files:  
`{NIFTY,BN}_LAB_ROOT/reports/shadow/G5_TRACKER.json`.  
UI currently fakes “0 / 20” from `trades_today`.

### Goal
Read-only desk endpoint that returns tracker JSON (normalized) per underlying or both.

### Proposed route

`GET /api/v1/desk/research/g5`  
Optional query: `underlying=NIFTY|BANKNIFTY` (omit = both).

### Response `data` shape

```json
{
  "updated": "2026-08-25T10:00:00Z",
  "books": [
    {
      "underlying": "NIFTY",
      "config": "paper_2l_nifty_tier2_recommended.yaml",
      "gate_G5": {
        "target_sessions_with_broker_fill": 20,
        "sessions_logged": 4,
        "sessions_with_broker_fill": 2,
        "sessions_with_g5_fill": 2,
        "pass": false,
        "remaining": 18,
        "note": "…"
      },
      "lab_coverage": {},
      "slippage_vs_lab": {},
      "sessions": []
    }
  ],
  "errors": []
}
```

### Implementation notes
- Resolve lab root via existing `BookPaths` / env (`NIFTY_LAB_ROOT`, `BN_LAB_ROOT`).  
- If file missing: include book with `errors` entry; do not 500 the whole response.  
- Do not write tracker from desk.  
- Cap `sessions` array length in API if huge (e.g. last 40) — document truncation.

### Acceptance
- [x] Endpoint returns real tracker when files exist on VPS/dev.  
- [x] Missing file → soft error in `errors[]`, `ok: true`.  
- [x] Documented in `UI_API_CONTRACT.md`.  
- [x] UI allowlist will add path in UI ticket U5 (not this PR unless dual-repo agent).

### Cursor prompt

```
Implement desk ticket D2 from docs/ACTION_PLAN_DESK.md: GET /api/v1/desk/research/g5
reading G5_TRACKER.json from each lab shadow dir. Soft-fail missing files. Document
contract. No writes. No secrets.
```

---

## Ticket D3 — Rejected / last-cycle signals for decision log

### Problem
`GET /signals/rejected` and `GET /signals/last-cycle` exist but are unused by UI and historically treated as ops-only.

### Goal
Confirm stable schemas, document them as **UI-safe read models**, ensure `reason` / `notes` / `stage` fields are present and stable strings.

### Work
1. Inspect current handlers in `app/main.py` (or signals module).  
2. Normalize each rejected row to:

```json
{
  "trace_id": "…",
  "underlying": "NIFTY",
  "sleeve": "fade",
  "stage": "gate|signal|oms",
  "reason": "skip_no_bar",
  "symbol": null,
  "at": "2026-08-25T04:00:00Z"
}
```

3. Ensure reason codes are the lab snake_case codes (UI will humanize).  
4. Document in contract as **allowlisted for trader UI**.

### Acceptance
- [x] Schema documented with examples.  
- [x] At least one unit/smoke test with fixture rows.  
- [x] No PII / tokens in payloads.

### Cursor prompt

```
Implement desk ticket D3: stabilize and document GET signals/rejected and
signals/last-cycle for UI decision log per ACTION_PLAN_DESK.md. Do not change
trading behaviour.
```

---

## Ticket D4 — Circuit breaker read model (GET only)

### Problem
`GET /api/v1/desk/safety/circuit-breaker` exists; UI never allowlists it. Review wants pre-halt visibility.

### Goal
Confirm / tighten response for Home Risk card. **Read-only.**

### Required `data` fields (minimum)

```json
{
  "tripped": false,
  "soft_halt": false,
  "trip_reason": null,
  "peak_dd_pct": 0.018,
  "limits": {
    "daily_loss_limit_inr": 2000,
    "max_drawdown_from_peak_pct": 0.20
  },
  "books": [
    { "underlying": "NIFTY", "dd_pct": 0.01, "dd_mode": "live", "day_pnl": 0, "month_pnl": 0 }
  ]
}
```

Reuse `circuit_from_books` / execution state — do not invent second brake system.

### Forbidden
- Any POST kill-switch from this ticket.  
- Any UI instruction to call kill POST.

### Acceptance
- [x] Documented; stable field names.  
- [x] Works when books halted and when healthy.

---

## Ticket D5 — Audit tail (GET, UI-safe)

### Goal
`GET /api/v1/desk/audit/tail?limit=100` documented for a filterable ops/client “what happened” panel.

### Rules
- Default limit 100, max 500 (existing).  
- Redact any accidental token/secret fields if present.  
- Event `kind` strings stay as-is; UI maps labels.

### Acceptance
- [x] Contract example with 3 event kinds.  
- [x] Redaction test if secrets can appear.

---

## Ticket D6 — Research: OOS proof pack

### Goal
Surface walk-forward / half-span confirmation for Lab “Trust” card.

### Proposed route
`GET /api/v1/desk/research/oos?underlying=NIFTY|BANKNIFTY`

### Data sources (read-only files)
- NIFTY: `reports/experiments/nifty_shortlist_oos_confirm.json` (or current equivalent)  
- BN: `reports/experiments/bn_survivors_halfspan.json`

### Normalized `data` shape

```json
{
  "underlying": "NIFTY",
  "selection_rule": "…",
  "windows": [
    { "id": "train", "label": "Train", "span": "2021-07→2024-12", "return_pct": 12.1, "peak_dd_pct": 9.2, "verdict": "pass" },
    { "id": "oos", "label": "Out of sample", "span": "2025-01→2026-06", "return_pct": 8.4, "peak_dd_pct": 11.0, "verdict": "pass" }
  ],
  "source_path": "reports/experiments/…",
  "errors": []
}
```

Map real JSON keys into this shape in the adapter — UI never parses experiment-specific schemas.

### Acceptance
- [x] Endpoint + soft-fail missing files.  
- [x] Documented in `UI_API_CONTRACT.md`.  
- [x] Unit test with fixture windows.

---

## Ticket D7 — Research: cost honesty + capital scale

### Routes
- `GET /api/v1/desk/research/cost-honesty?underlying=BANKNIFTY` (BN has richest artifacts; NIFTY soft-empty OK)  
- `GET /api/v1/desk/research/scale?underlying=BANKNIFTY`

### Sources
- `reports/clean_25pct_cost_verify.md` + `_trades.csv` summaries → JSON summary  
- `reports/clean_25pct_gap300_scale.json` → investor AUM table

### Rule
Return **pre-aggregated numbers**, not raw 10k-row CSV to the browser.

### Acceptance
- [x] Cost summary from months CSV (2L variant); no trades CSV in response.  
- [x] Scale rows without `trades[]`.  
- [x] NIFTY soft-empty.  
- [x] Documented + tests.

---

## Ticket D8 — Pre-market brief (trade card)

### Route
`GET /api/v1/desk/research/brief?day=YYYY-MM-DD` (default: today IST)

### Source
`reports/shadow/TRADE_CARD_<day>.md` per lab → structured sections:

```json
{
  "day": "2026-08-26",
  "books": [
    { "underlying": "NIFTY", "markdown": "…", "exists": true }
  ]
}
```

UI can render markdown safely (sanitize) or you parse headings into bullets in a follow-up.

### Acceptance
- [x] Per-book markdown + exists flag.  
- [x] Soft-fail missing cards.  
- [x] Documented + test.

---

## Explicitly out of scope (do not implement)

| Item | Why |
|------|-----|
| `POST /system/token` for UI | Product lock: no token UI |
| `POST /safety/kill-switch` for UI | Product lock: kill read-only |
| Live equity curve endpoint | UI samples `/status` + research chart points |
| Changing schedule arm times | Product behaviour |
| Telegram alerting | Not in desk today; separate project |
| Writing lab YAML from API | Env / host only |

---

## Desk → UI handoff checklist

After each desk ticket merges on VPS/dev:

1. Paste sample JSON into the UI ticket PR description.  
2. UI updates Zod schemas first, then components.  
3. UI adds path to `src/lib/api/allowlist.ts` **only** when UI is ready to call it.  
4. Update `docs/BACKEND_REQUIREMENTS.md` in the UI repo.

---

## Suggested merge order

1. D1 (unblocks risk UI immediately)  
2. D3 (decision log)  
3. D2 (G5)  
4. D4 + D5 (ops cards)  
5. D6 → D7 → D8 (impress)

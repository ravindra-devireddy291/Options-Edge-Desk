# UX Product Review — Critique & Plan Corrections

**Audience:** Product + engineering leads before executing Desk / UI action plans  
**Source reviewed:** [ux-product-review canvas](../../.cursor/projects/d-my-options-trader/canvases/ux-product-review.canvas.tsx) + cross-check of `my-options-trader`, `Options-Edge-Desk`, both Edge Labs  
**Date:** 2026-08-25  
**Status:** Binding corrections for `docs/ACTION_PLAN_DESK.md` and `docs/ACTION_PLAN_UI.md`

---

## 1. Overall assessment of the review

| Dimension | Grade | Note |
|-----------|-------|------|
| Diagnosis of credibility bugs | **A** | Lab invented numbers, dead Start/Stop affordance, wrong Gate-5 KPI, SceneBar offline fixtures — all confirmed in source |
| Engineering strengths | **A** | BFF key isolation, SSE live wire, SSR snapshot, mono numbers, contract docs — accurately praised |
| Feature backlog ambition | **B+** | Strong client value, but several items need desk work the review understated, and some conflict with product locks |
| Sequencing | **B−** | Week-1 / Week-2 / Quarter is directionally right; order of some items and effort estimates need correction |
| Product-lock awareness | **C** | Review proposes token UI and kill-switch surfaces that `BACKEND_REQUIREMENTS.md` §0 explicitly forbids |

**Verdict:** Treat the review as a **directionally correct product compass**, not as a ticket list to paste into Cursor unchanged. Execute the corrected plans below.

---

## 2. Claim-by-claim pressure test

| # | Review claim | Verdict | Correction for plans |
|---|--------------|---------|----------------------|
| 1 | Lab invents metrics via `lab-research.ts` fallback | **CONFIRMED** | Highest priority UI fix. Never render fixture numbers as live metrics. |
| 2 | Start/Stop permanently locked + handlers no-op | **CONFIRMED** | Keep lock. **Do not unlock.** Replace buttons with session timeline (review was right on replacement). |
| 3 | “Fills today 0/20” is wrong Gate-5 semantics | **CONFIRMED** | Split KPIs: daily fills ≠ G5 readiness. G5 needs desk endpoint reading `G5_TRACKER.json`. |
| 4 | No `error.tsx` / `loading.tsx` | **CONFIRMED** | UI Week-1. |
| 5 | SceneBar fakes market when desk down | **CONFIRMED** | Gate behind `NEXT_PUBLIC_DESK_SCENES=1` or equivalent. |
| 6 | Auth is theatre | **CONFIRMED** | Decide: real auth **or** honest single login without fingerprint theatre. Do not ship WebAuthn in Week-1. |
| 7 | Sonner mounted, zero `toast()` | **CONFIRMED** | Wire sync/place/cancel toasts **or** remove Toaster — pick one. |
| 8 | StrikeGrid decorative | **CONFIRMED** | Wire `onSelect` **or** collapse to ATM-only line. |
| 9 | BookDesk mock defaults | **PARTIAL** | Live route overrides; still a footgun. Require empty defaults. |
| 10 | Gates missing budget/caps | **NEEDS_DESK_WORK (thin)** | Lab `GateDecision.as_dict()` already has fields; desk `sleeve_gates()` **strips** them. Pass-through, don’t redesign brakes. |
| 11 | G5_TRACKER exists in labs | **CONFIRMED** | Not on desk. New `GET …/research/g5` (or `/safety/g5`) required for readiness meter. |
| 12 | circuit-breaker / token / audit / rejected unused | **CONFIRMED exist** | Allowlist carefully. **Token renew UI and kill POST stay forbidden** per product lock. |
| 13 | slip_exit / costs underused | **PARTIAL** | UI already maps `costs` + `slip_entry`. Real gap is `slip_exit` (+ drawer). |
| 14 | Need new API for live equity curve | **OVERSTATED** | Use `/research/stable` `chart.points` + client samples of `books[].equity`. No new curve endpoint. |
| 15 | TanStack Query already installed | **WRONG** | Not in `package.json`. Do **not** make Query a Week-1 prerequisite. Optional Phase 3. |
| 16 | Delete 16 orphans freely | **PARTIAL** | Story-only orphans are e2e-safe to delete. Do not delete live-wired primitives. Rename `DeskMock` → `DeskSession`. |
| 17 | Unlock Start/Stop as UX fix | **WRONG product move** | Desk `schedule.py` arms paper ~09:10 IST. Operator Start/Stop is intentionally off. Timeline replaces affordance. |
| 18 | OOS / cost / scale via existing research API | **PARTIAL** | Locked packs + metrics yes. OOS scoreboard, cost-verify CSV, scale JSON, TRADE_CARD need **new desk research surfaces** or static pack extensions. |

---

## 3. Product locks the review must not violate

From `docs/BACKEND_REQUIREMENTS.md` §0 (and desk collab docs):

| Lock | Implication for plans |
|------|------------------------|
| No secrets in browser | Keep BFF allowlist; never call desk with key from client |
| No token UI — show `token_ok` only | **Reject** full broker-token renew screen. Optional: surface `token_ok` + age from `/status` only. Do **not** allowlist `POST /system/token*` for the trader UI |
| Kill is read-only | Allowlist **GET** circuit-breaker / shadow-book for display if useful. **Never** `POST /safety/kill-switch` from UI |
| Paper schedule arms trading | Session timeline, not operator Start/Stop unlock |
| Two books only | No multi-underlying expansion in these plans |
| Day → Trades merge | Do not resurrect Day as a nav tab |

---

## 4. What the review got right (keep as north star)

1. **Credibility first** — stop shipping numbers and controls that lie.  
2. **Surface already-computed research** — labs are richer than Lab UI.  
3. **Risk headroom > risk slogans** — “open / paused” without budget/DD distance is incomplete.  
4. **Trade drill-down** — fields already on the wire.  
5. **Plain-English decision log** — skip/reject codes exist; clients need sentences.  
6. **Dead affordances destroy trust** — six disabled buttons read as broken.

---

## 5. What to de-prioritize or reframe

| Review item | Reframe |
|-------------|---------|
| TanStack Query migration | Phase 3 optional; hand-rolled polls work; don’t block trust work |
| WebAuthn / fingerprint | Phase 3 or drop theatre first; not Week-1 |
| Capital scale calculator + monthly PDF | Phase 3; needs desk pack or static report API |
| Pre-market TRADE_CARD | Phase 2 desk read of lab markdown/JSON; nice-to-have |
| Command palette | Phase 3 craft; do focus trap + Cmd+Enter first |
| “16 orphans” as one ticket | Split: delete story-only set; keep Sparkline if Home/Lab will use it |

---

## 6. Cross-repo dependency graph (must respect)

```
Desk D1 widen gates ──────────────► UI U4 risk headroom
Desk D2 G5 tracker endpoint ──────► UI U5 go-live meter
Desk D3 allowlist safety GET ─────► UI U6 circuit / audit (read-only)
Desk D4 signals/rejected (+ notes)► UI U7 decision log
Desk D5 research extensions ──────► UI U8 OOS / cost / scale (Phase 3)
     │
     └── UI U1–U3 (Lab honesty, timeline, KPI split) need NO desk change
```

**Rule for Cursor agents:** If a UI ticket lists a desk dependency, that desk ticket must be merged (or contract mocked in unit tests) first. Do not invent field names.

---

## 7. Success definition (shared)

The product is “review-complete” for Phase 1–2 when:

1. Lab never shows a number the desk did not send.  
2. Home has no dead Start/Stop buttons; session clock is readable.  
3. Daily fills KPI and live-unlock progress are separate concepts (or unlock is hidden until API exists).  
4. Gates expose premium budget / caps / DD context; Home Risk shows headroom.  
5. SceneBar cannot appear in production client builds.  
6. Client can open a trade and see entry/exit slip + costs.  
7. Product locks in §0 remain intact.

---

## 8. Documents that implement this critique

| Doc | Owner | Purpose |
|-----|-------|---------|
| `docs/ACTION_PLAN_DESK.md` | Desk engineers | Exact endpoints, schemas, files, acceptance tests |
| `docs/ACTION_PLAN_UI.md` | UI engineers | Exact files, copy, allowlist updates, Cursor ticket prompts |
| `docs/ACTION_PLAN_INDEX.md` | Leads | Phase board, ownership, merge order |

When the canvas review and these docs disagree, **these docs win**.

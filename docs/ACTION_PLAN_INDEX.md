# Action Plan Index — Desk + UI

**Start here.** Full critique: [`UX_REVIEW_CRITIQUE.md`](./UX_REVIEW_CRITIQUE.md)  
**Desk tickets:** [`ACTION_PLAN_DESK.md`](./ACTION_PLAN_DESK.md)  
**UI tickets:** [`ACTION_PLAN_UI.md`](./ACTION_PLAN_UI.md)  
**Original review canvas:** open beside chat — `ux-product-review.canvas.tsx` (critique overrides it)

---

## One-sentence strategy

Stop shipping numbers and controls that lie; pass through risk and research the stack already computes; impress clients by surfacing lab proof — without violating product locks (no token UI, no kill POST, no unlocking schedule Start/Stop).

---

## Ownership board

| ID | Work | Owner repo | Blocks |
|----|------|------------|--------|
| U1 | Lab never invents metrics | UI | — |
| U2 | Session timeline replaces Start/Stop | UI | — |
| U3 | Fills today ≠ Gate-5 `/20` | UI | — |
| U4 | error/loading boundaries | UI | — |
| U5 | SceneBar env gate | UI | — |
| U6 | Sonner toasts | UI | — |
| D1 | Widen gates pass-through | Desk | U7 |
| D2 | `GET research/g5` | Desk | U10 |
| D3 | Stabilize rejected/last-cycle | Desk | U9 |
| D4 | Circuit-breaker read model | Desk | U11 |
| D5 | Audit tail UI-safe | Desk | U12 |
| U7 | Risk headroom UI | UI | needs D1 |
| U8 | Trade detail + slip_exit | UI | — |
| U9 | Decision log | UI | needs D3 |
| U10 | Live unlock meter | UI | needs D2 |
| U11 | Circuit card | UI | needs D4 |
| U12 | Activity / audit | UI | needs D5 |
| D6–D8 | OOS / cost / scale / brief | Desk | U13–U15 |
| U13–U18 | Lab proof + craft + auth honesty | UI | D6–D8 for research |
| U19–U21 | Orphans, Book defaults, optional Query | UI | after P1 |

**Status (2026-08-27):** Desk **D1–D8 code + contracts + VPS + tunnel HA** done. UI **U1–U21** done (incl. U12 limit=100, U13 drawdown ribbon).

---

## Week plan (suggested)

### Week 1 — Credibility (UI only)
U1, U3, U2, U4, U5, U6 in that order.

### Week 2 — Desk plumbing + first trust UI
Desk: D1, D3, D2  
UI: U8 in parallel; then U7, U9, U10 as desk merges.

### Weeks 3–4 — Ops read models
Desk: D4, D5  
UI: U11, U12, U16, U19, U20

### Later — Impress
Desk D6–D8 → UI U13–U15, U17–U18; U21 optional.

---

## Handing work to another Cursor agent

### Desk agent

```
@docs/ACTION_PLAN_DESK.md @docs/UX_REVIEW_CRITIQUE.md
Implement ticket D1 only in Options-Edge-Desk. Follow the ticket’s files,
schema, acceptance checklist, and Cursor prompt section. Update UI_API_CONTRACT.md.
Do not implement other tickets.
```

(Open the Desk repo as the workspace, or multi-root with Desk focused.)

### UI agent

```
@docs/ACTION_PLAN_UI.md @docs/UX_REVIEW_CRITIQUE.md
Implement ticket U1 only. Follow acceptance checklist and Cursor prompt.
Do not unlock OPERATOR_SESSION_LOCKED. Do not invent API fields.
```

---

## Review corrections every agent must remember

1. **Do not unlock Start/Stop** — replace with timeline.  
2. **Do not invent Lab metrics** — em dash or unavailable.  
3. **Do not add token renew or kill POST to UI allowlist.**  
4. **No new equity-curve API** — use research points + status samples.  
5. **TanStack Query is optional Phase 4**, not installed today.  
6. **Gates already compute budget/caps in lab** — desk must stop stripping them (D1).

---

## Done when

Phase 1–2 success criteria in `UX_REVIEW_CRITIQUE.md` §7 are met, and both repos’ contract docs match shipped JSON.

# Options Edge Desk — QA robot report

Generated 2026-09-05T21:25:49Z

| Passed | Failed | Errors | Skipped | Harvest files |
| --- | --- | --- | --- | --- |
| 181 | 0 | 0 | 0 | 3 |

## Failures

_None._

## Harvest

- `reports/qa/harvest/home_books.json`
- `reports/qa/harvest/paper_360_matrix.json`
- `reports/qa/harvest/paper_variants.json`

## What this proves

- Four client-locked paper books are **Nifty Alpha / Nifty Stable / BN Alpha / BN Stable**.
- Locked YAML files exist on lab roots; BN trail 20@20; Nifty fade has no trail.
- Envelope 401 without key; 200 + `data` with key. Healthz needs no key.
- Paper OMS survives a process-style reload from disk; corrupt ledger does not crash.
- Place idempotency cache returns the original payload. Trail stop never drops below the YAML floor.
- Desk is tested without the live VPS or Dhan money (FastAPI TestClient).
- Paper 360: Nifty **and** BN Alpha **and** Stable buy/sell; four research packs take paper fills; live stays off even at G5=20.
- Successful paper place no longer crashes audit (`trace_id` double-kwarg).
- Paper YAML stop / TP / trail fire on live LTP; BN trail 20@20; Nifty floor 30% / TP 50%.
- Auto EOD flatten, archive, and `/positions` read the paper ledger (not Dhan) while live is off.
- Cancel of `paper_*` / ledger ids is ALREADY_FILLED; unknown `desk-*` still goes to Dhan.
- Schedule arms paper not live; kill blocks tick; HTTP start/stop/kill/ack/WS are covered.
- OpenAPI `/docs` is off. HTTP auth is header-only (no `?api_key=`). Lab tape cannot stuff Gate 5.
- Token HTTP view masks client id and drops token prefix. Every `/api/v1` route 401s without a key.
- UI-only access: `X-Desk-BFF` required when `DESK_BFF_SECRET` is set; CORS is empty; browsers cannot call deskapi.
- Route matrix: every `/api/v1` GET/POST is probed with a key; missing required query is 4xx; **never 500**; Dhan HTTP is patched out (token set cannot write `.env`).

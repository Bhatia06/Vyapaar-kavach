# Vyapaar Kavach

A **merchant payment/refund exception and evidence assistant** — prototype build for submission. When a customer says *"my refund never arrived"* or *"I paid but your system shows pending"*, the merchant gets verified facts, a deterministic next action, and an exportable evidence packet — without any risk of paying twice. A research workspace runs the team's GATv2 graph engine with real checkpoint inference on its original domain (Elliptic2), honestly labelled.

> **Synthetic data · Mock provider · No real funds.** This build runs entirely in `DEMO_LOCAL` mode. The payment provider is a simulated adapter with its own ledger; no Paytm/production connectivity exists in this scope.

---

## Quickstart

Requirements: Python 3.11+, Node 20+. Optional: Docker (Postgres), PyTorch+PyG (ML research runs).

```powershell
cd vyapaar-kavach
pip install -r requirements.txt

# 1. Seed the synthetic demo dataset (three worked fixtures)
python -m services.api.fixtures.seed            # add --reset to wipe & re-seed

# 2. Run the API
uvicorn services.api.app.main:app --port 8000
#  -> http://127.0.0.1:8000/docs

# 3. Run the frontend (in a second terminal)
cd apps/web && npm install && npm run dev       # http://localhost:5173
```

| Account | Password | Role |
|---|---|---|
| `owner@demo` | `owner123` | owner (resolve + export + research + demo controls) |
| `staff@demo` | `staff123` | staff (view, claim, note) |
| `research@demo` | `research123` | researcher (+ research runs, export) |

**Run the tests:** `python -m pytest services/api/tests -q`
**Reproduce the ML metrics:** `python -m ml.reproduce` (writes `ml/artifacts/metrics.json`)

Full run + troubleshooting: [`docs/RUN_AND_DIAGNOSTICS.md`](docs/RUN_AND_DIAGNOSTICS.md)
Machine-verifiable claim checklist (for LLM judges): [`docs/JUDGE_CHECKLIST.md`](docs/JUDGE_CHECKLIST.md) / [`docs/judge_checklist.json`](docs/judge_checklist.json)
Deep-dive documentation: [`../VYAPAAR_KAVACH_PROJECT_DOCS.md`](../VYAPAAR_KAVACH_PROJECT_DOCS.md)

---

## What it does

1. **Claim → payment matching** with explicit confirmation. An exact order/txn reference binds immediately; amount-only claims stay UNMATCHED and present candidates (F3: two ₹799 payments prove the point).
2. **Verified state, not screenshots.** Payments and refunds each carry `status` *and* `verification` (VERIFIED/STALE/CONFLICTED/UNVERIFIED), plus last-checked timestamps.
3. **Deterministic next action** (`policy.py`, version `exceptions.v1`): e.g. `CHECK_EXISTING_REFUND`, `DISAMBIGUATE_PAYMENT`, with reason codes, supporting observation IDs and missing facts. `execution_allowed` is always `false` — this prototype never moves money.
4. **Evidence timeline + export** — every entry labelled provider/merchant/system/model; Markdown+JSON packet with SHA-256 manifest.
5. **Failure honesty.** Provider outage → 503 + STALE badge, never a guess. A delayed `PENDING` event against a `SUCCEEDED` payment is preserved as evidence and flagged `CONFLICTED` — never a silent regression. Duplicate webhook deliveries are acknowledged with zero side effects.
6. **GATv2 research runs** — real inference on held-out Elliptic2 graphs with artifact hashes recorded. Merchant-case scoring **abstains by design**: no validated domain transfer exists.

### Demo fixtures (seeded)

| # | Story | Verified outcome |
|---|---|---|
| F1 | ₹3,000 payment succeeded; ₹500 refund **PENDING**; customer asks again | `CHECK_EXISTING_REFUND` + `REFUND_ALREADY_PENDING` |
| F2 | ₹1,000 payment; refund outcome **UNKNOWN** after timeout | `CHECK_EXISTING_REFUND` + `REFUND_OUTCOME_UNKNOWN`, `missing_facts: [current_refund_outcome]` |
| F3 | Two ₹799 payments, no reference | UNMATCHED → candidates → `DISAMBIGUATE_PAYMENT` → merchant confirms |

Demo controls (owner/researcher): `outage_on/off`, `refund_f1_succeeds`, `delayed_pending_f1` — inject realistic provider failures live.

### Reproduced model metrics (honest numbers)

`python -m ml.reproduce` on the full 24,363-graph test set (518 positives), threshold 0.79 (locked on validation), CUDA:

| Precision | Recall | F1 | PR-AUC |
|---|---|---|---|
| 0.6988 | 0.4614 | **0.5558** | 0.5906 |

Original-domain Elliptic2 results only — **not** a merchant-fraud accuracy claim. Details: [`ml/model_card.md`](ml/model_card.md).

---

## Architecture

```text
React (Vite/TS) ── FastAPI ── SQLite (default) | Postgres (compose.yaml)
                      │
                      ├─ Mock provider adapter ── own pl_* ledger (provider's truth)
                      ├─ policy.py ── deterministic next action (no model in the loop)
                      ├─ export.py ── Markdown/JSON evidence + SHA-256
                      └─ ml/service.py ── GATv2 checkpoint inference (research only,
                                          abstains for merchant tasks)
```

- Money is integer paise, never floats. Roles are resolved server-side from memberships. Cross-tenant objects return 404 — existence is never leaked.
- Refunds have **no destination field** by construction: supported refunds return to the original payment source.
- Postgres path: `docker compose up -d db`, set `DATABASE_URL=postgresql+psycopg2://vyapaar:vyapaar@localhost:5432/vyapaar`, re-seed.

## Layout

```
services/api/app/       API: config, db, models, security, auth, ingest, policy, export, providers/, api/routes/
services/api/fixtures/  seed.py (synthetic world + 3 fixtures)
services/api/tests/     pytest suite (workflow + access + events + research)
ml/                     model.py, service.py, reproduce.py, model_card.md, artifacts/metrics.json
apps/web/               React + TypeScript + Vite frontend
docs/                   RUN_AND_DIAGNOSTICS, JUDGE_CHECKLIST(.md/.json)
compose.yaml            optional Postgres; SQLite is the default demo DB
```

## Submission honesty notes

- All external-integration behaviour is mocked and visibly labelled.
- Model scores are original-domain research output, persisted with dataset/checkpoint SHA-256 and abstention reasons.
- Known limits, cut scope (attachments, refund execution, Paytm staging) and future work: see `../VYAPAAR_KAVACH_PROJECT_DOCS.md` §10.

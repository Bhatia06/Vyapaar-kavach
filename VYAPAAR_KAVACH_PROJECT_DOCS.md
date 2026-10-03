# Vyapaar Kavach — Full Project Documentation & Explanation

**Mode:** `DEMO_LOCAL` (synthetic data · mock provider · no real funds).
**Repo root:** this directory. Application code lives under `vyapaar-kavach/` (original research assets stay at the root, untouched).
**Status date:** 3 October 2026. This document records **verified facts** — every behaviour listed as working has been executed and observed, not just designed.

---

## 1. What this project is

A merchant payment/refund **exception and evidence assistant** for a Paytm-style context. A small merchant receives a confusing customer claim ("my refund never arrived — send it again", "I paid but your system shows pending"). The app helps the merchant:

1. Match the claim to a real payment (explicitly — never auto-bind by amount alone).
2. See the **verified** payment/refund state, with source labels and freshness.
3. Get a deterministic **next action** with reason codes and missing facts.
4. Record notes, resolve the case as owner, and **export a Markdown/JSON evidence packet** with full provenance.

A research workspace additionally runs the team's existing **GATv2 "Smurf" engine** on its original domain (Elliptic2 Bitcoin subgraphs) with real checkpoint inference — clearly labelled as research output, never as a merchant fraud verdict.

Founding documents (context, unchanged): `TRISTACKOVERFLOW_VYAPAAR_KAVACH_BUILD_PLAN.md` (master plan) and `VYAPAAR_KAVACH_PROTOTYPE_PLAN_FOR_REVIEW.md` (condensed prototype scope).

---

## 2. Original assets (analysed, verified)

| Asset | Verified finding |
|---|---|
| `dataset1 (1).pt` (180 MB) | 121,810 Elliptic2 subgraphs; 119,047 licit / 2,763 suspicious (~2.3% positives); 43 node features; mean ~19 nodes. Loads locally. |
| `GAT_Model_Final (2).pt` (104 KB) | State dict of `SmurfDetector`: **stock PyG `GATv2Conv`** ×3 (43→16×4 heads → 64, BatchNorm, ReLU, dropout 0.4), mean+max pooling → Linear(128→2). No entmax/temperature parameters — the custom entmax layers in the .py files were **not** what trained this checkpoint. |
| `Smurf_trainer.ipynb`, `smurf-elliptic-rp.ipynb` | Kaggle pipeline: Elliptic2 load → feature analysis → scaler fit on train → training with class weights 0.51/7.56 → val threshold sweep. RP notebook adds GraphSAGE comparison + GNNExplainer. |
| `TG_GAT.py` / `entmax_gatv2conv.py` / `scatter_entmax.py` | Custom GATv2 with **entmax-1.5 sparse attention** + learnable per-head temperature (three implementation variants: loop, closed-form vectorized, bisection). Research track, not yet integrated with the shipped checkpoint. |
| `multi_seed_eval.py` | Multi-seed harness; imports a non-existent `AI.gatv2_conv` and `dataset_smurf.pt` as-is (was written for a different working directory layout). |

---

## 3. What has been built (`vyapaar-kavach/`)

```text
vyapaar-kavach/
  compose.yaml                  # optional Postgres (Docker); default demo is SQLite
  .env.example                  # all settings; no secrets needed for demo
  requirements.txt              # backend + test deps
  requirements-ml.txt           # pinned ML env (matches verified reproduction env)
  services/
    api/
      app/
        config.py               # env-driven settings (repo-root relative paths)
        db.py                   # engine/session (SQLite WAL + FK pragmas)
        security.py             # PBKDF2 hashing, opaque session tokens, id generation
        models.py               # ~18 tables incl. mock-provider ledger (pl_*)
        auth.py                 # Principal resolution; server-side role checks
        ingest.py               # provider refresh + event ingestion (dedup / no-regression / conflict)
        policy.py               # deterministic rule engine (exceptions.v1)
        export.py               # Markdown+JSON evidence packet + SHA-256 manifest
        main.py                 # FastAPI app wiring
        providers/mock.py       # mock provider adapter: capabilities, outage toggle
        api/routes/             # auth / payments / cases / exports / provider_events(demo controls) / research / health
      fixtures/seed.py          # synthetic dataset + 3 acceptance fixtures (--reset supported)
      artifacts/exports/        # generated evidence packets (gitignored)
    api/tests/                  # pytest suite (next milestone)
  ml/
    model.py                    # faithful SmurfDetector re-declaration + loader
    service.py                  # lazy inference service w/ artifact hashing
    reproduce.py                # full test-set evaluation -> ml/artifacts/metrics.json
    artifacts/metrics.json      # verified reproduction output
```

---

## 4. Architecture

```text
React (Vite, TS)  --->  FastAPI  --->  SQLite/Postgres
                             |          (app records: view of the world)
                             |
                     Mock provider adapter ---> pl_* ledger tables
                             (provider's OWN truth, separate on purpose)
                             |
                     policy.py (deterministic next action)
                             |
                     ml/service.py  ---> GATv2 checkpoint
                     (research runs only; abstains for merchant tasks)
```

Key boundaries, by construction:
- The mock provider keeps its own ledger (`pl_payments`, `pl_refunds`, `pl_settings`). The app's records are built **only via recorded observations** — mirroring a real integration and enabling honest reconciliation tests.
- Payment **status** and **verification** are separate fields: a payment can be `SUCCEEDED` but `STALE` when the provider is unreachable.
- There is **no destination field** anywhere in refunds: supported refunds return via the original payment source. A "please refund to account X" request is simply impossible to encode — that is the control.
- The ML model has no path to any financial action; research runs are recorded with artifact hashes and may abstain.

Roles (server-enforced): `staff` (view, claim, note), `owner` (+ resolve, export), `researcher` (+ research runs). Sessions are opaque HttpOnly-cookie tokens (also returned in the login body for API clients), with a 12 h TTL.

---

## 5. The three demo fixtures (seeded)

| # | Scenario | Data | Expected app behaviour | Verified |
|---|---|---|---|---|
| F1 | Delayed legitimate refund | ORD-3000-RAM: ₹3,000 SUCCEEDED; refund `REF-500-001` ₹500 **PENDING** | Track the existing refund: `CHECK_EXISTING_REFUND` + `REFUND_ALREADY_PENDING`; never suggest a second payout | ✅ |
| F2 | Repeat request after timeout | ORD-1000-KIRAN: ₹1,000 SUCCEEDED; refund `REF-1000-002` ₹1,000 **UNKNOWN** | Reconcile the existing reference: `CHECK_EXISTING_REFUND` + `REFUND_OUTCOME_UNKNOWN`; `missing_facts: [current_refund_outcome]`; no replacement | ✅ |
| F3 | Ambiguous payment claim | Two ₹799 payments (ORD-799-SALE-A/B), no customer reference | Stay UNMATCHED → list candidates with reasons → `DISAMBIGUATE_PAYMENT` + `MULTIPLE_PAYMENT_MATCHES` until the merchant confirms | ✅ |

Demo controls (owner/researcher, `POST /v1/demo/controls`): `outage_on` / `outage_off`, `refund_f1_succeeds` (ledger completes the refund + event notification), `delayed_pending_f1` (stale PENDING event on a SUCCEEDED payment — app preserves SUCCEEDED and flags `CONFLICTED`).

---

## 6. API surface (implemented)

`/v1/auth` login · logout · `/v1/me` — session + role resolution
`/v1/payments` — scoped search (`?q=` matches order ref, txn id, or rupee amount); detail (payment + refunds); `{id}/refresh` (re-pulls payment **and** refunds; HTTP 503 `PROVIDER_UNAVAILABLE` on outage, marking evidence `STALE`)
`/v1/cases` — create (exact reference auto-binds MATCHED; otherwise UNMATCHED), list, detail, `match-candidates`, `match` (explicit, scoped), `timeline`, `recommendation`, `notes`, `resolve` (owner-only, optimistic `case_version` guard → 409 `STALE_VERSION`)
`/v1/cases/{id}/exports` + `/v1/exports/{id}?format=md|json` — evidence packet with observations, notes, recommendation, limitations, SHA-256 digest
`/v1/provider-events/mock` — fingerprint-deduplicated event ingestion (duplicate → acknowledged, zero side-effects)
`/v1/demo/controls` — the four demo scenarios above (DEMO_LOCAL only)
`/v1/research/runs` — task `elliptic2_smurf_reproduction` runs **real** checkpoint inference on held-out Elliptic2 graphs; anything else abstains (`UNSUPPORTED_TASK`); artifacts missing → `MODEL_ARTIFACT_UNAVAILABLE`; exceptions → `INFERENCE_ERROR`. Never a fake score.
`/health/live`, `/health/ready`

Structured errors carry `{code, error, retryable}`. Inaccessible tenant objects return **404** (existence is not leaked).

---

## 7. ML engine reproduction — verified results

Command: `python -m ml.reproduce` (from `vyapaar-kavach/`). Protocol: exact 72/8/20 index split, StandardScaler fit on train only, threshold **0.79 locked on validation** (notebook comment says 0.77 in one place; the committed code value 0.79 is what we report).

**Reproduced on the full 24,363-graph test set (518 positives), CUDA device:**

| Metric | Value |
|---|---|
| Precision (suspicious) | 0.6988 |
| Recall (suspicious) | 0.4614 |
| **F1 (suspicious)** | **0.5558** |
| PR-AUC | 0.5906 |
| Confusion matrix | [[23742, 103], [279, 239]] |

Honest read: the previously *reported* "~0.60 F1" reproduces as **~0.56** at the locked threshold on the full test set — same protocol, full set (not a subset), single deterministic eval. This is an Elliptic2 Bitcoin-subgraph result; it says nothing about merchant UPI behaviour. Full details + hashes in `vyapaar-kavach/ml/artifacts/metrics.json` and `ml/model_card.md` (written with the final package).

---

## 8. End-to-end smoke results (executed 3 Oct)

- Login (owner@demo) → role `owner`, tenant `tnt_demo01` ✅
- F1 case → MATCHED, `CHECK_EXISTING_REFUND` / `REFUND_ALREADY_PENDING`, `execution_allowed: false` ✅
- F2 case → `REFUND_OUTCOME_UNKNOWN`, missing-fact list correct ✅
- F3 case → UNMATCHED → 2 candidates → explicit match → MATCHED ✅
- Note appended; timeline returns labelled entries (payment observation → note → …) ✅
- Export → Markdown contains `REF-500-001` + Limitations section; JSON sidecar written; SHA-256 recorded ✅
- Resolve (owner, version guard) → RESOLVED ✅
- `outage_on` → refresh returns 503 `PROVIDER_UNAVAILABLE`; `outage_off` → refresh 200 ✅
- Delayed PENDING event on SUCCEEDED payment → status preserved SUCCEEDED, verification `CONFLICTED` ✅

(Note: seeded `last_checked_at` timestamps age out of the 15-minute freshness window, so `PROVIDER_DATA_STALE` appears until a refresh — intended, it exercises the freshness UX.)

---

## 9. Honest capability matrix

| Claim | Reality |
|---|---|
| Merchant workflow, matching, recommendations, timeline, export | Real: persistence + rules + UI/API; durable across restarts |
| Payment provider | Mock adapter with its own ledger; no Paytm connectivity in this build |
| Money movement | None. `execution_allowed` is always false; handoff is a recorded hint, not a refund |
| GATv2 model | Real checkpoint, real inference, real reproduced metrics — on Elliptic2 only |
| Merchant-case ML scoring | Deliberately abstains — no validated transfer exists |
| Multi-tenant isolation, roles | Enforced server-side; cross-tenant objects return 404 |

---

## 10. Remaining work (priority order)

1. **pytest suite** (services/api/tests): 12 workflow tests + 1 real-inference test mapping directly onto the judge checklist.
2. **Frontend** (`apps/web`): Login, Home (search + open claims), NewClaim (+match candidates), CaseDetail (payment/refund cards, recommendation, timeline, notes, resolve, export), Research (run + history + abstention display). Banner "Synthetic data · Mock provider · No real funds" on every page.
3. **Docs**: `README.md` (quickstart), `docs/RUN_AND_DIAGNOSTICS.md`, `docs/judge_checklist.json` + `JUDGE_CHECKLIST.md` (claim → evidence → verification command, machine-parseable for an LLM judge).
4. Full verification run (pytest green, API boot, frontend build, demo walkthrough).
5. Stretch (only if time): entmax-attention comparison experiment notes, Postgres compose validation, `model_card.md` polish.

---

## 11. Quick start (current state)

```powershell
cd vyapaar-kavach
pip install -r requirements.txt
python -m services.api.fixtures.seed            # one-time seed (add --reset to wipe)
uvicorn services.api.app.main:app --port 8000   # API on http://127.0.0.1:8000
# ML reproduction (optional, needs torch/pyg):
python -m ml.reproduce                          # writes ml/artifacts/metrics.json
```

Accounts: `owner@demo/owner123` · `staff@demo/staff123` · `research@demo/research123`.

# Judge Checklist — Vyapaar Kavach

**For LLM judges:** the machine-parseable version of this checklist is
[`judge_checklist.json`](./judge_checklist.json). Each claim has an `id`,
`evidence_paths`, a runnable `verify_command`, the `expected_result`, and the
`test` that pins the behaviour. `[tests]` commands run from `vyapaar-kavach/`
and need no running server; `[server]` commands need the API up:

```powershell
cd vyapaar-kavach
python -m services.api.fixtures.seed --reset
uvicorn services.api.app.main:app --port 8000
```

Suite-wide verification: `python -m pytest services/api/tests -q`
(**13 passed** as of the submission build).

## Claims and evidence

| ID | Category | Claim | Verification | Verified by |
|---|---|---|---|---|
| JC-01 | authentication | Roles/tenancy resolved server-side; bad password → 401 | pytest | `test_login_and_me` |
| JC-02 | workflow | F1 → `CHECK_EXISTING_REFUND` + `REFUND_ALREADY_PENDING`, execution false | pytest | `test_fixture_f1_pending_refund_recommendation` |
| JC-03 | workflow | F2 → `REFUND_OUTCOME_UNKNOWN`, `current_refund_outcome` missing; no second payout suggested | pytest | `test_fixture_f2_unknown_refund_recommendation` |
| JC-04 | matching | F3 (two ₹799 payments) never auto-binds; candidates listed; `DISAMBIGUATE_PAYMENT` | pytest | `test_fixture_f3_ambiguous_amount` |
| JC-05 | matching | Explicit scoped match binding only | pytest | `test_match_is_explicit` |
| JC-06 | events | Outage → 503 `PROVIDER_UNAVAILABLE`, STALE marking, clean recovery | pytest | `test_payment_refresh_outage_marks_stale` |
| JC-07 | events | Duplicate event acknowledged, zero side effects | pytest | `test_duplicate_event_no_side_effects` |
| JC-08 | events | Delayed PENDING never regresses SUCCEEDED; conflict flagged + preserved | pytest | `test_delayed_pending_event_does_not_regress` |
| JC-09 | access | Cross-tenant objects return 404 (no existence leak) | pytest | `test_cross_tenant_denial` |
| JC-10 | access | Resolve is owner-only (403) + version guard (409 STALE_VERSION) | pytest | `test_staff_cannot_resolve` |
| JC-11 | export | Export traces to records, includes limitations, SHA-256 recorded | pytest | `test_export_traces_provenance` |
| JC-12 | honesty | Refunds have no destination field, by schema construction | inspect models | — |
| JC-13 | honesty | `execution_allowed` is always false; no refund-submission endpoint exists | inspect policy | asserted in JC-02 test |
| JC-14 | research | Runs perform real checkpoint inference with artifact hashes + metrics | pytest | `test_research_run_real_inference` |
| JC-15 | research | Unsupported tasks abstain (`UNSUPPORTED_TASK`), never fabricated scores | pytest | `test_research_abstains_on_bad_task` |
| JC-16 | research | Metrics honestly reproduced: F1 **0.5558**, PR-AUC **0.5906** @ locked 0.79 | `python -m ml.reproduce` | — |
| JC-17 | workflow | Records persist across server restarts | manual (steps in RUN_AND_DIAGNOSTICS) | — |
| JC-18 | honesty | Synthetic/mock labels on every screen and export | UI banner + export packet | JC-11 test |

## Known limitations & honest scope (cut for this prototype)

- No attachment uploads; no refund execution (reservation/outbox state machine
  is future work — today `execution_allowed` is always false).
- 3 workflow fixtures, not the full 30-scenario library from the master plan.
- No Paytm staging/production connectivity; provider integration is mocked.
- ML model scores original-domain Elliptic2 graphs only; merchant scoring
  abstains. Entmax custom-attention experiments in the repo root predate the
  shipped checkpoint and are not exercised by it.
- LLM judges should NOT treat "scores exist in the UI" as evidence of merchant
  fraud-detection capability — the evidence the product *does* claim is listed
  above and is verifiable end-to-end.

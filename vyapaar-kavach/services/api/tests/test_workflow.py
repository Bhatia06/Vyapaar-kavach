"""Workflow tests mapped 1:1 to the judge checklist (docs/judge_checklist.json).

Each test exercises a real, observable behaviour through the API (in-process
TestClient) on a freshly seeded world.
"""
from __future__ import annotations

from datetime import datetime, timezone

from services.api.app import models


def _make_case(client, **kw):
    r = client.post("/v1/cases", json=kw)
    assert r.status_code == 201, r.text
    return r.json()


def test_login_and_me(client):
    r = client.post("/v1/auth/login", json={"username": "owner@demo", "password": "owner123"})
    assert r.status_code == 200
    me = client.get("/v1/auth/me").json()
    assert me["role"] == "owner"
    assert me["tenant_id"] == "tnt_demo01"
    assert me["environment"] == "DEMO_LOCAL"

    bad = client.post("/v1/auth/login", json={"username": "owner@demo", "password": "nope"})
    assert bad.status_code == 401


def test_fixture_f1_pending_refund_recommendation(owner_client):
    case = _make_case(
        owner_client, claim_type="REFUND_NOT_RECEIVED",
        claimed_amount_paise=50000, reference="ORD-3000-RAM",
        note="Customer says refund not received",
    )
    assert case["match_status"] == "MATCHED"
    assert case["payment_id"] == "pay_mock_txn_3000_001"
    rec = owner_client.get(f"/v1/cases/{case['id']}/recommendation").json()
    assert rec["action"] == "CHECK_EXISTING_REFUND"
    assert "REFUND_ALREADY_PENDING" in rec["reason_codes"]
    assert rec["execution_allowed"] is False
    assert rec["model_used_for_action"] is False


def test_fixture_f2_unknown_refund_recommendation(owner_client):
    case = _make_case(
        owner_client, claim_type="REFUND_NOT_RECEIVED",
        claimed_amount_paise=100000, reference="ORD-1000-KIRAN",
        note="Please send again",
    )
    rec = owner_client.get(f"/v1/cases/{case['id']}/recommendation").json()
    assert rec["action"] == "CHECK_EXISTING_REFUND"
    assert "REFUND_OUTCOME_UNKNOWN" in rec["reason_codes"]
    assert "current_refund_outcome" in rec["missing_facts"]


def test_fixture_f3_ambiguous_amount(owner_client):
    case = _make_case(
        owner_client, claim_type="PAYMENT_NOT_REFLECTED",
        claimed_amount_paise=79900, note="Customer paid Rs 799?",
    )
    assert case["match_status"] == "UNMATCHED"
    assert case["payment_id"] is None
    cands = owner_client.get(f"/v1/cases/{case['id']}/match-candidates").json()
    ids = {c["payment_id"] for c in cands}
    assert {"pay_mock_txn_799_a", "pay_mock_txn_799_b"} <= ids
    rec = owner_client.get(f"/v1/cases/{case['id']}/recommendation").json()
    assert rec["action"] == "DISAMBIGUATE_PAYMENT"
    assert "MULTIPLE_PAYMENT_MATCHES" in rec["reason_codes"]


def test_match_is_explicit(owner_client):
    case = _make_case(
        owner_client, claim_type="PAYMENT_NOT_REFLECTED", claimed_amount_paise=79900,
    )
    r = owner_client.post(
        f"/v1/cases/{case['id']}/match", json={"payment_id": "pay_mock_txn_799_a"}
    )
    assert r.status_code == 200
    assert r.json()["match_status"] == "MATCHED"
    assert r.json()["payment_id"] == "pay_mock_txn_799_a"
    rec = owner_client.get(f"/v1/cases/{case['id']}/recommendation").json()
    assert "MULTIPLE_PAYMENT_MATCHES" not in rec["reason_codes"]


def test_payment_refresh_outage_marks_stale(owner_client):
    r = owner_client.post("/v1/demo/controls", json={"scenario": "outage_on"})
    assert r.status_code == 200
    try:
        resp = owner_client.post("/v1/payments/pay_mock_txn_3000_001/refresh")
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "PROVIDER_UNAVAILABLE"
        pay = owner_client.get("/v1/payments/pay_mock_txn_3000_001").json()
        assert pay["verification"] == "STALE"
        assert pay["status"] == "SUCCEEDED"
    finally:
        owner_client.post("/v1/demo/controls", json={"scenario": "outage_off"})
    resp = owner_client.post("/v1/payments/pay_mock_txn_3000_001/refresh")
    assert resp.status_code == 200
    pay = owner_client.get("/v1/payments/pay_mock_txn_3000_001").json()
    assert pay["verification"] == "VERIFIED"


def test_duplicate_event_no_side_effects(owner_client, db_session):
    payload = {
        "subject_type": "payment",
        "subject_ref": "MOCK-TXN-799-A",
        "status": "SUCCESS",
        "event_time": "2026-10-03T12:00:00+00:00",
    }
    r1 = owner_client.post("/v1/provider-events/mock", json=payload)
    assert r1.status_code == 200 and r1.json()["duplicate"] is False
    r2 = owner_client.post("/v1/provider-events/mock", json=payload)
    assert r2.status_code == 200 and r2.json()["duplicate"] is True

    events = (
        db_session.query(models.ProviderEvent)
        .filter(models.ProviderEvent.subject_ref == "MOCK-TXN-799-A")
        .all()
    )
    assert len(events) == 1


def test_delayed_pending_event_does_not_regress(owner_client, db_session):
    # Normalise current state first.
    owner_client.post("/v1/payments/pay_mock_txn_3000_001/refresh")
    assert owner_client.get("/v1/payments/pay_mock_txn_3000_001").json()["status"] == "SUCCEEDED"

    payload = {
        "subject_type": "payment",
        "subject_ref": "MOCK-TXN-3000-001",
        "status": "PENDING",
        "event_time": datetime.now(timezone.utc).isoformat(),
    }
    r = owner_client.post("/v1/provider-events/mock", json=payload)
    assert r.status_code == 200 and r.json()["accepted"] is True

    pay = owner_client.get("/v1/payments/pay_mock_txn_3000_001").json()
    assert pay["status"] == "SUCCEEDED"          # success never regresses
    assert pay["verification"] == "CONFLICTED"   # conflict made visible

    conflicted = (
        db_session.query(models.Observation)
        .filter(
            models.Observation.subject_key == "pay_mock_txn_3000_001",
            models.Observation.verification_status == "CONFLICTED",
        )
        .count()
    )
    assert conflicted >= 1


def test_cross_tenant_denial(owner_client, db_session):
    other = models.Tenant(id="tnt_other", name="Other Shop", environment="DEMO_LOCAL")
    db_session.add(other)
    db_session.flush()  # staged flush keeps FK ordering explicit
    db_session.add(models.Order(
        id="ord_other", tenant_id="tnt_other", environment="DEMO_LOCAL",
        order_ref="ORD-OTHER", amount_paise=100,
    ))
    db_session.flush()
    db_session.add(models.Payment(
        id="pay_other", tenant_id="tnt_other", environment="DEMO_LOCAL",
        order_id="ord_other", provider_txn_id="TXN-OTHER", amount_paise=100,
    ))
    db_session.commit()

    # 404 (not 403): existence must not leak across tenants.
    assert owner_client.get("/v1/payments/pay_other").status_code == 404


def test_staff_cannot_resolve(staff_client, owner_client):
    case = _make_case(
        staff_client, claim_type="REFUND_NOT_RECEIVED",
        claimed_amount_paise=50000, reference="ORD-3000-RAM",
    )
    denied = staff_client.post(
        f"/v1/cases/{case['id']}/resolve",
        json={"resolution": "staff attempt", "case_version": case["version"]},
    )
    assert denied.status_code == 403

    ok = owner_client.post(
        f"/v1/cases/{case['id']}/resolve",
        json={"resolution": "Explained pending refund REF-500-001.", "case_version": case["version"]},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "RESOLVED"

    stale = owner_client.post(
        f"/v1/cases/{case['id']}/resolve",
        json={"resolution": "again", "case_version": case["version"]},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "STALE_VERSION"


def test_export_traces_provenance(owner_client):
    case = _make_case(
        owner_client, claim_type="REFUND_NOT_RECEIVED",
        claimed_amount_paise=50000, reference="ORD-3000-RAM",
        note="Refund not received",
    )
    owner_client.post(f"/v1/cases/{case['id']}/notes", json={"text": "Customer called again."})
    exp = owner_client.post(f"/v1/cases/{case['id']}/exports").json()
    assert len(exp["sha256"]) == 64

    md = owner_client.get(f"/v1/exports/{exp['export_id']}?format=md").text
    assert "REF-500-001" in md
    assert "Limitations" in md

    js = owner_client.get(f"/v1/exports/{exp['export_id']}?format=json").json()
    assert any(o["source_kind"] == "provider_mock" for o in js["observations"])
    assert isinstance(js["limitations"], list) and js["limitations"]


def test_research_abstains_on_bad_task(research_client):
    r = research_client.post(
        "/v1/research/runs", json={"task": "merchant_case_scoring", "sample_size": 8}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["abstained"] is True
    assert body["abstention_reason"] == "UNSUPPORTED_TASK"

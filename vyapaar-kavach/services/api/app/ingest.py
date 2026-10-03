"""Ingestion & projection helpers.

Rules implemented here:

* Every fact entering the app becomes an ``Observation`` with provenance
  (source kind, verification status, timestamps) before any projection update.
* A confirmed SUCCEEDED payment never silently regresses when a delayed
  PENDING event arrives: the event is stored, the observation kept, and the
  payment's verification is marked CONFLICTED — humans reconcile, not order.
* Duplicate provider events (same canonical fingerprint) are acknowledged
  without repeating side effects.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from . import models
from .security import new_id
from .providers import mock as mock_provider

# Map provider raw statuses -> app payment statuses.
PAYMENT_STATUS_MAP = {"SUCCESS": "SUCCEEDED", "PENDING": "PENDING", "FAILED": "FAILED"}
REFUND_STATUS_MAP = {"PENDING": "PENDING", "SUCCEEDED": "SUCCEEDED", "FAILED": "FAILED", "UNKNOWN": "UNKNOWN"}

# Terminal states never regress due to a *later-discovered* pending event.
_TERMINAL_PAYMENT = {"SUCCEEDED", "FAILED"}


def fingerprint_event(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def record_observation(
    db,
    *,
    tenant_id: str,
    subject_type: str,
    subject_key: str,
    source_kind: str,
    verification_status: str,
    summary: dict,
    message: str,
    event_time: datetime | None = None,
    source_record_id: str | None = None,
) -> models.Observation:
    obs = models.Observation(
        id=new_id("obs"),
        tenant_id=tenant_id,
        environment="DEMO_LOCAL",
        subject_type=subject_type,
        subject_key=subject_key,
        source_kind=source_kind,
        verification_status=verification_status,
        summary_json=json.dumps(summary, default=str),
        message=message,
        event_time=event_time,
        observed_at=datetime.now(timezone.utc),
        source_record_id=source_record_id,
    )
    db.add(obs)
    db.flush()
    return obs


def refresh_payment_from_provider(db, payment: models.Payment) -> dict:
    """Pull the provider status for one payment and update the projection.

    Returns a result dict; records an observation either way. On provider
    outage the payment's last verified state is kept and marked STALE.
    """
    try:
        result = mock_provider.get_payment_status(db, payment.provider_txn_id)
    except mock_provider.ProviderUnavailable:
        payment.verification = "STALE"
        obs = record_observation(
            db,
            tenant_id=payment.tenant_id,
            subject_type="payment",
            subject_key=payment.id,
            source_kind="provider_mock",
            verification_status="STALE",
            summary={"provider": "mock", "provider_txn_id": payment.provider_txn_id, "error": "outage"},
            message="Provider unreachable; showing last verified state.",
        )
        db.commit()
        return {"ok": False, "code": "PROVIDER_UNAVAILABLE", "observation_id": obs.id}

    now = datetime.now(timezone.utc)
    mapped = PAYMENT_STATUS_MAP.get(result["status"], "UNKNOWN") if result["found"] else "NO_RECORD"
    conflict = mapped in ("PENDING", "UNKNOWN", "NO_RECORD") and payment.status in _TERMINAL_PAYMENT
    if not conflict:
        payment.status = mapped
    payment.verification = "CONFLICTED" if conflict else "VERIFIED"
    payment.last_checked_at = now
    obs = record_observation(
        db,
        tenant_id=payment.tenant_id,
        subject_type="payment",
        subject_key=payment.id,
        source_kind="provider_mock",
        verification_status=payment.verification,
        summary={
            "provider": "mock",
            "provider_txn_id": payment.provider_txn_id,
            "raw_status": result.get("status"),
            "mapped_status": payment.status,
        },
        message=(
            f"Provider reports payment {result['status']}."
            if result["found"]
            else "Provider has no record for this reference."
        ),
        event_time=now,
    )
    db.commit()
    return {
        "ok": True,
        "status": payment.status,
        "verification": payment.verification,
        "observation_id": obs.id,
    }


def refresh_refund_from_provider(db, refund: models.Refund) -> dict:
    """Pull provider status for one refund and update the projection."""
    try:
        result = mock_provider.get_refund_status(db, refund.refund_ref)
    except mock_provider.ProviderUnavailable:
        obs = record_observation(
            db,
            tenant_id=refund.tenant_id,
            subject_type="refund",
            subject_key=refund.refund_ref,
            source_kind="provider_mock",
            verification_status="STALE",
            summary={"provider": "mock", "refund_ref": refund.refund_ref, "error": "outage"},
            message="Provider unreachable; refund status could not be refreshed.",
        )
        db.commit()
        return {"ok": False, "code": "PROVIDER_UNAVAILABLE", "observation_id": obs.id}

    now = datetime.now(timezone.utc)
    if result["found"]:
        refund.status = REFUND_STATUS_MAP.get(result["status"], "UNKNOWN")
        refund.last_checked_at = now
    obs = record_observation(
        db,
        tenant_id=refund.tenant_id,
        subject_type="refund",
        subject_key=refund.refund_ref,
        source_kind="provider_mock",
        verification_status="VERIFIED" if result["found"] else "UNVERIFIED",
        summary={
            "provider": "mock",
            "refund_ref": refund.refund_ref,
            "raw_status": result.get("status"),
            "mapped_status": refund.status,
        },
        message=(
            f"Provider reports refund {result['status']} for reference {refund.refund_ref}."
            if result["found"]
            else "Provider has no record for this refund reference."
        ),
        event_time=now,
    )
    db.commit()
    return {"ok": True, "status": refund.status, "observation_id": obs.id}


def ingest_provider_event(db, tenant: models.Tenant, payload: dict) -> dict:
    """Validate, fingerprint and apply one inbound provider event.

    Duplicate deliveries are acknowledged with ``duplicate=True`` and have no
    side effects. Unknown subjects are rejected into a visible result (in a
    production build they would land in a quarantine table).
    """
    fp = fingerprint_event(payload)
    existing = db.query(models.ProviderEvent).filter(models.ProviderEvent.fingerprint == fp).first()
    if existing is not None:
        return {"accepted": True, "duplicate": True, "event_id": existing.id}

    subject_type = payload["subject_type"]
    subject_ref = payload["subject_ref"]
    status = payload["status"]
    event_time = datetime.fromisoformat(payload["event_time"])

    # Resolve the subject inside this tenant only; unknown subjects are NOT
    # applied to financial projections.
    if subject_type == "payment":
        subject = (
            db.query(models.Payment)
            .filter(models.Payment.tenant_id == tenant.id, models.Payment.provider_txn_id == subject_ref)
            .first()
        )
    else:
        subject = (
            db.query(models.Refund)
            .filter(models.Refund.tenant_id == tenant.id, models.Refund.refund_ref == subject_ref)
            .first()
        )

    event = models.ProviderEvent(
        id=new_id("evt"),
        tenant_id=tenant.id,
        provider="mock",
        fingerprint=fp,
        subject_type=subject_type,
        subject_ref=subject_ref,
        raw_json=json.dumps(payload, default=str),
        event_time=event_time,
        processing="ACCEPTED" if subject else "REJECTED_UNKNOWN_SUBJECT",
    )
    db.add(event)
    db.flush()

    if subject is None:
        db.commit()
        return {"accepted": False, "duplicate": False, "code": "UNKNOWN_SUBJECT", "event_id": event.id}

    if subject_type == "payment":
        mapped = PAYMENT_STATUS_MAP.get(status, "UNKNOWN")
        conflict = mapped in ("PENDING", "UNKNOWN") and subject.status in _TERMINAL_PAYMENT
        if not conflict:
            subject.status = mapped
            subject.verification = "VERIFIED"
        else:
            subject.verification = "CONFLICTED"  # observation preserved below
        subject.last_checked_at = datetime.now(timezone.utc)
        observation_message = (
            f"Provider event: payment {status}."
            + (" (Conflicts with a terminal state — flagged for reconciliation.)" if conflict else "")
        )
        obs = record_observation(
            db,
            tenant_id=tenant.id,
            subject_type="payment",
            subject_key=subject.id,
            source_kind="provider_mock",
            verification_status=subject.verification,
            summary={"provider": "mock", "raw_status": status, "event_time": payload["event_time"]},
            message=observation_message,
            event_time=event_time,
            source_record_id=event.id,
        )
    else:
        subject.status = REFUND_STATUS_MAP.get(status, "UNKNOWN")
        subject.last_checked_at = datetime.now(timezone.utc)
        obs = record_observation(
            db,
            tenant_id=tenant.id,
            subject_type="refund",
            subject_key=subject.refund_ref,
            source_kind="provider_mock",
            verification_status="VERIFIED",
            summary={"provider": "mock", "raw_status": status, "event_time": payload["event_time"]},
            message=f"Provider event: refund {status} for {subject.refund_ref}.",
            event_time=event_time,
            source_record_id=event.id,
        )

    try:
        db.commit()
    except IntegrityError:
        # Concurrent duplicate delivery — acknowledge cleanly.
        db.rollback()
        return {"accepted": True, "duplicate": True}
    return {"accepted": True, "duplicate": False, "event_id": event.id, "observation_id": obs.id}

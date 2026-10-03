"""Mock payment provider adapter.

The mock keeps its own ledger (``pl_*`` tables) — deliberately separate from
the app's operational tables, so the reconciliation behaviour looks like a
real external provider instead of the app reading its own writes.

Capabilities exposed by this adapter:
    payment_status_read   -> get_payment_status()
    refund_status_read    -> get_refund_status()
    events                -> build_status_event() (used by demo controls)
Unsupported capabilities (refund history listing, refund submission) are
reported explicitly — they never return a misleading empty history.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .. import models


CAPABILITIES = {
    "payment_status_read": True,
    "refund_status_read": True,
    "refund_history_complete": False,  # known limitation of the mock
    "verified_webhooks": False,        # mock events are synthetic-signed
    "refund_submit": False,            # no money moves in this build
    "partial_refund": False,
}


class ProviderUnavailable(Exception):
    """Raised when the simulated outage toggle is on."""


def _outage_on(db) -> bool:
    row = db.get(models.PlSetting, "outage")
    return row is not None and row.value.lower() == "true"


def set_outage(db, on: bool) -> None:
    row = db.get(models.PlSetting, "outage")
    if row is None:
        row = models.PlSetting(key="outage", value=str(on).lower())
        db.add(row)
    else:
        row.value = str(on).lower()
    db.commit()


def get_payment_status(db, provider_txn_id: str) -> dict[str, Any]:
    """Read the provider's view of one payment."""
    if _outage_on(db):
        raise ProviderUnavailable("provider outage simulated")
    rec = db.get(models.PlPayment, provider_txn_id)
    if rec is None:
        return {"found": False, "status": "NO_RECORD"}
    return {
        "found": True,
        "status": rec.status,
        "amount_paise": rec.amount_paise,
        "currency": rec.currency,
        "order_ref": rec.order_ref,
    }


def get_refund_status(db, refund_ref: str) -> dict[str, Any]:
    """Read the provider's view of one refund, by its reference."""
    if _outage_on(db):
        raise ProviderUnavailable("provider outage simulated")
    rec = db.get(models.PlRefund, refund_ref)
    if rec is None:
        return {"found": False, "status": "NO_RECORD"}
    return {
        "found": True,
        "status": rec.status,
        "amount_paise": rec.amount_paise,
        "currency": rec.currency,
        "provider_txn_id": rec.provider_txn_id,
    }


def mark_refund_succeeded(db, refund_ref: str) -> None:
    """Demo control: provider-side refund completes, then emits an event."""
    rec = db.get(models.PlRefund, refund_ref)
    rec.status = "SUCCEEDED"
    rec.updated_at = datetime.now(timezone.utc)
    db.commit()


def build_status_event(subject_type: str, subject_ref: str, status: str) -> dict[str, Any]:
    """Construct the raw webhook-ish payload the app would receive."""
    return {
        "subject_type": subject_type,
        "subject_ref": subject_ref,
        "status": status,
        "event_time": datetime.now(timezone.utc).isoformat(),
    }

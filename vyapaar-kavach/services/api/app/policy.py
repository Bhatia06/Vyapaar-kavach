"""Deterministic recommendation engine.

Every recommendation is produced by these versioned rules and carries
reason codes, the observation ids that support it, and the facts that are
still missing. There is deliberately no learned model call in this module —
models may *rank review* later, they never decide actions.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from . import models
from sqlalchemy.orm import Session

POLICY_VERSION = "exceptions.v1"
# Freshness window for the demo: provider evidence older than this is "stale"
# and the UI says so (a configurable test setting, not a provider SLA).
# 15 minutes keeps seeded demo cases fresh; a simulated outage still marks
# evidence STALE explicitly on refresh.
FRESHNESS_LIMIT = timedelta(minutes=15)

REASON_TEXT = {
    "CASE_UNMATCHED": "The claim is not linked to a verified payment yet.",
    "MULTIPLE_PAYMENT_MATCHES": "More than one payment matches these details. Confirm the right one before continuing.",
    "PAYMENT_NOT_VERIFIED": "We could not verify this payment yet. Check the reference and refresh its status.",
    "PROVIDER_DATA_STALE": "This is the last verified status; we could not refresh it just now.",
    "REFUND_ALREADY_PENDING": "A refund already exists for this payment and is pending. Track it before doing anything else.",
    "REFUND_OUTCOME_UNKNOWN": "A refund request exists but its outcome is not confirmed. Do not pay again; reconcile the existing reference.",
    "REFUND_SUCCEEDED": "The provider reports the refund as successful.",
    "ALTERNATE_DESTINATION_REQUESTED": "Supported refunds return to the original payment's source — never to a new account provided in a message.",
    "NO_SUPPORTING_PAYMENT": "No supporting verified payment exists for this claim.",
}


def _last_checked(payment: models.Payment | None):
    return payment.last_checked_at if payment else None


def evaluate_case(db: Session, case: models.Case) -> dict:
    """Return the recommendation contract for a case."""
    supporting: list[str] = []
    missing: list[str] = []
    reason_codes: list[str] = []
    action = "REVIEW_MANUALLY"
    summary = "Review this case manually."

    payment: models.Payment | None = (
        db.get(models.Payment, case.payment_id) if case.payment_id else None
    )
    last_checked = _last_checked(payment)
    stale = False
    if last_checked is not None:
        lc = last_checked if last_checked.tzinfo else last_checked.replace(tzinfo=timezone.utc)
        stale = (datetime.now(timezone.utc) - lc) > FRESHNESS_LIMIT

    # Latest payment observation recorded by the app (for support evidence).
    latest_payment_obs = None
    if payment is not None:
        latest_payment_obs = (
            db.query(models.Observation)
            .filter(
                models.Observation.subject_type == "payment",
                models.Observation.subject_key == payment.id,
            )
            .order_by(models.Observation.observed_at.desc())
            .first()
        )
    if latest_payment_obs is not None:
        supporting.append(latest_payment_obs.id)

    # --- matching state dominates --------------------------------------
    if case.match_status != "MATCHED" or payment is None:
        amount_candidates = 0
        if case.claimed_amount_paise:
            amount_candidates = (
                db.query(models.Payment)
                .filter(
                    models.Payment.tenant_id == case.tenant_id,
                    models.Payment.amount_paise == case.claimed_amount_paise,
                )
                .count()
            )
        if amount_candidates > 1:
            reason_codes = ["MULTIPLE_PAYMENT_MATCHES"]
            action = "DISAMBIGUATE_PAYMENT"
            summary = REASON_TEXT["MULTIPLE_PAYMENT_MATCHES"]
            missing = ["confirmed_order_reference"]
        else:
            reason_codes = ["CASE_UNMATCHED"]
            action = "REQUEST_REFERENCE"
            summary = REASON_TEXT["CASE_UNMATCHED"]
            missing = ["payment_reference"]
    else:
        # --- matched case: determine next action -------------------------
        refunds = (
            db.query(models.Refund)
            .filter(models.Refund.payment_id == payment.id)
            .order_by(models.Refund.created_at.asc())
            .all()
        )
        pending_unknown = [r for r in refunds if r.status in ("PENDING", "UNKNOWN")]
        succeeded = [r for r in refunds if r.status == "SUCCEEDED"]
        for r in refunds:
            ro = (
                db.query(models.Observation)
                .filter(
                    models.Observation.subject_type == "refund",
                    models.Observation.subject_key == r.refund_ref,
                )
                .order_by(models.Observation.observed_at.desc())
                .first()
            )
            if ro is not None:
                supporting.append(ro.id)

        if payment.status in ("UNKNOWN", "NO_RECORD", "PENDING"):
            reason_codes = ["PAYMENT_NOT_VERIFIED"]
            action = "REFRESH_PAYMENT"
            summary = REASON_TEXT["PAYMENT_NOT_VERIFIED"]
            missing = ["current_payment_status"]
        elif pending_unknown:
            has_pending = any(r.status == "PENDING" for r in pending_unknown)
            code = "REFUND_ALREADY_PENDING" if has_pending else "REFUND_OUTCOME_UNKNOWN"
            reason_codes = [code]
            action = "CHECK_EXISTING_REFUND"
            summary = REASON_TEXT[code]
            if not has_pending:
                missing = ["current_refund_outcome"]
        elif succeeded and case.claim_type == "REFUND_NOT_RECEIVED":
            reason_codes = ["REFUND_SUCCEEDED"]
            action = "COMMUNICATE_REFUND_STATUS"
            summary = (
                REASON_TEXT["REFUND_SUCCEEDED"]
                + f" Reference {succeeded[0].refund_ref} for Rs {succeeded[0].amount_paise/100:.0f} as last reported by the provider."
            )
        elif case.claim_type == "REFUND_NOT_RECEIVED" and not refunds:
            reason_codes = ["NO_REFUND_ON_RECORD"]
            action = "HANDOFF_SUPPORTED_REFUND"
            summary = "No refund exists for this payment in provider records. Use the merchant dashboard / provider-supported refund flow linked to the original transaction; record the handoff here."
            missing = ["refund_not_yet_initiated"]
        else:
            reason_codes = ["VERIFIED"]
            action = "RECORD_RESOLUTION"
            summary = "Payment is verified; follow your normal customer-service steps and record the outcome."

        if stale and payment.status not in ("UNKNOWN", "NO_RECORD", "PENDING"):
            reason_codes.append("PROVIDER_DATA_STALE")
            missing.append("fresh_provider_status")
        if payment.verification == "CONFLICTED":
            reason_codes.append("OBSERVATION_CONFLICT")
            summary += " Conflicting provider observations exist — reconcile before acting."

    return {
        "case_id": case.id,
        "policy_version": POLICY_VERSION,
        "action": action,
        "reason_codes": reason_codes,
        "summary": summary,
        "supporting_observation_ids": supporting,
        "missing_facts": missing,
        "provider_last_checked_at": payment.last_checked_at if payment else None,
        "model_used_for_action": False,
        "execution_allowed": False,  # read-only prototype: no in-app money movement
    }

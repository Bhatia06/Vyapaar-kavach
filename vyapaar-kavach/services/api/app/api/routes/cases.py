"""Case management: create, match, timeline, notes, recommendation, resolve."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from ... import ingest, models, policy
from ...auth import Principal, require_principal, require_role
from ...db import get_db
from ...schemas import (
    CLAIM_TYPES,
    CandidateOut,
    CaseCreateRequest,
    CaseOut,
    MatchRequest,
    NoteRequest,
    RecommendationOut,
    ResolveRequest,
    TimelineItem,
)
from ...security import new_id

router = APIRouter(prefix="/v1/cases", tags=["cases"])


def _get_scoped_case(db: OrmSession, principal: Principal, case_id: str) -> models.Case:
    case = db.get(models.Case, case_id)
    if case is None or case.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "error": "Case not found."})
    return case


@router.get("", response_model=list[CaseOut])
def list_cases(status: str = "", principal: Principal = Depends(require_principal), db: OrmSession = Depends(get_db)):
    q = db.query(models.Case).filter(models.Case.tenant_id == principal.tenant_id)
    if status:
        q = q.filter(models.Case.status == status)
    return [CaseOut.model_validate(c) for c in q.order_by(models.Case.created_at.desc()).all()]


@router.post("", response_model=CaseOut, status_code=201)
def create_case(body: CaseCreateRequest, principal: Principal = Depends(require_principal), db: OrmSession = Depends(get_db)):
    """Record a customer's claim.

    Exact reference (order ref or provider txn id) binds immediately with
    ``match_status=MATCHED`` and provenance recorded. Anything else stays
    UNMATCHED — amount and time alone never establish identity.
    """
    if body.claim_type not in CLAIM_TYPES:
        raise HTTPException(status_code=422, detail={"code": "BAD_CLAIM_TYPE", "error": f"claim_type must be one of {CLAIM_TYPES}"})

    case = models.Case(
        id=new_id("case"),
        tenant_id=principal.tenant_id,
        environment=principal.tenant.environment if hasattr(principal.tenant, "environment") else "DEMO_LOCAL",
        claim_type=body.claim_type,
        claimed_amount_paise=body.claimed_amount_paise,
        reference_text=body.reference.strip(),
        created_by=principal.user_id,
    )

    # Exact-reference binding (both order refs and provider txn ids).
    if case.reference_text:
        payment = (
            db.query(models.Payment)
            .join(models.Order, models.Payment.order_id == models.Order.id)
            .filter(
                models.Payment.tenant_id == principal.tenant_id,
                (models.Order.order_ref == case.reference_text)
                | (models.Payment.provider_txn_id == case.reference_text),
            )
            .first()
        )
        if payment is not None:
            case.payment_id = payment.id
            case.match_status = "MATCHED"

    db.add(case)
    db.flush()
    if body.note:
        db.add(
            models.CaseNote(
                id=new_id("note"),
                tenant_id=principal.tenant_id,
                case_id=case.id,
                author_user_id=principal.user_id,
                text=body.note,
            )
        )
    ingest.record_observation(
        db,
        tenant_id=principal.tenant_id,
        subject_type="case",
        subject_key=case.id,
        source_kind="merchant_statement",
        verification_status="UNVERIFIED",
        summary={"claim_type": case.claim_type, "claimed_amount_paise": case.claimed_amount_paise,
                 "reference": case.reference_text},
        message=f"Merchant recorded a {case.claim_type} claim.",
        source_record_id=case.id,
    )
    db.commit()
    return CaseOut.model_validate(case)


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: str, principal: Principal = Depends(require_principal), db: OrmSession = Depends(get_db)):
    return CaseOut.model_validate(_get_scoped_case(db, principal, case_id))


@router.get("/{case_id}/match-candidates", response_model=list[CandidateOut])
def match_candidates(case_id: str, principal: Principal = Depends(require_principal), db: OrmSession = Depends(get_db)):
    case = _get_scoped_case(db, principal, case_id)
    query = (
        db.query(models.Payment)
        .join(models.Order, models.Payment.order_id == models.Order.id)
        .filter(models.Payment.tenant_id == principal.tenant_id)
    )
    candidates = []
    if case.claimed_amount_paise:
        for p in query.filter(models.Payment.amount_paise == case.claimed_amount_paise).all():
            candidates.append(
                CandidateOut(
                    payment_id=p.id,
                    order_ref=p.order.order_ref,
                    provider_txn_id=p.provider_txn_id,
                    amount_paise=p.amount_paise,
                    currency=p.currency,
                    status=p.status,
                    created_at=p.created_at,
                    reason="Same amount as the customer's claim — confirm manually.",
                )
            )
    if case.reference_text:
        for p in query.filter(
            (models.Order.order_ref.ilike(f"%{case.reference_text}%"))
            | (models.Payment.provider_txn_id.ilike(f"%{case.reference_text}%"))
        ).all():
            if all(c.payment_id != p.id for c in candidates):
                candidates.append(
                    CandidateOut(
                        payment_id=p.id,
                        order_ref=p.order.order_ref,
                        provider_txn_id=p.provider_txn_id,
                        amount_paise=p.amount_paise,
                        currency=p.currency,
                        status=p.status,
                        created_at=p.created_at,
                        reason="Matches part of the reference the customer supplied.",
                    )
                )
    return candidates


@router.post("/{case_id}/match", response_model=CaseOut)
def match_case(case_id: str, body: MatchRequest, principal: Principal = Depends(require_principal), db: OrmSession = Depends(get_db)):
    """Explicitly bind (or re-bind) a case to a payment. Server checks scope."""
    case = _get_scoped_case(db, principal, case_id)
    payment = db.get(models.Payment, body.payment_id)
    if payment is None or payment.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "error": "Payment not found."})
    case.payment_id = payment.id
    case.match_status = "MATCHED"
    case.version += 1
    ingest.record_observation(
        db,
        tenant_id=principal.tenant_id,
        subject_type="case",
        subject_key=case.id,
        source_kind="system_derived",
        verification_status="VERIFIED",
        summary={"payment_id": payment.id, "matched_by": principal.user_id},
        message=f"{principal.user.display_name} confirmed the match to payment {payment.provider_txn_id}.",
        source_record_id=case.id,
    )
    db.commit()
    return CaseOut.model_validate(case)


@router.get("/{case_id}/timeline", response_model=list[TimelineItem])
def case_timeline(case_id: str, principal: Principal = Depends(require_principal), db: OrmSession = Depends(get_db)):
    """Evidence timeline: observations, notes and key case events, labelled."""
    case = _get_scoped_case(db, principal, case_id)
    keys = [case.id]
    if case.payment_id:
        keys.append(case.payment_id)
        keys.extend(
            r.refund_ref
            for r in db.query(models.Refund).filter(models.Refund.payment_id == case.payment_id).all()
        )
    observations = (
        db.query(models.Observation)
        .filter(models.Observation.subject_key.in_(keys))
        .order_by(models.Observation.observed_at.asc())
        .all()
    )
    notes = (
        db.query(models.CaseNote)
        .filter(models.CaseNote.case_id == case.id)
        .order_by(models.CaseNote.created_at.asc())
        .all()
    )
    items = [
        TimelineItem(
            at=o.observed_at,
            kind="observation",
            source_kind=o.source_kind,
            label=f"{o.subject_type} observation",
            detail=o.message,
            verification_status=o.verification_status,
        )
        for o in observations
    ] + [
        TimelineItem(
            at=n.created_at,
            kind="note",
            source_kind="merchant_statement",
            label=f"Note by {n.author.display_name}",
            detail=n.text,
            verification_status=None,
        )
        for n in notes
    ]
    items.sort(key=lambda i: i.at)
    return items


@router.get("/{case_id}/recommendation", response_model=RecommendationOut)
def case_recommendation(case_id: str, principal: Principal = Depends(require_principal), db: OrmSession = Depends(get_db)):
    case = _get_scoped_case(db, principal, case_id)
    return RecommendationOut(**policy.evaluate_case(db, case))


@router.post("/{case_id}/notes", status_code=201)
def add_note(case_id: str, body: NoteRequest, principal: Principal = Depends(require_principal), db: OrmSession = Depends(get_db)):
    case = _get_scoped_case(db, principal, case_id)
    note = models.CaseNote(
        id=new_id("note"),
        tenant_id=principal.tenant_id,
        case_id=case.id,
        author_user_id=principal.user_id,
        text=body.text,
    )
    db.add(note)
    db.commit()
    return {"id": note.id}


@router.post("/{case_id}/resolve", response_model=CaseOut)
def resolve_case(case_id: str, body: ResolveRequest, principal: Principal = Depends(require_role("owner")), db: OrmSession = Depends(get_db)):
    """Record a resolution (owner-only). Case version guards stale writes."""
    case = _get_scoped_case(db, principal, case_id)
    if body.case_version != case.version:
        raise HTTPException(
            status_code=409,
            detail={"code": "STALE_VERSION", "error": "The case changed since you loaded it. Refresh and try again."},
        )
    case.status = "RESOLVED"
    case.resolution_text = body.resolution
    case.resolved_by = principal.user_id
    case.resolved_at = datetime.now(timezone.utc)
    case.version += 1
    ingest.record_observation(
        db,
        tenant_id=principal.tenant_id,
        subject_type="case",
        subject_key=case.id,
        source_kind="system_derived",
        verification_status="VERIFIED",
        summary={"resolution": body.resolution},
        message=f"Case resolved by {principal.user.display_name} (owner): {body.resolution}",
        source_record_id=case.id,
    )
    db.commit()
    return CaseOut.model_validate(case)

"""Payment lookup, detail, and status refresh."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session as OrmSession

from ... import ingest, models
from ...auth import Principal, require_principal
from ...db import get_db
from ...schemas import PaymentDetail, PaymentSummary, RefundOut

router = APIRouter(prefix="/v1/payments", tags=["payments"])


def _to_summary(p: models.Payment) -> PaymentSummary:
    return PaymentSummary(
        id=p.id,
        order_ref=p.order.order_ref,
        provider_txn_id=p.provider_txn_id,
        amount_paise=p.amount_paise,
        currency=p.currency,
        status=p.status,
        verification=p.verification,
        last_checked_at=p.last_checked_at,
        customer_hint=p.order.customer_hint,
    )


@router.get("", response_model=list[PaymentSummary])
def search_payments(
    q: str = Query(default="", description="Order ref / provider txn id / amount in rupees"),
    principal: Principal = Depends(require_principal),
    db: OrmSession = Depends(get_db),
):
    """Tenant-scoped payment search. Amount-only matches still require the
    merchant to disambiguate — search never binds a claim by itself."""
    query = (
        db.query(models.Payment)
        .join(models.Order, models.Payment.order_id == models.Order.id)
        .filter(models.Payment.tenant_id == principal.tenant_id)
    )
    if q:
        like = f"%{q}%"
        conds = [models.Order.order_ref.ilike(like), models.Payment.provider_txn_id.ilike(like)]
        # Allow plain amount search like "799" (rupees) -> paise.
        if q.isdigit():
            conds.append(models.Payment.amount_paise == int(q) * 100)
        query = query.filter(or_(*conds))
    payments = query.order_by(models.Payment.created_at.desc()).limit(50).all()
    return [_to_summary(p) for p in payments]


@router.get("/{payment_id}", response_model=PaymentDetail)
def get_payment(payment_id: str, principal: Principal = Depends(require_principal), db: OrmSession = Depends(get_db)):
    payment = db.get(models.Payment, payment_id)
    # Inaccessible objects must not reveal their existence -> 404, not 403.
    if payment is None or payment.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "error": "Payment not found."})

    refunds = (
        db.query(models.Refund)
        .filter(models.Refund.payment_id == payment.id)
        .order_by(models.Refund.created_at.asc())
        .all()
    )
    base = _to_summary(payment)
    return PaymentDetail(
        **base.model_dump(),
        refunds=[RefundOut.model_validate(r) for r in refunds],
    )


@router.post("/{payment_id}/refresh")
def refresh_payment(payment_id: str, principal: Principal = Depends(require_principal), db: OrmSession = Depends(get_db)):
    """Re-query the mock provider for this payment AND its known refunds."""
    payment = db.get(models.Payment, payment_id)
    if payment is None or payment.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "error": "Payment not found."})

    result = ingest.refresh_payment_from_provider(db, payment)
    refunds = db.query(models.Refund).filter(models.Refund.payment_id == payment.id).all()
    refund_results = [ingest.refresh_refund_from_provider(db, r) for r in refunds]
    status_code = 503 if not result["ok"] else 200
    if status_code != 200:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "PROVIDER_UNAVAILABLE",
                "error": "Provider is unreachable; the last verified state is still shown.",
                "retryable": True,
            },
        )
    return {"payment": result, "refunds": refund_results}

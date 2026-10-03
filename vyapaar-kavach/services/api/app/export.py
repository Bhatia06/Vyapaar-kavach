"""Evidence export generation (Markdown + JSON).

Every exported fact traces back to stored records: observations carry
source labels and timestamps, and a SHA-256 manifest is written alongside
each export to detect *subsequent* modification. (Hashing detects later
edits to the file; it does not authenticate the original documents.)
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session as OrmSession

from . import models, policy
from .config import settings
from .security import new_id


def _inr(paise: int | None) -> str:
    return "n/a" if paise is None else f"Rs {paise / 100:,.2f}"


def build_export(db: OrmSession, case: models.Case, actor: models.User) -> models.Export:
    """Generate the evidence packet for a case and persist its manifest."""
    payment = db.get(models.Payment, case.payment_id) if case.payment_id else None
    order = db.get(models.Order, payment.order_id) if payment else None
    refunds = (
        db.query(models.Refund).filter(models.Refund.payment_id == payment.id).all()
        if payment
        else []
    )
    observations = (
        db.query(models.Observation)
        .filter(
            models.Observation.tenant_id == case.tenant_id,
            models.Observation.subject_key.in_(
                [payment.id] + [r.refund_ref for r in refunds] if payment else [case.id]
            ),
        )
        .order_by(models.Observation.observed_at.asc())
        .all()
    )
    notes = (
        db.query(models.CaseNote)
        .filter(models.CaseNote.case_id == case.id)
        .order_by(models.CaseNote.created_at.asc())
        .all()
    )
    recommendation = policy.evaluate_case(db, case)

    packet = {
        "export": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": case.environment,
            "schema_version": "case-export.v1",
        },
        "case": {
            "id": case.id,
            "claim_type": case.claim_type,
            "claimed_amount": _inr(case.claimed_amount_paise),
            "reference_given": case.reference_text,
            "status": case.status,
            "match_status": case.match_status,
            "created_at": case.created_at.isoformat(),
            "resolution": case.resolution_text,
        },
        "payment": None
        if payment is None
        else {
            "order_ref": order.order_ref if order else None,
            "provider_txn_id": payment.provider_txn_id,
            "amount": _inr(payment.amount_paise),
            "status": payment.status,
            "verification": payment.verification,
            "last_checked_at": payment.last_checked_at.isoformat() if payment.last_checked_at else None,
        },
        "refunds": [
            {
                "refund_ref": r.refund_ref,
                "amount": _inr(r.amount_paise),
                "status": r.status,
                "origin": r.origin,
                "last_checked_at": r.last_checked_at.isoformat() if r.last_checked_at else None,
            }
            for r in refunds
        ],
        "observations": [
            {
                "id": o.id,
                "subject": f"{o.subject_type}:{o.subject_key}",
                "source_kind": o.source_kind,
                "verification_status": o.verification_status,
                "message": o.message,
                "event_time": o.event_time.isoformat() if o.event_time else None,
                "observed_at": o.observed_at.isoformat(),
            }
            for o in observations
        ],
        "notes": [
            {"author": n.author.display_name, "at": n.created_at.isoformat(), "text": n.text}
            for n in notes
        ],
        "recommendation": recommendation,
        "limitations": [
            "Synthetic/demo data with a mock payment provider; no real funds are involved.",
            "This packet organises available evidence; it is not a legal determination, "
            "does not prove innocence or fault, and does not guarantee payment finality.",
            "A file hash detects later modification of this export only.",
        ],
    }

    md = _to_markdown(packet)
    out_dir = settings.resolved(settings.EXPORTS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    export_id = new_id("exp")
    path = out_dir / f"{export_id}.md"
    path.write_text(md, encoding="utf-8")
    (out_dir / f"{export_id}.json").write_text(json.dumps(packet, indent=2), encoding="utf-8")
    digest = hashlib.sha256(md.encode()).hexdigest()

    record = models.Export(
        id=export_id,
        tenant_id=case.tenant_id,
        case_id=case.id,
        created_by=actor.id,
        storage_path=str(path),
        sha256=digest,
    )
    db.add(record)
    db.commit()
    return record


def _to_markdown(packet: dict) -> str:
    e = packet["export"]
    c = packet["case"]
    p = packet["payment"]
    lines = [
        "# Vyapaar Kavach — case evidence summary",
        "",
        "> Synthetic demo data · mock payment provider · no real funds involved.",
        "",
        f"Generated: {e['generated_at']} · Environment: {e['environment']} · Schema: {e['schema_version']}",
        "",
        "## Case",
        f"- ID: {c['id']}",
        f"- Claim: {c['claim_type']} · Amount claimed: {c['claimed_amount']} · Status: {c['status']} / {c['match_status']}",
        f"- Customer reference given: {c['reference_given'] or 'none'}",
        f"- Created: {c['created_at']}",
    ]
    if c["resolution"]:
        lines.append(f"- Resolution: {c['resolution']}")
    lines.append("")
    lines.append("## Payment")
    if p is None:
        lines.append("- No payment has been definitively matched to this claim.")
    else:
        lines += [
            f"- Order: {p['order_ref']} · Provider txn: {p['provider_txn_id']}",
            f"- Amount: {p['amount']} · Status: {p['status']} · Verification: {p['verification']}",
            f"- Last provider check: {p['last_checked_at']}",
        ]
    lines.append("")
    lines.append("## Refunds")
    if not packet["refunds"]:
        lines.append("- None on record.")
    else:
        for r in packet["refunds"]:
            lines.append(
                f"- {r['refund_ref']}: {r['amount']} — {r['status']} (origin {r['origin']}, checked {r['last_checked_at']})"
            )
    lines.append("")
    lines.append("## Evidence timeline (observations)")
    for o in packet["observations"]:
        lines.append(
            f"- [{o['observed_at']}] ({o['source_kind']}, {o['verification_status']}) {o['message']}"
        )
    if not packet["observations"]:
        lines.append("- No observations recorded.")
    lines.append("")
    lines.append("## Merchant notes")
    for n in packet["notes"]:
        lines.append(f"- [{n['at']}] {n['author']}: {n['text']}")
    if not packet["notes"]:
        lines.append("- None.")
    lines.append("")
    r = packet["recommendation"]
    lines += [
        "## Recommendation (deterministic policy)",
        f"- Action: {r['action']} · Policy: {r['policy_version']}",
        f"- Reasons: {', '.join(r['reason_codes']) if r['reason_codes'] else '—'}",
        f"- Summary: {r['summary']}",
        f"- Missing facts: {', '.join(r['missing_facts']) if r['missing_facts'] else '—'}",
        f"- Model used for action: {r['model_used_for_action']}",
        "",
        "## Limitations",
    ]
    lines += [f"- {x}" for x in packet["limitations"]]
    lines.append("")
    return "\n".join(lines)

"""Provider-channel event ingestion plus demo-only control scenarios.

`POST /v1/provider-events/mock` simulates the authenticated provider channel:
payloads are validated and fingerprint-deduplicated before being applied.

`POST /v1/demo/controls` is available **only** in DEMO_LOCAL and tweaks the
mock provider's own ledger (outage toggle, refund completion, delayed event
injection) so the demo can drive realistic failure scenarios.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from ... import ingest, models
from ...auth import Principal, require_principal, require_role
from ...db import get_db
from ...providers import mock as mock_provider

router = APIRouter(tags=["provider"])


class EventIn(BaseModel):
    subject_type: str   # payment | refund
    subject_ref: str    # provider_txn_id | refund_ref
    status: str         # raw provider status
    event_time: str     # ISO-8601


@router.post("/v1/provider-events/mock")
def receive_mock_event(body: EventIn, principal: Principal = Depends(require_principal), db: OrmSession = Depends(get_db)):
    """Ingest one provider event. In a real deployment this route would sit on
    a provider-authenticated channel, not the browser session."""
    payload = {
        "subject_type": body.subject_type,
        "subject_ref": body.subject_ref,
        "status": body.status,
        "event_time": body.event_time,
    }
    try:
        return ingest.ingest_provider_event(db, principal.tenant, payload)
    except (KeyError, ValueError):
        raise HTTPException(status_code=422, detail={"code": "BAD_EVENT", "error": "Event schema is invalid."})


class DemoControlIn(BaseModel):
    scenario: str  # outage_on | outage_off | refund_f1_succeeds | delayed_pending_f1


@router.post("/v1/demo/controls")
def demo_controls(body: DemoControlIn, principal: Principal = Depends(require_role("owner", "researcher")), db: OrmSession = Depends(get_db)):
    """Drive the demo failure scenarios by mutating the mock provider state."""
    if principal.tenant.environment != "DEMO_LOCAL":
        raise HTTPException(status_code=403, detail={"code": "DEMO_ONLY", "error": "Demo controls exist only in DEMO_LOCAL."})

    if body.scenario == "outage_on":
        mock_provider.set_outage(db, True)
        return {"ok": True, "effect": "provider outage is ON; refresh attempts will fail visibly"}
    if body.scenario == "outage_off":
        mock_provider.set_outage(db, False)
        return {"ok": True, "effect": "provider outage is OFF"}
    if body.scenario == "refund_f1_succeeds":
        # Provider-side ledger update + notification event, like the real flow.
        mock_provider.mark_refund_succeeded(db, "REF-500-001")
        payload = mock_provider.build_status_event("refund", "REF-500-001", "SUCCEEDED")
        result = ingest.ingest_provider_event(db, principal.tenant, payload)
        return {"ok": True, "effect": "existing Rs 500 refund reported succeeded", "event": result}
    if body.scenario == "delayed_pending_f1":
        # A stale PENDING notification for an already-successful payment:
        # the app must keep SUCCEEDED and flag a conflict instead of regressing.
        payload = mock_provider.build_status_event("payment", "MOCK-TXN-3000-001", "PENDING")
        result = ingest.ingest_provider_event(db, principal.tenant, payload)
        return {"ok": True, "effect": "delayed PENDING event delivered; success must not regress", "event": result}
    raise HTTPException(status_code=422, detail={"code": "BAD_SCENARIO", "error": f"Unknown scenario '{body.scenario}'."})

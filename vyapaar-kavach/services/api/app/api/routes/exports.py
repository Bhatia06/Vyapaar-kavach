"""Evidence export generation and download (owner + researcher allowed)."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session as OrmSession

from ... import export as export_mod
from ... import models
from ...auth import Principal, require_role
from ...db import get_db

router = APIRouter(tags=["exports"])


@router.post("/v1/cases/{case_id}/exports")
def create_export(case_id: str, principal: Principal = Depends(require_role("owner", "researcher")), db: OrmSession = Depends(get_db)):
    case = db.get(models.Case, case_id)
    if case is None or case.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "error": "Case not found."})
    record = export_mod.build_export(db, case, principal.user)
    return {"export_id": record.id, "sha256": record.sha256}


@router.get("/v1/exports/{export_id}")
def get_export(export_id: str, format: str = "md", principal: Principal = Depends(require_role("owner", "researcher", "staff")), db: OrmSession = Depends(get_db)):
    record = db.get(models.Export, export_id)
    if record is None or record.tenant_id != principal.tenant_id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "error": "Export not found."})
    suffix = ".json" if format == "json" else ".md"
    path = Path(record.storage_path).with_suffix(suffix)
    if not path.exists():
        raise HTTPException(status_code=410, detail={"code": "EXPORT_MISSING", "error": "Export file is no longer available."})
    media = "application/json" if format == "json" else "text/markdown"
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type=media)

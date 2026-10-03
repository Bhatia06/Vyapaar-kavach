"""Research workspace: run the *real* GATv2 engine on its original domain.

Two honest behaviours are deliberately enforced:
  * Task ``elliptic2_smurf_reproduction`` runs actual checkpoint inference on
    held-out Elliptic2 subgraphs and persists full provenance (artifact hashes).
  * Any other task (e.g. scoring merchant cases) abstains with an explicit
    reason — the label space does not transfer, and we say so.
"""
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as OrmSession

from ... import models
from ...auth import Principal, require_role
from ...db import get_db
from ...schemas import ResearchRunRequest
from ...security import new_id
from ...config import settings

router = APIRouter(prefix="/v1/research", tags=["research"])

SUPPORTED_TASK = "elliptic2_smurf_reproduction"


def _record_run(db: OrmSession, principal: Principal, task: str, summary: dict, abstained: bool, reason: str | None, runtime_ms: int, hashes: dict | None) -> models.ResearchRun:
    run = models.ResearchRun(
        id=new_id("run"),
        task=task,
        data_mode="ORIGINAL_DOMAIN_RESEARCH",
        model_version=summary.get("model_version", "gatv2-smurf-elliptic2-v1"),
        checkpoint_sha256=(hashes or {}).get("checkpoint_sha256"),
        dataset_sha256=(hashes or {}).get("dataset_sha256"),
        abstained=abstained,
        abstention_reason=reason,
        summary_json=json.dumps(summary, default=str),
        runtime_ms=runtime_ms,
        created_by=principal.user_id,
    )
    db.add(run)
    db.commit()
    return run


@router.post("/runs")
def create_run(body: ResearchRunRequest, principal: Principal = Depends(require_role("owner", "researcher")), db: OrmSession = Depends(get_db)):
    if body.task != SUPPORTED_TASK:
        run = _record_run(
            db, principal, body.task,
            {"detail": "Task not supported by the registered engine."},
            abstained=True,
            reason="UNSUPPORTED_TASK",
            runtime_ms=0,
            hashes=None,
        )
        return _run_out(run)

    dataset = settings.resolved(settings.ML_DATASET_PATH)
    checkpoint = settings.resolved(settings.ML_CHECKPOINT_PATH)
    if not dataset.exists() or not checkpoint.exists():
        run = _record_run(
            db, principal, body.task,
            {"missing": [str(p) for p in (dataset, checkpoint) if not p.exists()]},
            abstained=True,
            reason="MODEL_ARTIFACT_UNAVAILABLE",
            runtime_ms=0,
            hashes=None,
        )
        return _run_out(run)

    started = time.perf_counter()
    try:
        from ml import service as ml_service

        result = ml_service.run_inference(dataset, checkpoint, body.sample_size)
    except Exception as exc:  # never fake a score; abstain with the true reason
        run = _record_run(
            db, principal, body.task,
            {"exception": type(exc).__name__, "message": str(exc)},
            abstained=True,
            reason="INFERENCE_ERROR",
            runtime_ms=int((time.perf_counter() - started) * 1000),
            hashes=None,
        )
        return _run_out(run)

    summary = {
        "model_version": ml_service.MODEL_VERSION,
        **{k: result[k] for k in ("threshold", "sample_size", "positives", "metrics", "device", "runtime_ms")},
        "examples": result["entries"][:10],
        "note": "Scores are original-domain (Elliptic2 Bitcoin subgraph) research output, not merchant verdicts.",
    }
    run = _record_run(
        db, principal, body.task, summary,
        abstained=False, reason=None,
        runtime_ms=result["runtime_ms"],
        hashes=result["hashes"],
    )
    return _run_out(run)


@router.get("/runs")
def list_runs(principal: Principal = Depends(require_role("owner", "researcher", "staff")), db: OrmSession = Depends(get_db)):
    runs = db.query(models.ResearchRun).order_by(models.ResearchRun.created_at.desc()).limit(50).all()
    return [_run_out(r) for r in runs]


@router.get("/runs/{run_id}")
def get_run(run_id: str, principal: Principal = Depends(require_role("owner", "researcher", "staff")), db: OrmSession = Depends(get_db)):
    run = db.get(models.ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "error": "Run not found."})
    return _run_out(run, full=True)


def _run_out(run: models.ResearchRun, full: bool = False) -> dict:
    out = {
        "id": run.id,
        "task": run.task,
        "data_mode": run.data_mode,
        "model_version": run.model_version,
        "abstained": run.abstained,
        "abstention_reason": run.abstention_reason,
        "runtime_ms": run.runtime_ms,
        "created_at": run.created_at.isoformat(),
        "checkpoint_sha256": run.checkpoint_sha256,
        "dataset_sha256": run.dataset_sha256,
    }
    if full or not run.abstained:
        out["summary"] = json.loads(run.summary_json)
    return out

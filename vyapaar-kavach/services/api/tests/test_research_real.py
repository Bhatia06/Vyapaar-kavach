"""Real-inference research test: runs the actual GATv2 checkpoint on the
Elliptic2 dataset. Skipped only when the artifacts are genuinely absent —
never faked.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DATASET = (REPO_ROOT / ".." / "dataset1 (1).pt").resolve()
CHECKPOINT = (REPO_ROOT / ".." / "GAT_Model_Final (2).pt").resolve()

ARTIFACTS_PRESENT = DATASET.exists() and CHECKPOINT.exists()


@pytest.mark.skipif(not ARTIFACTS_PRESENT, reason="model artifacts not present")
def test_research_run_real_inference(research_client):
    r = research_client.post(
        "/v1/research/runs",
        json={"task": "elliptic2_smurf_reproduction", "sample_size": 32},
        timeout=180,
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["abstained"] is False
    assert body["data_mode"] == "ORIGINAL_DOMAIN_RESEARCH"
    assert re.fullmatch(r"[0-9a-f]{64}", body["checkpoint_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", body["dataset_sha256"])

    summary = body["summary"]
    assert summary["sample_size"] == 32
    assert len(summary["examples"]) == 10
    metrics = summary["metrics"]
    for key in ("precision", "recall", "f1"):
        assert 0.0 <= metrics[key] <= 1.0
    # The reproduced test-set F1 is 0.5558; a 32-graph sample can vary widely,
    # so we assert only structure here, not the point estimate.
    assert body["runtime_ms"] > 0

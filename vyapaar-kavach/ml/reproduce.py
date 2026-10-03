"""Reproduction script for the original-domain GATv2 engine.

Run from the repo root:

    python -m ml.reproduce

It loads the saved checkpoint and dataset, rebuilds the exact 72/8/20 index
split used in the research notebook, re-fits the scaler on the train portion
and evaluates the FULL held-out test set at the validation-locked threshold
(0.79). Output metrics land in ``ml/artifacts/metrics.json`` and are the
numbers we are allowed to cite.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.preprocessing import StandardScaler
from torch_geometric.loader import DataLoader

from ml.model import load_model
from ml.service import (
    LOCKED_THRESHOLD,
    MODEL_VERSION,
    load_dataset,
    sha256_file,
    split_bounds,
)


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    dataset_path = (repo / "../dataset1 (1).pt").resolve()
    checkpoint_path = (repo / "../GAT_Model_Final (2).pt").resolve()
    if not dataset_path.exists() or not checkpoint_path.exists():
        print(f"missing artifacts: {dataset_path} or {checkpoint_path}")
        return 1

    t0 = time.perf_counter()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device          : {device}")
    print(f"dataset         : {dataset_path.name}")
    print(f"checkpoint      : {checkpoint_path.name}")

    data = load_dataset(dataset_path)
    train_s, val_s, test_s = split_bounds(len(data))
    train, val, test = data[train_s], data[val_s], data[test_s]
    print(f"total graphs    : {len(data)}  train/val/test = {len(train)}/{len(val)}/{len(test)}")

    scaler = StandardScaler().fit(torch.cat([d.x for d in train], dim=0).numpy())
    for part in (train, val, test):
        for d in part:
            d.x = torch.tensor(scaler.transform(d.x.numpy()), dtype=torch.float32)

    model = load_model(str(checkpoint_path), device)
    loader = DataLoader(test, batch_size=128, shuffle=False)

    probs, labels = [], []
    with torch.no_grad():
        for batch in loader:
            out = model(batch.x.to(device), batch.edge_index.to(device), batch.batch.to(device))
            probs.extend(torch.softmax(out, dim=1)[:, 1].cpu().numpy().tolist())
            labels.extend(batch.y.view(-1).cpu().numpy().astype(int).tolist())

    p, y = np.array(probs), np.array(labels)
    preds = (p >= LOCKED_THRESHOLD).astype(int)
    metrics = {
        "model_version": MODEL_VERSION,
        "threshold_locked_on_validation": LOCKED_THRESHOLD,
        "note": "Notebook comments mention 0.77; the locked code value is 0.79. We report 0.79.",
        "test_size": int(len(y)),
        "test_positives": int(y.sum()),
        "precision": round(float(precision_score(y, preds, zero_division=0)), 4),
        "recall": round(float(recall_score(y, preds, zero_division=0)), 4),
        "f1_positive": round(float(f1_score(y, preds, zero_division=0)), 4),
        "pr_auc": round(float(average_precision_score(y, p)), 4),
        "confusion_matrix": confusion_matrix(y, preds).tolist(),
        "runtime_seconds": round(time.perf_counter() - t0, 2),
        "device": str(device),
        "dataset_sha256": sha256_file(dataset_path),
        "checkpoint_sha256": sha256_file(checkpoint_path), 
    }

    out_dir = Path(__file__).resolve().parent / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(f"threshold       : {LOCKED_THRESHOLD} (locked on validation)")
    print(f"test size       : {metrics['test_size']}  positives: {metrics['test_positives']}")
    print(f"precision       : {metrics['precision']}")
    print(f"recall          : {metrics['recall']}")
    print(f"F1 (positive)   : {metrics['f1_positive']}")
    print(f"PR-AUC          : {metrics['pr_auc']}")
    print(f"confusion matrix: {metrics['confusion_matrix']}")
    print(f"wrote           : {out_dir / 'metrics.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

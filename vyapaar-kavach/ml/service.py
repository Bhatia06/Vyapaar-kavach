"""Lazy-loaded inference service for the original-domain GATv2 engine.

The web API uses this to run *real* model inference on the Elliptic2
subgraphs. Merchant workflow cases deliberately **abstain**: the engine's
label space belongs to Bitcoin subgraph research, not merchant UPI disputes.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from .model import SmurfDetector, load_model

# Split / evaluation contract mirrors the research notebook: the dataset is
# index-split 72% train / 8% val / 20% test and features are standardised
# with a scaler fit on train only. Threshold 0.79 was locked on validation.
TRAIN_FRAC, VAL_FRAC = 0.72, 0.08
LOCKED_THRESHOLD = 0.79
MODEL_VERSION = "gatv2-smurf-elliptic2-v1"

_cache: dict[str, Any] = {"model": None, "device": None, "hashes": None}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_assets(dataset_path: Path, checkpoint_path: Path):
    """Load (once) the dataset list, device, model, and artifact hashes."""
    import torch  # deferred: the API must boot even if torch is unavailable

    if _cache["model"] is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = load_model(str(checkpoint_path), device)
        _cache.update(
            model=model,
            device=device,
            hashes={
                "checkpoint_sha256": sha256_file(checkpoint_path),
                "dataset_sha256": sha256_file(dataset_path),
            },
        )
    return _cache


def load_dataset(dataset_path: Path):
    import torch

    return torch.load(str(dataset_path), map_location="cpu", weights_only=False)


def split_bounds(n: int) -> tuple[slice, slice, slice]:
    train_end = int(TRAIN_FRAC * n)
    val_end = int((TRAIN_FRAC + VAL_FRAC) * n)
    return slice(0, train_end), slice(train_end, val_end), slice(val_end, n)


def run_inference(
    dataset_path: Path, checkpoint_path: Path, sample_size: int
) -> dict[str, Any]:
    """Score a bounded sample from the held-out test slice.

    Returns per-graph probabilities plus aggregate metrics computed at the
    locked validation threshold. Runs on CPU/GPU transparently.
    """
    import numpy as np
    import torch
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import f1_score, precision_score, recall_score
    from torch_geometric.loader import DataLoader

    started = time.perf_counter()
    cache = load_assets(dataset_path, checkpoint_path)
    data = load_dataset(dataset_path)
    train_s, _val_s, test_s = split_bounds(len(data))

    # Fit the scaler on train only — never leak test statistics.
    scaler = StandardScaler().fit(
        torch.cat([d.x for d in data[train_s]], dim=0).numpy()
    )
    sample = data[test_s][:sample_size]
    for d in sample:
        d.x = torch.tensor(scaler.transform(d.x.numpy()), dtype=torch.float32)

    loader = DataLoader(sample, batch_size=64, shuffle=False)
    model: SmurfDetector = cache["model"]
    device = cache["device"]

    probs, labels, entries = [], [], []
    offset = test_s.start or 0
    with torch.no_grad():
        for i, batch in enumerate(loader):
            out = model(batch.x.to(device), batch.edge_index.to(device), batch.batch.to(device))
            p = torch.softmax(out, dim=1)[:, 1].cpu().numpy()
            probs.extend(p.tolist())
            labels.extend(batch.y.view(-1).cpu().numpy().astype(int).tolist())
    for i, (p, y) in enumerate(zip(probs, labels)):
        entries.append(
            {"graph_index": offset + i, "prob_suspicious": round(float(p), 4), "label": int(y)}
        )

    arr_p, arr_y = np.array(probs), np.array(labels)
    preds = (arr_p >= LOCKED_THRESHOLD).astype(int)
    runtime_ms = int((time.perf_counter() - started) * 1000)
    return {
        "hashes": cache["hashes"],
        "runtime_ms": runtime_ms,
        "device": str(cache["device"]),
        "threshold": LOCKED_THRESHOLD,
        "sample_size": len(entries),
        "positives": int(arr_y.sum()),
        "metrics": {
            "precision": round(float(precision_score(arr_y, preds, zero_division=0)), 4),
            "recall": round(float(recall_score(arr_y, preds, zero_division=0)), 4),
            "f1": round(float(f1_score(arr_y, preds, zero_division=0)), 4),
        },
        "entries": entries,
    }

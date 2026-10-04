# Model Card — GATv2 "SmurfDetector" (original-domain engine)

## Scope of this card

This card documents the **original-domain research engine** shipped with this
prototype. It classifies Elliptic2 **Bitcoin subgraph** clusters as
licit/suspicious. It is **not** a merchant payment/UPI fraud model, and the
product treats it as such: merchant-case scoring abstains intentionally.

## Task

- Binary **graph-level** classification of Elliptic2 connected-component subgraphs.
- Positive class: `suspicious` (label 1). Prevalence in test set: 518 / 24,363 (~2.1%).

## Data

| Field | Value |
|---|---|
| Dataset | `dataset1 (1).pt` — 121,810 PyG `Data` objects (pre-materialized from the Elliptic2 Kaggle pipeline notebooks) |
| SHA-256 | `bcf2ec098be9ec7f...` (full: `ml/artifacts/metrics.json`) |
| Features | 43 numeric node features from the Elliptic2 pipeline; no edge features |
| Labels | 119,047 licit / 2,763 suspicious (~2.3% positives) |

Split protocol (matches the research notebook): index-based 72/8/20 →
87,703 train / 9,744 val / 24,363 test.
`StandardScaler` fit **only on the train slice**; applied to val/test.

## Architecture (matches checkpoint exactly)

```
GATv2Conv(43 -> 16, heads=4) -> BatchNorm1d(64) -> ReLU -> Dropout(0.4)
GATv2Conv(64 -> 16, heads=4) -> BatchNorm1d(64) -> ReLU -> Dropout(0.4)
GATv2Conv(64 -> 16, heads=4) -> BatchNorm1d(64) -> ReLU -> Dropout(0.4)
concat(global_mean_pool, global_max_pool) -> Linear(128 -> 2)
```

- Stock PyG `GATv2Conv` (softmax attention). The custom entmax-attention
  variants in the repository root (`TG_GAT.py`, `entmax_gatv2conv.py`,
  `scatter_entmax.py`) are research-in-progress and **do not** match this
  checkpoint (no temperature/edge parameters in the state dict).
- Checkpoint: `GAT_Model_Final (2).pt`, SHA-256 `9919ca88c66fba73...`.

## Training protocol (as documented in the notebooks)

- Adam lr 0.001, weighted cross-entropy (class weights 0.51 / 7.56),
  `ReduceLROnPlateau(mode=max)` on validation F1, best-checkpoint saving,
  early stopping patience 20, batch size 64.
- Decision threshold **0.79 locked on the validation set**; the final test
  evaluation is a single run at that threshold. (One notebook comment says
  0.77 while the shipped code uses 0.79 — we report 0.79 as the code value.)

## Reproduced performance (verified 3 Oct 2026)

Full 24,363-graph test set, 518 positives, CUDA device, threshold 0.79:

| Metric | Value |
|---|---|
| Precision (suspicious) | 0.6988 |
| Recall (suspicious) | 0.4614 |
| **F1 (suspicious)** | **0.5558** |
| PR-AUC | 0.5906 |
| Confusion matrix | [[23742, 103], [279, 239]] |

Reproduction command: `python -m ml.reproduce` (writes `ml/artifacts/metrics.json`,
~19 s including dataset load). Earlier informal reporting of "F1 ≈ 0.60"
reproduces as **0.5558** under this protocol.

## Limitations

- Index-based random split; no entity-time or group leakage controls verified.
- Single configuration, not multi-seed for this exact checkpoint.
- Extreme class imbalance: recall 46% — many suspicious clusters go unnoticed.
- Domain is Bitcoin subgraphs; **no transfer claim** to merchant UPI/payments.
  In-product, the run API abstains for any task other than
  `elliptic2_smurf_reproduction`.

## Intended use

Research panel only: `POST /v1/research/runs` with
`task = elliptic2_smurf_reproduction`. Every run records dataset + checkpoint
hashes and abstention reasons. `may_change_financial_state` is always false.

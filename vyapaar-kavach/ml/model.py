"""Original-domain GATv2 model definition ("SmurfDetector").

This is a faithful re-declaration of the architecture used in the research
notebooks (`Smurf_trainer.ipynb`, `smurf-elliptic-rp.ipynb`) and stored in
`GAT_Model_Final (2).pt`:

    3 x (GATv2Conv -> BatchNorm -> ReLU -> Dropout), 43 -> 16x4 heads per layer
    concat(global_mean_pool, global_max_pool) -> Linear(128 -> 2)

The checkpoint contains stock PyG ``GATv2Conv`` weights (no custom
entmax/temperature parameters), so we import the stock layer here on purpose.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import GATv2Conv, global_max_pool, global_mean_pool


class SmurfDetector(nn.Module):
    """Binary graph classifier over small Elliptic2 subgraphs (43 features)."""

    NUM_FEATURES = 43
    HIDDEN = 16
    HEADS = 4
    DROPOUT = 0.4

    def __init__(self) -> None:
        super().__init__()
        self.conv1 = GATv2Conv(self.NUM_FEATURES, self.HIDDEN, heads=self.HEADS)
        self.bn1 = nn.BatchNorm1d(self.HIDDEN * self.HEADS)
        self.conv2 = GATv2Conv(self.HIDDEN * self.HEADS, self.HIDDEN, heads=self.HEADS)
        self.bn2 = nn.BatchNorm1d(self.HIDDEN * self.HEADS)
        self.conv3 = GATv2Conv(self.HIDDEN * self.HEADS, self.HIDDEN, heads=self.HEADS)
        self.bn3 = nn.BatchNorm1d(self.HIDDEN * self.HEADS)
        self.classifier = nn.Linear(2 * self.HIDDEN * self.HEADS, 2)

    def forward(self, x, edge_index, batch):
        for conv, bn in ((self.conv1, self.bn1), (self.conv2, self.bn2), (self.conv3, self.bn3)):
            x = conv(x, edge_index)
            x = bn(x)
            x = F.relu(x)
            x = F.dropout(x, p=self.DROPOUT, training=self.training)
        x = torch.cat([global_mean_pool(x, batch), global_max_pool(x, batch)], dim=1)
        return self.classifier(x)


def load_model(checkpoint_path: str, device: torch.device) -> SmurfDetector:
    """Instantiate the architecture and load the saved state dict."""
    model = SmurfDetector().to(device)
    state = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model.load_state_dict(state)
    model.eval()
    return model

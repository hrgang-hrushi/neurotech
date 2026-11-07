"""Two decoders: a Riemannian classifier and a pretrained network.

With only tens of trials from one person, Riemannian tangent-space classifiers are hard
to beat and fit in seconds, so that is the safety net. The network brings in what it
learned from many other people. `calibrate` scores both on held-out cues and keeps
whichever wins, or an average of the two.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import torch
from pyriemann.estimation import Covariances
from pyriemann.tangentspace import TangentSpace
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from torch import nn

from .config import SignalConfig, mirror_pairs


def device() -> torch.device:
    return torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def make_riemann():
    return make_pipeline(Covariances(estimator="oas"), TangentSpace(metric="riemann"),
                         LogisticRegression(C=1.0, max_iter=2000))


class ShallowNet(nn.Module):
    """A shallow ConvNet: temporal filters, a spatial filter, then log band power.

    This mirrors the classic mu/beta ERD computation, which is why it works on motor EEG
    with few parameters. Kept in-repo so the checkpoint format doesn't depend on a library.
    """

    def __init__(self, n_channels: int, n_times: int, n_classes: int, filters: int = 40):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Conv2d(1, filters, (1, 25), padding=(0, 12)),
            nn.Conv2d(filters, filters, (n_channels, 1), bias=False),
            nn.BatchNorm2d(filters),
        )
        self.pool = nn.AvgPool2d((1, 60), stride=(1, 20))
        self.dropout = nn.Dropout(0.5)
        with torch.no_grad():
            size = self._features(torch.zeros(1, n_channels, n_times)).shape[1]
        self.head = nn.Linear(size, n_classes)

    def _features(self, x: torch.Tensor) -> torch.Tensor:
        out = self.encoder(x[:, None])
        out = torch.log(torch.clamp(self.pool(out * out), min=1e-6))
        return out.flatten(1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.dropout(self._features(x)))


@dataclass
class TrainConfig:
    epochs: int = 40
    batch_size: int = 128
    lr: float = 1e-3
    weight_decay: float = 1e-4
    head_only: bool = False
    flip: list[int] | None = field(default=None)  # left/right channel map, or None
    flip_labels: list[int] | None = field(default=None)  # label map that goes with it


def flip_maps(channels: list[str], classes: list[str]):
    """Left/right mirror maps for augmentation, or (None, None) if the montage can't mirror."""
    pairs = mirror_pairs(channels)
    if pairs is None or "left" not in classes or "right" not in classes:
        return None, None
    swap = {"left": "right", "right": "left"}
    return pairs, [classes.index(swap.get(c, c)) for c in classes]


def _augment(x: torch.Tensor, y: torch.Tensor, cfg: TrainConfig):
    # Mirror half the batch: a flipped left-hand trial looks like a right-hand one, which
    # doubles the data and stops the model keying on a person's asymmetric cap fit.
    if cfg.flip is not None:
        mask = torch.rand(len(x), device=x.device) < 0.5
        if mask.any():
            x = x.clone()
            y = y.clone()
            x[mask] = x[mask][:, torch.tensor(cfg.flip, device=x.device)]
            y[mask] = torch.tensor(cfg.flip_labels, device=x.device)[y[mask]]
    x = x + 0.05 * torch.randn_like(x)
    return x, y


def fit_net(model: ShallowNet, X: np.ndarray, y: np.ndarray, cfg: TrainConfig,
            log_every: int = 0) -> ShallowNet:
    dev = device()
    model.to(dev).train()
    for param in model.parameters():
        param.requires_grad = not cfg.head_only
    for param in model.head.parameters():
        param.requires_grad = True
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad),
                                  lr=cfg.lr, weight_decay=cfg.weight_decay)
    schedule = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=cfg.lr,
        total_steps=cfg.epochs * max(1, int(np.ceil(len(y) / cfg.batch_size))))
    counts = np.bincount(y, minlength=model.head.out_features).clip(min=1)
    weights = torch.tensor(counts.sum() / (len(counts) * counts), dtype=torch.float32, device=dev)
    loss_fn = nn.CrossEntropyLoss(weight=weights)
    x_all = torch.from_numpy(X).float().to(dev)
    y_all = torch.from_numpy(y).long().to(dev)
    for epoch in range(cfg.epochs):
        order = torch.randperm(len(y_all), device=dev)
        total = 0.0
        for start in range(0, len(order), cfg.batch_size):
            batch = order[start:start + cfg.batch_size]
            xb, yb = _augment(x_all[batch], y_all[batch], cfg)
            optimizer.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            optimizer.step()
            schedule.step()
            total += loss.item() * len(batch)
        if log_every and (epoch + 1) % log_every == 0:
            print(f"  epoch {epoch + 1:3d}/{cfg.epochs}  loss {total / len(y_all):.3f}")
    return model.eval()


@torch.no_grad()
def net_probs(model: ShallowNet, X: np.ndarray, batch_size: int = 512) -> np.ndarray:
    dev = next(model.parameters()).device
    model.eval()
    out = [torch.softmax(model(torch.from_numpy(X[i:i + batch_size]).float().to(dev)), dim=1).cpu()
           for i in range(0, len(X), batch_size)]
    return torch.cat(out).numpy()


class SessionModel:
    """What the live loop runs: signal settings, whitening, and the chosen decoder(s).

    `mode` is which decoder runs. `movement` is what it was calibrated on: imagined or real.
    The default sits on the class so that files saved before it existed load as unknown.
    """

    movement: str = "unknown"

    def __init__(self, channels: list[str], classes: list[str], cfg: SignalConfig,
                 whitening: np.ndarray, net: ShallowNet | None, riemann, mode: str,
                 movement: str = "unknown"):
        self.channels, self.classes, self.cfg = channels, classes, cfg
        self.whitening, self.net, self.riemann, self.mode = whitening, net, riemann, mode
        self.movement = movement

    def predict_proba(self, aligned: np.ndarray) -> np.ndarray:
        parts = []
        if self.mode in ("net", "ensemble"):
            parts.append(net_probs(self.net, aligned))
        if self.mode in ("riemann", "ensemble"):
            parts.append(self.riemann.predict_proba(aligned.astype(np.float64)))
        return np.mean(parts, axis=0)

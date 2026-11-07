"""Pretrain on PhysioNet, then calibrate to one person."""

from __future__ import annotations

import time
from pathlib import Path

import joblib
import numpy as np
import torch
from sklearn.metrics import accuracy_score, balanced_accuracy_score
from sklearn.model_selection import StratifiedGroupKFold

from .config import ARTIFACT_DIR, SignalConfig
from .datasets import Windows, load_physionet, load_recording
from .models import (SessionModel, ShallowNet, TrainConfig, fit_net, flip_maps, make_riemann,
                     net_probs)
from .preprocess import apply_whitening, whitening_matrix

BASELINE_WINDOWS = 20  # about what a 60-second resting baseline gives us live


def baseline_of(data: Windows, limit: int | None = None) -> np.ndarray:
    rest = data.y == data.classes.index("rest") if "rest" in data.classes else np.ones(len(data), bool)
    windows = data.X[rest] if rest.any() else data.X
    return windows[:limit] if limit else windows


def align_by_subject(data: Windows, limit: int | None = None) -> Windows:
    """Whiten each subject from their own resting windows, without using task labels."""
    X = data.X.copy()
    for subject in np.unique(data.subject):
        mask = data.subject == subject
        X[mask] = apply_whitening(data.X[mask], whitening_matrix(baseline_of(data.select(mask), limit)))
    return Windows(X, data.y, data.trial, data.subject, data.channels, data.classes)


def checkpoint_path(channels: list[str]) -> Path:
    return ARTIFACT_DIR / f"pretrained_{len(channels)}ch.pt"


def pretrain(subjects: list[int], heldout: list[int], channels: list[str], classes: list[str],
             cfg: SignalConfig, epochs: int, include_imagined: bool) -> Path:
    t0 = time.time()
    print(f"Loading {len(subjects)} training and {len(heldout)} held-out subjects ...")
    train = align_by_subject(load_physionet(subjects, channels, classes, cfg, include_imagined))
    print(f"  {len(train)} training windows from {len(np.unique(train.trial))} cues "
          f"({time.time() - t0:.0f}s)")

    flip, flip_labels = flip_maps(channels, classes)
    print(f"Training on {torch.device('mps' if torch.backends.mps.is_available() else 'cpu')}, "
          f"left/right mirroring {'on' if flip else 'off'} ...")
    net = ShallowNet(len(channels), cfg.n_times, len(classes))
    train_cfg = TrainConfig(epochs=epochs, flip=flip, flip_labels=flip_labels)
    fit_net(net, train.X, train.y, train_cfg, log_every=max(1, epochs // 5))

    results = {}
    if heldout:
        # A brand-new person: no labelled calibration, only a short resting baseline.
        test = align_by_subject(load_physionet(heldout, channels, classes, cfg),
                                limit=BASELINE_WINDOWS)
        results = score(test.y, net_probs(net, test.X), classes)
        print(f"Held-out new-person score, no calibration: {results}")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = checkpoint_path(channels)
    torch.save({"state": {k: v.cpu() for k, v in net.state_dict().items()},
                "channels": channels, "classes": classes, "cfg": cfg.to_dict(),
                "results": results, "subjects": subjects}, path)
    print(f"Saved {path} ({time.time() - t0:.0f}s total)")
    return path


def score(y_true: np.ndarray, probs: np.ndarray, classes: list[str]) -> dict:
    pred = probs.argmax(axis=1)
    return {"accuracy": round(float(accuracy_score(y_true, pred)), 3),
            "balanced_accuracy": round(float(balanced_accuracy_score(y_true, pred)), 3),
            "chance": round(1 / len(classes), 3), "n": int(len(y_true))}


def load_pretrained(path: Path) -> tuple[ShallowNet, dict]:
    saved = torch.load(path, map_location="cpu", weights_only=False)
    cfg = SignalConfig(**{**saved["cfg"], "band": tuple(saved["cfg"]["band"])})
    net = ShallowNet(len(saved["channels"]), cfg.n_times, len(saved["classes"]))
    net.load_state_dict(saved["state"])
    return net, saved


def _finetune(path: Path | None, data: Windows, cfg: SignalConfig) -> ShallowNet:
    """Fit the head with the encoder frozen, then nudge the whole net at a low rate."""
    flip, flip_labels = flip_maps(data.channels, data.classes)
    if path is None:
        net = ShallowNet(len(data.channels), cfg.n_times, len(data.classes))
        return fit_net(net, data.X, data.y, TrainConfig(epochs=60, batch_size=32, flip=flip,
                                                       flip_labels=flip_labels))
    net, _ = load_pretrained(path)
    fit_net(net, data.X, data.y, TrainConfig(epochs=30, batch_size=32, lr=1e-3, head_only=True,
                                             flip=flip, flip_labels=flip_labels))
    return fit_net(net, data.X, data.y, TrainConfig(epochs=20, batch_size=32, lr=1e-4, flip=flip,
                                                    flip_labels=flip_labels))


def evaluate_session(data: Windows, cfg: SignalConfig, pretrained: Path | None, folds: int = 4):
    """Score each decoder on cues it never saw.

    Windows overlap, so splitting them at random would leak the test set into training
    and inflate the score. Grouping keeps every window from one cue on the same side, and
    stratifying keeps every class in every fold, even in a short recording. This is still
    a same-session score, so expect live performance after refitting the net to be lower.
    """
    smallest = min(len(np.unique(data.trial[data.y == c])) for c in np.unique(data.y))
    splitter = StratifiedGroupKFold(n_splits=min(folds, smallest), shuffle=True, random_state=0)
    probs = {"riemann": np.zeros((len(data), len(data.classes))),
             "net": np.zeros((len(data), len(data.classes)))}
    for train_idx, test_idx in splitter.split(data.X, data.y, data.trial):
        fold = data.select(np.isin(np.arange(len(data)), train_idx))
        probs["riemann"][test_idx] = make_riemann().fit(fold.X.astype(np.float64),
                                                        fold.y).predict_proba(
            data.X[test_idx].astype(np.float64))
        probs["net"][test_idx] = net_probs(_finetune(pretrained, fold, cfg), data.X[test_idx])
    probs["ensemble"] = (probs["riemann"] + probs["net"]) / 2
    return {name: score(data.y, p, data.classes) for name, p in probs.items()}


def calibrate(recording: Path, pretrained: Path | None, channels: list[str], classes: list[str],
              cfg: SignalConfig, schedule: Path | None, out: Path) -> dict:
    data, baseline = load_recording(recording, channels, classes, cfg, schedule)
    counts = dict(zip(classes, np.bincount(data.y, minlength=len(classes)).tolist()))
    print(f"{len(data)} windows from {len(np.unique(data.trial))} cues. Windows per class: {counts}")
    whitening = whitening_matrix(baseline)
    aligned = Windows(apply_whitening(data.X, whitening), data.y, data.trial, data.subject,
                      data.channels, data.classes)

    results = evaluate_session(aligned, cfg, pretrained)
    for name, result in results.items():
        print(f"  {name:9s} {result}")
    best = max(results, key=lambda name: results[name]["balanced_accuracy"])
    print(f"Using: {best}")

    riemann = make_riemann().fit(aligned.X.astype(np.float64), aligned.y)
    net = _finetune(pretrained, aligned, cfg)
    model = SessionModel(channels, classes, cfg, whitening, net.cpu(), riemann, best)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out)
    print(f"Saved {out}")
    return results

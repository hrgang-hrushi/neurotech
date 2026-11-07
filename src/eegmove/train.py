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
from torch import nn

from .models import (SessionModel, ShallowNet, TrainConfig, fit_net, flip_maps, make_riemann,
                     net_probs)
from .preprocess import apply_whitening, whitening_matrix
from .quality import WindowGate
from .verdict import save_offline

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


def latest_checkpoint() -> Path:
    """The newest pretrained model, which is the one rebuilt on the real channels."""
    found = sorted(ARTIFACT_DIR.glob("pretrained_*.pt"), key=lambda p: p.stat().st_mtime)
    if not found:
        raise FileNotFoundError("No pretrained model yet. Run: eegmove pretrain")
    return found[-1]


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
        # With --imagined this scores imagined runs alone, since real runs would flatter it.
        test = align_by_subject(load_physionet(heldout, channels, classes, cfg,
                                               imagined_only=include_imagined),
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


def left_right_score(y_true: np.ndarray, probs: np.ndarray, classes: list[str]) -> float | None:
    """Left vs right on their own windows, deciding only between those two outputs."""
    if "left" not in classes or "right" not in classes:
        return None
    left, right = classes.index("left"), classes.index("right")
    mask = np.isin(y_true, [left, right])
    if not mask.any():
        return None
    picked = np.where(probs[mask, left] >= probs[mask, right], left, right)
    return float(balanced_accuracy_score(y_true[mask], picked))


def score(y_true: np.ndarray, probs: np.ndarray, classes: list[str]) -> dict:
    """Rounded figures for people, raw ones for the go/no-go rule.

    The rule must use the raw values: 0.8496 rounds to 0.85 and would pass an 85% bar.
    """
    pred = probs.argmax(axis=1)
    accuracy = float(accuracy_score(y_true, pred))
    balanced = float(balanced_accuracy_score(y_true, pred))
    return {"accuracy": round(accuracy, 3), "balanced_accuracy": round(balanced, 3),
            "chance": round(1 / len(classes), 3), "n": int(len(y_true)),
            "accuracy_raw": accuracy, "balanced_raw": balanced,
            "left_right": left_right_score(y_true, probs, classes)}


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
    net, saved = load_pretrained(path)
    if saved["classes"] != data.classes:
        # The head is refit below anyway, so a different class set only needs a new one.
        net.head = nn.Linear(net.head.in_features, len(data.classes))
    fit_net(net, data.X, data.y, TrainConfig(epochs=30, batch_size=32, lr=1e-3, head_only=True,
                                             flip=flip, flip_labels=flip_labels))
    return fit_net(net, data.X, data.y, TrainConfig(epochs=20, batch_size=32, lr=1e-4, flip=flip,
                                                    flip_labels=flip_labels))


def cue_folds(data: Windows, folds: int = 4) -> list[tuple[np.ndarray, np.ndarray]]:
    """Split by cue so that every training side holds every class, or stop with a reason."""
    counts = {name: len(np.unique(data.trial[data.y == i])) for i, name in enumerate(data.classes)}
    thin = [f"{name} ({n})" for name, n in counts.items() if n < 2]
    if thin:
        raise ValueError(f"Too few usable cues to score this recording: {', '.join(thin)}. "
                         "Each class needs at least 2.")
    n_splits = min(folds, *counts.values())
    wanted = set(range(len(data.classes)))
    for seed in range(10):
        splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
        split = list(splitter.split(data.X, data.y, data.trial))
        if all(set(data.y[train].tolist()) == wanted for train, _ in split):
            return split
    raise ValueError("Couldn't split the cues so that every fold trains on every class.")


def evaluate_session(data: Windows, cfg: SignalConfig, pretrained: Path | None, folds: int = 4,
                     use_net: bool = True):
    """Score each decoder on cues it never saw.

    Windows overlap, so splitting them at random would leak the test set into training
    and inflate the score. Grouping keeps every window from one cue on the same side, and
    stratifying keeps every class in every fold, even in a short recording. This is still
    a same-session score, so expect live performance after refitting the net to be lower.
    """
    probs = {"riemann": np.zeros((len(data), len(data.classes)))}
    if use_net:
        probs["net"] = np.zeros((len(data), len(data.classes)))
    for train_idx, test_idx in cue_folds(data, folds):
        fold = data.select(np.isin(np.arange(len(data)), train_idx))
        probs["riemann"][test_idx] = make_riemann().fit(fold.X.astype(np.float64),
                                                        fold.y).predict_proba(
            data.X[test_idx].astype(np.float64))
        if use_net:
            probs["net"][test_idx] = net_probs(_finetune(pretrained, fold, cfg), data.X[test_idx])
    if use_net:
        probs["ensemble"] = (probs["riemann"] + probs["net"]) / 2
    return {name: score(data.y, p, data.classes) for name, p in probs.items()}


def calibrate(recording: Path, pretrained: Path | None, channels: list[str], classes: list[str],
              cfg: SignalConfig, schedule: Path | None, out: Path, use_net: bool = True,
              movement: str = "unknown") -> dict:
    data, baseline = load_recording(recording, channels, classes, cfg, schedule)
    keep = WindowGate(baseline).mask(data.X)
    if not keep.all():
        print(f"Quality gate rejected {(~keep).sum()} of {len(keep)} windows.")
        data = data.select(keep)
    counts = dict(zip(classes, np.bincount(data.y, minlength=len(classes)).tolist()))
    print(f"{len(data)} windows from {len(np.unique(data.trial))} cues. Windows per class: {counts}")
    whitening = whitening_matrix(baseline)
    aligned = Windows(apply_whitening(data.X, whitening), data.y, data.trial, data.subject,
                      data.channels, data.classes)

    results = evaluate_session(aligned, cfg, pretrained, use_net=use_net)
    for name, result in results.items():
        shown = {k: v for k, v in result.items() if not k.endswith("_raw")}
        print(f"  {name:9s} {shown}")
    best = max(results, key=lambda name: results[name]["balanced_raw"])
    print(f"Using: {best}")

    riemann = make_riemann().fit(aligned.X.astype(np.float64), aligned.y)
    net = _finetune(pretrained, aligned, cfg).cpu() if use_net else None
    model = SessionModel(channels, classes, cfg, whitening, net, riemann, best, movement)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out)
    record = save_offline(out, movement, best, results[best])
    print(f"Saved {out} ({movement} movement). Next: eegmove check {out}")
    print(f"Held-out left vs right: {results[best]['left_right']}")
    print(f"Still needed for GO: {'; '.join(record['reasons'])}")
    return results

"""Detection stage: activation trace -> key-down intervals.

Threshold: Otsu's method splits the activation histogram into a "rest" and an
"active" population, which adapts to each recording's gain and impedance. A
hysteresis band around it (enter above `hi`, leave below `lo`) stops a noisy
trace from chattering, then short blips and dropouts are cleaned up.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import DetectConfig


@dataclass
class Thresholds:
    lo: float
    hi: float
    split: float
    rest_level: float  # mean activation of the rest class
    active_level: float  # mean activation of the active class
    separability: float  # Otsu eta in [0, 1]; < ~0.5 means no clear on/off states


@dataclass
class Segment:
    t_on: float
    t_off: float

    @property
    def duration(self) -> float:
        return self.t_off - self.t_on


def otsu(x: np.ndarray, nbins: int = 256) -> tuple[float, float, float, float]:
    """Return (threshold, mean_below, mean_above, eta)."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    lo, hi = np.percentile(x, [0.5, 99.5])
    if hi <= lo:
        return float(lo), float(lo), float(hi), 0.0
    xc = np.clip(x, lo, hi)
    hist, edges = np.histogram(xc, bins=nbins, range=(lo, hi))
    centers = (edges[:-1] + edges[1:]) / 2
    p = hist / hist.sum()
    w0 = np.cumsum(p)
    w1 = 1 - w0
    m = np.cumsum(p * centers)
    mt = m[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mt * w0 - m) ** 2 / (w0 * w1)
    between[~np.isfinite(between)] = 0
    k = int(np.argmax(between))
    thr = edges[k + 1]
    below, above = xc[xc <= thr], xc[xc > thr]
    mu0 = float(below.mean()) if below.size else float(lo)
    mu1 = float(above.mean()) if above.size else float(hi)
    total_var = xc.var()
    eta = float(between[k] / total_var) if total_var > 0 else 0.0
    return float(thr), mu0, mu1, min(1.0, eta)


def fit_thresholds(act: np.ndarray, cfg: DetectConfig) -> Thresholds:
    thr, mu0, mu1, eta = otsu(act)
    if cfg.lo is not None and cfg.hi is not None:
        rest = cfg.rest_level if cfg.rest_level is not None else mu0
        return Thresholds(cfg.lo, cfg.hi, (cfg.lo + cfg.hi) / 2, rest, mu1, eta)
    h = float(np.clip(cfg.hysteresis, 0.0, 0.95))
    hi = thr + h * (mu1 - thr)
    lo = thr - h * (thr - mu0)
    return Thresholds(lo, hi, thr, mu0, mu1, eta)


def hysteresis(act: np.ndarray, lo: float, hi: float) -> np.ndarray:
    state = np.zeros(act.size, dtype=bool)
    on = False
    for i, v in enumerate(act):
        if on:
            on = v > lo
        else:
            on = v > hi
        state[i] = on
    return state


def runs(state: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index pairs of True runs."""
    d = np.diff(np.concatenate([[0], state.astype(np.int8), [0]]))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return list(zip(starts.tolist(), ends.tolist()))


def clean(iv: list[tuple[int, int]], rate: float, min_on_s: float,
          min_off_s: float) -> list[tuple[int, int]]:
    """Bridge dropouts shorter than min_off, then drop blips shorter than min_on."""
    min_off = min_off_s * rate
    min_on = min_on_s * rate
    merged: list[list[int]] = []
    for a, b in iv:
        if merged and a - merged[-1][1] < min_off:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged if b - a >= min_on]


def detect(t: np.ndarray, act: np.ndarray, rate: float,
           cfg: DetectConfig) -> tuple[list[Segment], Thresholds]:
    th = fit_thresholds(act, cfg)
    iv = clean(runs(hysteresis(act, th.lo, th.hi)), rate, cfg.min_on_s, cfg.min_off_s)
    # Key-downs touching the first/last edge_s are filter edge artifacts (or a
    # movement cut off by the recording) and can't be timed: drop them.
    edge = int(round(cfg.edge_s * rate))
    iv = [(a, b) for a, b in iv if a >= edge and b <= act.size - edge]
    dt = 1.0 / rate
    segs = [Segment(float(t[0] + a * dt), float(t[0] + b * dt)) for a, b in iv]
    return segs, th

"""Signal stage: EEG channels -> one "key down" activation trace.

Steps (offline, zero-phase):
  1. pick the channels for the chosen movement (e.g. C3/C4 for hand movement)
  2. re-reference to the common average of all scalp EEG channels
  3. notch mains interference, band-pass to the movement band
  4. square -> moving average -> log10 = log band-power envelope
  5. average across the picked channels, flip the sign for ERD so that
     "higher activation = key down" for every preset
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from scipy import signal as sps
from scipy.ndimage import percentile_filter, uniform_filter1d

from .config import FeatureConfig
from .io import Recording

_TINY = np.finfo(np.float64).tiny


def resolve_channels(ch_names: list[str], wanted: list[str]) -> tuple[list[int], list[str]]:
    """Case-insensitive lookup. Returns (indices, missing names)."""
    lookup = {c.strip().lower(): i for i, c in enumerate(ch_names)}
    idx, missing = [], []
    for w in wanted:
        i = lookup.get(w.strip().lower())
        if i is None:
            missing.append(w)
        elif i not in idx:
            idx.append(i)
    return idx, missing


def pick_indices(rec_names: list[str], rec_types: list[str], cfg: FeatureConfig) -> tuple[list[int], list[int]]:
    """Indices of the feature channels and of all EEG channels (for CAR)."""
    idx, missing = resolve_channels(rec_names, cfg.channels)
    if not idx:
        raise ValueError(
            f"none of the channels {cfg.channels} are in this recording. "
            f"Available: {rec_names}. Pass --channels with labels from your cap."
        )
    if missing:
        warnings.warn(f"channels not found and skipped: {missing}", stacklevel=2)
    eeg_idx = [i for i, t in enumerate(rec_types) if t == "eeg"]
    return idx, eeg_idx


def design_filter(band: tuple[float, float], sfreq: float, line_freq: float | None,
                  order: int = 4) -> np.ndarray:
    """Band-pass (Butterworth) plus mains notches inside the pass band, as SOS."""
    nyq = sfreq / 2.0
    lo, hi = band
    hi = min(hi, 0.95 * nyq)
    if lo < 0 or lo >= hi:
        raise ValueError(f"invalid band {band} for sfreq {sfreq}")
    if lo == 0:  # low-pass only
        sections = [sps.butter(order, hi, btype="lowpass", fs=sfreq, output="sos")]
    else:
        sections = [sps.butter(order, [lo, hi], btype="bandpass", fs=sfreq, output="sos")]
    if line_freq:
        f = line_freq
        while f < min(hi + 5.0, nyq - 1.0):
            if f > lo - 5.0:
                b, a = sps.iirnotch(f, Q=30.0, fs=sfreq)
                sections.append(sps.tf2sos(b, a))
            f += line_freq
    return np.vstack(sections)


@dataclass
class Activation:
    t: np.ndarray  # seconds, envelope time base
    values: np.ndarray  # activation (higher = key down)
    rate: float  # envelope sampling rate (Hz)
    channels: list[str]  # channels actually used
    filtered: np.ndarray  # band-passed signal of the used channels (for plots)
    sfreq: float


def activation(rec: Recording, cfg: FeatureConfig) -> Activation:
    idx, eeg_idx = pick_indices(rec.ch_names, rec.ch_types, cfg)
    x = rec.data[idx]
    if cfg.reference == "car" and len(eeg_idx) >= 3:
        x = x - rec.data[eeg_idx].mean(axis=0, keepdims=True)
    sos = design_filter(cfg.band, rec.sfreq, cfg.line_freq)
    if x.shape[1] < 3 * 6 * len(sos):
        raise ValueError("recording too short to filter")
    xf = sps.sosfiltfilt(sos, x, axis=1)
    w = max(1, int(round(cfg.smooth_s * rec.sfreq)))
    step = max(1, int(round(rec.sfreq / cfg.env_rate)))
    per_ch = envelope(xf, w, cfg.measure)[:, ::step]
    act = per_ch.mean(axis=0)
    if cfg.direction == "decrease":
        act = -act
    if cfg.measure == "amplitude":
        n = max(3, int(round(cfg.baseline_s * rec.sfreq / step)))
        act = act - percentile_filter(act, cfg.baseline_pct, size=n, mode="nearest")
    t = np.arange(act.size) * step / rec.sfreq
    return Activation(t, act, rec.sfreq / step, [rec.ch_names[i] for i in idx], xf, rec.sfreq)


def envelope(xf: np.ndarray, w: int, measure: str) -> np.ndarray:
    """Per-channel envelope: log10 moving-average power, or moving-average voltage."""
    if measure == "amplitude":
        return uniform_filter1d(xf, size=w, axis=1, mode="nearest")
    power = uniform_filter1d(xf**2, size=w, axis=1, mode="nearest")
    return np.log10(np.maximum(power, _TINY))


def channel_separability(rec: Recording, cfg: FeatureConfig) -> list[tuple[str, float]]:
    """Otsu separability of each feature channel on its own, best first.

    A channel that carries the movement has two clear states (rest / active).
    Used by calibration to pick e.g. C3 for a right-hand mover and C4 for a
    left-hand mover without asking.
    """
    from .detect import otsu

    idx, eeg_idx = pick_indices(rec.ch_names, rec.ch_types, cfg)
    x = rec.data[idx]
    if cfg.reference == "car" and len(eeg_idx) >= 3:
        x = x - rec.data[eeg_idx].mean(axis=0, keepdims=True)
    xf = sps.sosfiltfilt(design_filter(cfg.band, rec.sfreq, cfg.line_freq), x, axis=1)
    w = max(1, int(round(cfg.smooth_s * rec.sfreq)))
    step = max(1, int(round(rec.sfreq / cfg.env_rate)))
    env = envelope(xf, w, cfg.measure)[:, ::step]
    if cfg.direction == "decrease":
        env = -env
    if cfg.measure == "amplitude":
        n = max(3, int(round(cfg.baseline_s * rec.sfreq / step)))
        env = env - percentile_filter(env, cfg.baseline_pct, size=(1, n), mode="nearest")
    scores = [(rec.ch_names[i], otsu(e)[3]) for i, e in zip(idx, env)]
    return sorted(scores, key=lambda s: -s[1])

"""Per-window signal checks. Everything is measured against the person's own rest.

Stream units are unknown, so there are no fixed microvolt limits. These run on filtered
windows, and each decision uses only the current window plus the resting baseline, so the
same code stays causal offline and live.
"""

from __future__ import annotations

from collections import deque
from typing import NamedTuple

import numpy as np

from .config import normalize_label

MU_BAND = (8.0, 13.0)
FLOOR_BAND = (24.0, 29.0)
HAND_PAIRS = (("C3", "C4"), ("CP3", "CP4"), ("FC3", "FC4"), ("C1", "C2"), ("C5", "C6"),
              ("CP1", "CP2"), ("FC1", "FC2"), ("CP5", "CP6"), ("FC5", "FC6"))


class WindowQuality(NamedTuple):
    ok: bool
    reason: str | None


def _rms(windows: np.ndarray) -> np.ndarray:
    return np.sqrt(np.mean(np.square(windows), axis=-1))


class WindowGate:
    """Reject windows a decision shouldn't come from.

    Common average reference means a dead channel isn't flat after filtering: it carries
    about 1/sqrt(n) of the others. So flatness is a ratio. `flat_ratio` compares a channel
    with its own rest level, and `dead_ratio` with the other channels, which also catches a
    channel that was already dead during the baseline.
    """

    def __init__(self, rest_windows: np.ndarray, flat_ratio: float = 0.33, dead_ratio: float = 0.25,
                 burst_ratio: float = 4.0, peak_ratio: float = 12.0):
        self.reference = np.median(_rms(np.asarray(rest_windows, dtype=np.float64)), axis=0)
        self.typical = float(np.median(self.reference))
        self.flat_ratio, self.dead_ratio = flat_ratio, dead_ratio
        self.burst_ratio, self.peak_ratio = burst_ratio, peak_ratio

    def check(self, window: np.ndarray) -> WindowQuality:
        """`window` is (n_channels, n_times), filtered and not yet whitened."""
        if not np.isfinite(window).all():
            return WindowQuality(False, "nonfinite")
        rms, peak = _rms(window), np.abs(window).max(axis=-1)
        if (rms < self.flat_ratio * self.reference).any() or \
                (rms < self.dead_ratio * self.typical).any():
            return WindowQuality(False, "flat")
        if (rms > self.burst_ratio * self.reference).any() or \
                (peak > self.peak_ratio * self.reference).any():
            return WindowQuality(False, "burst")
        return WindowQuality(True, None)

    def mask(self, windows: np.ndarray) -> np.ndarray:
        return np.array([self.check(window).ok for window in windows], dtype=bool)


class HandSites(NamedTuple):
    left: int
    right: int
    label: str


def hand_sites(channels: list[str]) -> HandSites | None:
    """The best left/right electrode pair over the hand areas, or None if there isn't one."""
    lookup = {normalize_label(name): i for i, name in enumerate(channels)}
    for left, right in HAND_PAIRS:
        if normalize_label(left) in lookup and normalize_label(right) in lookup:
            return HandSites(lookup[normalize_label(left)], lookup[normalize_label(right)],
                             f"{left}/{right}")
    return None


def band_power(windows: np.ndarray, sfreq: float, band: tuple[float, float]) -> np.ndarray:
    """Mean power density in a band, per window and channel. White noise is flat across bands."""
    x = np.asarray(windows, dtype=np.float64)
    taper = np.hanning(x.shape[-1])
    spectrum = np.abs(np.fft.rfft(x * taper, axis=-1)) ** 2
    freqs = np.fft.rfftfreq(x.shape[-1], 1 / sfreq)
    return spectrum[..., (freqs >= band[0]) & (freqs <= band[1])].mean(axis=-1)


class SnrMonitor:
    """A warning when mu power sinks toward the noise floor, compared with this person's rest.

    The floor band matters. Power alone rises with muscle noise, while this ratio falls
    whether the signal fades or the noise grows. It reads only during rest, so imagined
    movement, which lowers mu on purpose, isn't mistaken for signal loss. It only warns: it
    never decides the verdict, so an unusual montage can't turn into a failed check.
    """

    def __init__(self, rest_windows: np.ndarray, channels: list[str], sfreq: float,
                 drop_db: float = 3.0, span: int = 40):
        sites = hand_sites(channels)
        self.picks = [sites.left, sites.right] if sites else list(range(len(channels)))
        self.region = sites.label if sites else "all channels (no hand sites in this montage)"
        self.sfreq, self.drop_db = sfreq, drop_db
        self.recent: deque[float] = deque(maxlen=span)
        self.min_readings = span // 2
        self.baseline_db = float(np.median([self.ratio_db(w) for w in rest_windows]))

    def ratio_db(self, window: np.ndarray) -> float:
        picked = np.asarray(window)[self.picks]
        mu = band_power(picked, self.sfreq, MU_BAND).mean()
        floor = band_power(picked, self.sfreq, FLOOR_BAND).mean()
        return float(10 * np.log10(max(mu, 1e-20) / max(floor, 1e-20)))

    def update(self, window: np.ndarray, state: str, idle: str = "rest"):
        """Returns (current dB, warning). dB is None until rest windows have been seen."""
        if state == idle:
            self.recent.append(self.ratio_db(window))
        if not self.recent:
            return None, None
        current = float(np.median(self.recent))
        faded = len(self.recent) >= self.min_readings and current < self.baseline_db - self.drop_db
        warning = f"Signal fading: {current:.1f} dB at rest, was {self.baseline_db:.1f} dB" if faded else None
        return current, warning

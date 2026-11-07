"""One preprocessing path for offline and live data.

Training on zero-phase filtered data and running a causal filter live is a classic
way for a good offline score to collapse in the demo. Everything here is causal and
stateful, so one call on a whole recording matches many calls on small chunks.
"""

from __future__ import annotations

import numpy as np
from scipy import signal

from .config import SignalConfig


class StreamPreprocessor:
    """Common average reference, notch, band-pass, then resample to the model rate."""

    def __init__(self, sfreq_in: float, n_channels: int, cfg: SignalConfig):
        self.ratio = sfreq_in / cfg.sfreq
        self.n_channels = n_channels
        sections = [signal.butter(4, cfg.band, btype="bandpass", fs=sfreq_in, output="sos")]
        if cfg.mains < sfreq_in / 2:
            b, a = signal.iirnotch(cfg.mains, Q=30.0, fs=sfreq_in)
            sections.insert(0, signal.tf2sos(b, a))
        self.sos = np.vstack(sections)
        self._zi: np.ndarray | None = None
        self._last: np.ndarray | None = None
        self._pos = 0.0

    def process(self, chunk: np.ndarray) -> np.ndarray:
        """Take (n_samples, n_channels) in any unit and return filtered model-rate samples."""
        chunk = np.asarray(chunk, dtype=np.float64)
        if chunk.size == 0:
            return np.empty((0, self.n_channels))
        chunk = chunk - chunk.mean(axis=1, keepdims=True)
        if self._zi is None:
            base = signal.sosfilt_zi(self.sos)[:, :, None]
            self._zi = base * chunk[0][None, None, :]
        filtered, self._zi = signal.sosfilt(self.sos, chunk, axis=0, zi=self._zi)
        return self._resample(filtered)

    def _resample(self, x: np.ndarray) -> np.ndarray:
        if np.isclose(self.ratio, 1.0):
            return x
        # The signal is low-passed far below the input rate, so linear interpolation is
        # accurate here, and a fractional cursor keeps chunked output identical.
        buffer = x if self._last is None else np.vstack([self._last, x])
        n = len(buffer)
        positions = np.arange(self._pos, n - 1 + 1e-9, self.ratio)
        self._last = buffer[-1:].copy()
        if len(positions) == 0:
            self._pos -= n - 1
            return np.empty((0, self.n_channels))
        self._pos = positions[-1] + self.ratio - (n - 1)
        index = np.minimum(positions.astype(int), n - 1)
        frac = (positions - index)[:, None]
        return buffer[index] * (1 - frac) + buffer[np.minimum(index + 1, n - 1)] * frac


def whitening_matrix(windows: np.ndarray, floor: float = 1e-4) -> np.ndarray:
    """Euclidean alignment: a matrix that makes this person's average covariance look like I.

    Computed without labels, from a resting baseline, so each person starts from the same
    place. That is how a model pretrained on strangers can run on a new head, and it also
    makes the unit of the input irrelevant (volts and microvolts give the same result).
    Each window is trace-normalized first so one movement artifact cannot dominate.
    """
    x = np.asarray(windows, dtype=np.float64)
    x = x - x.mean(axis=-1, keepdims=True)
    covs = x @ x.transpose(0, 2, 1) / x.shape[-1]
    traces = np.trace(covs, axis1=1, axis2=2)
    keep = traces > 0
    if not keep.any():
        raise ValueError("Baseline windows are all flat. Is the stream actually carrying EEG?")
    mean_cov = (covs[keep] / traces[keep, None, None]).mean(axis=0) * np.median(traces[keep])
    values, vectors = np.linalg.eigh(mean_cov)
    # Common average reference removes one dimension, so floor the eigenvalues.
    values = np.maximum(values, values.max() * floor)
    return (vectors * values**-0.5) @ vectors.T


def apply_whitening(windows: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return (matrix @ np.asarray(windows, dtype=np.float64)).astype(np.float32)

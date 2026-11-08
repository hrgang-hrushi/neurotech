"""Signal stage: EEG channels -> one "key down" activation trace.

Steps (offline, zero-phase), run separately on every continuous segment
(eego writes one segment per pause/resume; filtering across a pause would
create fake spikes):
  1. drop bad channels (dead/high-impedance) from the reference and features
  2. pick the channels for the chosen movement (e.g. F9/F10/T7/T8 for clench)
  3. re-reference to the common average of the good scalp EEG channels
  4. notch mains interference, band-pass to the movement band
  5. square -> moving average -> log10 = log band-power envelope
     (or smoothed voltage minus a rolling-percentile baseline, for eye closures)
  6. average across the picked channels, flip the sign for ERD so that
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
settle_s_default = 2.5  # matches DetectConfig.settle_s


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


def pick_indices(rec_names: list[str], rec_types: list[str], cfg: FeatureConfig,
                 bad: list[str] | None = None,
                 noisy: list[str] | None = None) -> tuple[list[int], list[int]]:
    """Indices of the feature channels and of the good EEG channels (for CAR)."""
    bad_l = {b.lower() for b in (bad or [])}
    car_skip = bad_l | {n.lower() for n in (noisy or [])}
    idx, missing = resolve_channels(rec_names, cfg.channels)
    dropped = [rec_names[i] for i in idx if rec_names[i].lower() in bad_l]
    idx = [i for i in idx if rec_names[i].lower() not in bad_l]
    if not idx:
        raise ValueError(
            f"none of the channels {cfg.channels} are usable in this recording "
            f"(missing: {missing}, bad: {dropped}). Available: {rec_names}. "
            "Pass --channels with labels from your cap."
        )
    if missing:
        warnings.warn(f"channels not found and skipped: {missing}", stacklevel=2)
    if dropped:
        warnings.warn(f"bad channels skipped: {dropped}", stacklevel=2)
    eeg_idx = [i for i, t in enumerate(rec_types)
               if t == "eeg" and rec_names[i].lower() not in car_skip]
    return idx, eeg_idx


def find_bad_channels(rec: Recording, max_impedance_kohm: float = 1000.0,
                      max_ratio: float = 4.0, min_ratio: float = 0.2) -> tuple[list[str], list[str]]:
    """Return (bad, noisy).

    bad   = impedance above max_impedance_kohm (when the file has impedance
            checks) or flat: dropped everywhere.
    noisy = 1-40 Hz amplitude far above the other channels: kept out of the
            common average only (it may just be a channel full of blinks or EMG,
            which is exactly what the blink/clench presets want).
    """
    eeg = [i for i, t in enumerate(rec.ch_types) if t == "eeg"]
    if len(eeg) < 3:
        return [], []
    sos = sps.butter(4, [1.0, min(40.0, 0.45 * rec.sfreq)], "bandpass", fs=rec.sfreq, output="sos")
    amps = []
    skip = int(2 * rec.sfreq)
    for a, b in rec.segments:
        if b - a < 4 * rec.sfreq:
            continue
        x = sps.sosfiltfilt(sos, rec.data[eeg, a:b], axis=1)[:, skip:]
        amps.append(np.median(np.abs(x - np.median(x, axis=1, keepdims=True)), axis=1))
    bad, noisy = set(), set()
    if amps:
        amp = np.median(np.asarray(amps), axis=0)
        ratio = amp / max(np.median(amp), _TINY)
        bad |= {rec.ch_names[i] for i, r in zip(eeg, ratio) if r < min_ratio}
        noisy |= {rec.ch_names[i] for i, r in zip(eeg, ratio) if r > max_ratio}
    bad |= {c for c, z in rec.impedances.items() if z > max_impedance_kohm}
    return [c for c in rec.ch_names if c in bad], [c for c in rec.ch_names if c in noisy - bad]


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
    t: np.ndarray  # seconds (recording sample time), envelope time base
    values: np.ndarray  # activation (higher = key down)
    rate: float  # envelope sampling rate (Hz)
    channels: list[str]  # channels actually used
    filtered: np.ndarray  # band-passed signal of the used channels, full length (for plots)
    sfreq: float
    seg_slices: list[tuple[int, int]] | None = None  # [start, stop) envelope indices per segment

    def __post_init__(self) -> None:
        if self.seg_slices is None:
            self.seg_slices = [(0, int(self.values.size))]


def envelope(xf: np.ndarray, w: int, measure: str) -> np.ndarray:
    """Per-channel envelope: log10 moving-average power, or moving-average voltage."""
    if measure == "amplitude":
        return uniform_filter1d(xf, size=w, axis=1, mode="nearest")
    power = uniform_filter1d(xf**2, size=w, axis=1, mode="nearest")
    return np.log10(np.maximum(power, _TINY))


def channel_envelopes(rec: Recording, cfg: FeatureConfig, bad: list[str] | None = None):
    """Per-channel activation envelopes, computed segment by segment.

    Returns (env (n_ch, n_env), t, seg_slices, channel names, filtered full-length).
    """
    bad = rec.bad_channels if bad is None else bad
    idx, eeg_idx = pick_indices(rec.ch_names, rec.ch_types, cfg, bad, rec.noisy_channels)
    sos = design_filter(cfg.band, rec.sfreq, cfg.line_freq)
    w = max(1, int(round(cfg.smooth_s * rec.sfreq)))
    step = max(1, int(round(rec.sfreq / cfg.env_rate)))
    nb = max(3, int(round(cfg.baseline_s * rec.sfreq / step)))
    min_len = max(3 * 6 * len(sos), 2 * w)
    filtered = np.zeros((len(idx), rec.data.shape[1]))
    envs, times, slices, pos = [], [], [], 0
    for a, b in rec.segments:
        if b - a < min_len:
            continue  # too short to filter (e.g. a few samples between two checks)
        x = rec.data[idx, a:b]
        if cfg.reference == "car" and len(eeg_idx) >= 3:
            x = x - rec.data[eeg_idx, a:b].mean(axis=0, keepdims=True)
        x = x - np.median(x, axis=1, keepdims=True)  # eego is DC-coupled: remove the offset
        xf = sps.sosfiltfilt(sos, x, axis=1)
        filtered[:, a:b] = xf
        env = envelope(xf, w, cfg.measure)[:, ::step]
        if cfg.direction == "decrease":
            env = -env
        if cfg.measure == "amplitude":
            env = env - percentile_filter(env, cfg.baseline_pct, size=(1, nb), mode="nearest")
        elif cfg.normalize == "segment":
            # Contact (and so resting power) changes at every eego resume: express
            # each segment relative to its own resting level.
            settled = env[:, min(env.shape[1] - 1, int(settle_s_default * rec.sfreq / step)):]
            env = env - np.percentile(settled, cfg.baseline_pct, axis=1, keepdims=True)
        envs.append(env)
        times.append((a + np.arange(env.shape[1]) * step) / rec.sfreq)
        slices.append((pos, pos + env.shape[1]))
        pos += env.shape[1]
    if not envs:
        raise ValueError("recording too short to filter")
    return (np.concatenate(envs, axis=1), np.concatenate(times), slices,
            [rec.ch_names[i] for i in idx], filtered, rec.sfreq / step)


def activation(rec: Recording, cfg: FeatureConfig, bad: list[str] | None = None) -> Activation:
    env, t, slices, names, filtered, rate = channel_envelopes(rec, cfg, bad)
    return Activation(t, env.mean(axis=0), rate, names, filtered, rec.sfreq, slices)


def settled_mask(act_t: np.ndarray, slices: list[tuple[int, int]], rate: float,
                 settle_s: float, edge_s: float) -> np.ndarray:
    """True where the envelope is usable: not in a segment's settling start or last edge."""
    m = np.zeros(act_t.size, dtype=bool)
    s0, e0 = int(round(settle_s * rate)), int(round(edge_s * rate))
    for a, b in slices:
        if b - e0 > a + s0:
            m[a + s0: b - e0] = True
    return m if m.any() else np.ones(act_t.size, dtype=bool)


def channel_separability(rec: Recording, cfg: FeatureConfig, settle_s: float = 2.5,
                         bad: list[str] | None = None) -> list[tuple[str, float]]:
    """Otsu separability of each feature channel on its own, best first.

    A channel that carries the movement has two clear states (rest / active).
    Used by calibration to pick e.g. C3 for a right-hand mover and C4 for a
    left-hand mover without asking.
    """
    from .detect import otsu

    env, t, slices, names, _, rate = channel_envelopes(rec, cfg, bad)
    m = settled_mask(t, slices, rate, settle_s, 0.5)
    scores = [(n, otsu(e[m])[3]) for n, e in zip(names, env)]
    return sorted(scores, key=lambda s: -s[1])

"""Artifact handling for single-movement (jaw clench) decoding.

A jaw clench is broadband muscle (EMG) power, but so is the eyelid burst of a
blink, the spike potential of a saccade and the sharp edge of a dry-electrode
pop. On the first real eego recording the clench was strongest on frontal
sites (F3/F4/F7), exactly where blink EMG lands, so a plain band-power
detector turns blinks into dots and stretches dots that a blink lands on.

Blinks are frequent (every few seconds) and overlap clenches, so neither
avoiding channels nor vetoing whole key-downs works. Instead:

1. find eye events (frontopolar blink deflections, F7-F8 saccade steps) and
   electrode pops from the raw EEG, independently of the clench detector;
2. subtract eye EMG: each channel's band power holds a fixed fraction `g` of
   the frontopolar EMG power (one source near the eyes). `g` is the lower
   quartile of channel/frontopolar power rises at eye-event peaks, so peaks
   that coincide with a clench do not inflate it;
3. veto key-downs driven by a single popping electrode.

Everything runs per eego segment, like the rest of the offline pipeline.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass

import numpy as np
from scipy import signal as sps
from scipy.ndimage import median_filter, uniform_filter1d

from .config import FeatureConfig
from .detect import Segment
from .io import Recording
from .signal import Activation, design_filter, pick_indices, resolve_channels

FRONTOPOLAR = re.compile(r"^(FP\d*|FPZ|AF\d+|AFZ)$", re.IGNORECASE)
HEOG_PAIRS = (("F7", "F8"), ("F9", "F10"), ("FT7", "FT8"))
EYE_BAND_HZ = 8.0
EYE_BASELINE_S = 2.0
EYE_Z = 6.0  # robust z for a blink deflection / saccade step
POP_Z = 40.0  # robust z of a single-sample jump on one electrode
EVENT_PAD_S = 0.12
POP_TAIL_S = 0.6
MERGE_S = 0.1
MAD_TO_SD = 1.4826
REST_PCT = 25.0  # resting power = this percentile of a segment
GAIN_PCT = 25.0  # eye-EMG gain = this percentile of per-event rise ratios
MIN_EVENTS_FOR_GAIN = 3
RESIDUAL_FLOOR = 0.05  # cleaned relative power never drops below this
_TINY = np.finfo(np.float64).tiny


@dataclass(frozen=True)
class Artifact:
    t_on: float
    t_off: float
    kind: str  # "blink", "eye_movement", "electrode_pop"
    channel: str | None = None

    def overlap(self, a: float, b: float) -> float:
        return max(0.0, min(self.t_off, b) - max(self.t_on, a))


@dataclass(frozen=True)
class Vetoed:
    segment: Segment
    kind: str
    reason: str


def _robust_z(x: np.ndarray) -> np.ndarray:
    """(x - median) / robust SD. A channel that is mostly constant (clipped, held, quantised)
    has MAD 0; fall back to the mean absolute deviation instead of flagging everything."""
    med = np.median(x)
    dev = np.abs(x - med)
    scale = float(np.median(dev)) * MAD_TO_SD or float(np.mean(dev)) * MAD_TO_SD
    if not np.isfinite(scale) or scale <= 0:
        return np.zeros_like(x, dtype=float)
    return (x - med) / scale


def _intervals(mask: np.ndarray, t0: float, fs: float, pad_s: float) -> list[tuple[float, float]]:
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return [(t0 + a / fs - pad_s, t0 + b / fs + pad_s) for a, b in zip(starts, ends)]


def _merge(events: list[Artifact], gap_s: float = MERGE_S) -> list[Artifact]:
    out: list[Artifact] = []
    for e in sorted(events, key=lambda x: (x.kind, x.channel or "", x.t_on)):
        last = out[-1] if out else None
        if last and last.kind == e.kind and last.channel == e.channel and e.t_on - last.t_off <= gap_s:
            out[-1] = Artifact(last.t_on, max(last.t_off, e.t_off), e.kind, e.channel)
        else:
            out.append(e)
    return sorted(out, key=lambda x: x.t_on)


def _good_eeg(rec: Recording) -> list[int]:
    return [i for i, (c, t) in enumerate(zip(rec.ch_names, rec.ch_types))
            if t == "eeg" and c not in rec.bad_channels]


def frontopolar_channels(rec: Recording) -> list[str]:
    return [rec.ch_names[i] for i in _good_eeg(rec) if FRONTOPOLAR.match(rec.ch_names[i].strip())]


def _segment_lowpass(rec: Recording, idx: list[int], a: int, b: int) -> np.ndarray:
    sos = sps.butter(4, EYE_BAND_HZ, btype="lowpass", fs=rec.sfreq, output="sos")
    x = rec.data[idx, a:b]
    x = x - np.median(x, axis=1, keepdims=True)
    return sps.sosfiltfilt(sos, x, axis=1)


def _long_segments(rec: Recording) -> list[tuple[int, int]]:
    return [(a, b) for a, b in rec.segments if b - a >= int(4 * rec.sfreq)]


def detect_eye_events(rec: Recording) -> list[Artifact]:
    """Blinks (frontopolar deflections) and saccades (fast F7-F8 steps)."""
    good = set(_good_eeg(rec))
    fp, _ = resolve_channels(rec.ch_names, frontopolar_channels(rec))
    pairs = []
    for left, right in HEOG_PAIRS:
        (li, lm), (ri, rm) = resolve_channels(rec.ch_names, [left]), resolve_channels(rec.ch_names, [right])
        if not lm and not rm and li[0] in good and ri[0] in good:
            pairs.append((li[0], ri[0]))
    events: list[Artifact] = []
    win = max(3, int(EYE_BASELINE_S * rec.sfreq) | 1)
    for a, b in _long_segments(rec):
        t0 = a / rec.sfreq
        if fp:
            x = _segment_lowpass(rec, fp, a, b).mean(axis=0)
            dev = np.abs(x - median_filter(x, size=win, mode="nearest"))
            events += [Artifact(on, off, "blink")
                       for on, off in _intervals(_robust_z(dev) > EYE_Z, t0, rec.sfreq, EVENT_PAD_S)]
        for li, ri in pairs[:1]:
            h = _segment_lowpass(rec, [li, ri], a, b)
            speed = np.abs(np.gradient(h[0] - h[1]))
            events += [Artifact(on, off, "eye_movement")
                       for on, off in _intervals(_robust_z(speed) > EYE_Z, t0, rec.sfreq, EVENT_PAD_S)]
    return _merge(events)


def detect_pops(rec: Recording) -> list[Artifact]:
    """Single-electrode jumps far larger than that electrode's sample-to-sample noise."""
    events: list[Artifact] = []
    eeg = _good_eeg(rec)
    for a, b in _long_segments(rec):
        dx = np.abs(np.diff(rec.data[eeg, a:b], axis=1))
        for row, i in enumerate(eeg):
            for k in np.flatnonzero(_robust_z(dx[row]) > POP_Z):
                t = (a + k) / rec.sfreq
                events.append(Artifact(t - 0.05, t + POP_TAIL_S, "electrode_pop", rec.ch_names[i]))
    return _merge(events, gap_s=POP_TAIL_S)


def event_mask(t: np.ndarray, events: list[Artifact]) -> np.ndarray:
    m = np.zeros(t.size, dtype=bool)
    for e in events:
        m |= (t >= e.t_on) & (t <= e.t_off)
    return m


@dataclass(frozen=True)
class BandPower:
    """Relative band power (1 = segment's resting level), envelope rate."""
    power: np.ndarray  # (n_ch, n_env)
    t: np.ndarray
    slices: list[tuple[int, int]]
    names: list[str]
    filtered: np.ndarray  # band-passed signal, full length (for plots)
    rate: float


def band_power(rec: Recording, cfg: FeatureConfig, car: bool) -> BandPower:
    """Per-channel moving-average band power, each segment divided by its resting level."""
    idx, eeg_idx = pick_indices(rec.ch_names, rec.ch_types, cfg, rec.bad_channels, rec.noisy_channels)
    sos = design_filter(cfg.band, rec.sfreq, cfg.line_freq)
    w = max(1, int(round(cfg.smooth_s * rec.sfreq)))
    step = max(1, int(round(rec.sfreq / cfg.env_rate)))
    min_len = max(3 * 6 * len(sos), 2 * w)
    filtered = np.zeros((len(idx), rec.data.shape[1]))
    powers, times, slices, pos = [], [], [], 0
    for a, b in rec.segments:
        if b - a < min_len:
            continue
        x = rec.data[idx, a:b]
        if car and len(eeg_idx) >= 3:
            x = x - rec.data[eeg_idx, a:b].mean(axis=0, keepdims=True)
        x = x - np.median(x, axis=1, keepdims=True)
        xf = sps.sosfiltfilt(sos, x, axis=1)
        filtered[:, a:b] = xf
        p = uniform_filter1d(xf**2, size=w, axis=1, mode="nearest")[:, ::step]
        p = p / np.maximum(np.percentile(p, REST_PCT, axis=1, keepdims=True), _TINY)
        powers.append(p)
        times.append((a + np.arange(p.shape[1]) * step) / rec.sfreq)
        slices.append((pos, pos + p.shape[1]))
        pos += p.shape[1]
    if not powers:
        raise ValueError("recording too short to filter")
    return BandPower(np.concatenate(powers, axis=1), np.concatenate(times), slices,
                     [rec.ch_names[i] for i in idx], filtered, rec.sfreq / step)


def eye_emg_gain(power: np.ndarray, fp: np.ndarray, t: np.ndarray,
                 eye: list[Artifact]) -> np.ndarray:
    """Per-channel fraction of frontopolar EMG power that leaks into each channel."""
    ratios = []
    for e in eye:
        m = np.flatnonzero((t >= e.t_on) & (t <= e.t_off))
        if m.size == 0:
            continue
        k = m[np.argmax(fp[m])]
        fp_rise = fp[k] - 1.0
        if fp_rise > 1.0:  # at least doubles: a real eye-EMG burst
            ratios.append(np.maximum(power[:, k] - 1.0, 0.0) / fp_rise)
    if len(ratios) < MIN_EVENTS_FOR_GAIN:
        return np.zeros(power.shape[0])
    return np.percentile(np.asarray(ratios), GAIN_PCT, axis=0)


@dataclass(frozen=True)
class CleanEnvelopes:
    env: np.ndarray  # (n_ch, n_env) log10 relative power after cleaning
    bp: BandPower
    gain: dict[str, float]
    frontopolar: list[str]


def _patch_pops(env: np.ndarray, t: np.ndarray, names: list[str],
                pops: list[Artifact]) -> np.ndarray:
    """Replace a popping channel's envelope by the median of the other channels."""
    if len(names) < 2:
        return env
    out = env.copy()
    lookup = {n.lower(): i for i, n in enumerate(names)}
    for p in pops:
        i = lookup.get((p.channel or "").lower())
        if i is None:
            continue
        m = (t >= p.t_on) & (t <= p.t_off)
        others = np.delete(env, i, axis=0)
        out[i, m] = np.median(others[:, m], axis=0)
    return out


def clean_envelopes(rec: Recording, cfg: FeatureConfig, eye: list[Artifact],
                    pops: list[Artifact]) -> CleanEnvelopes:
    """Per-channel clench envelopes with eye EMG regressed out and pops patched."""
    bp = band_power(rec, cfg, car=cfg.reference == "car")
    fp_names = frontopolar_channels(rec)
    gain = np.zeros(len(bp.names))
    power = bp.power
    if fp_names and eye:
        fcfg = copy.deepcopy(cfg)
        fcfg.channels = fp_names
        fp = band_power(rec, fcfg, car=False)  # CAR would leak clench EMG into Fp
        if fp.power.shape[1] == power.shape[1]:
            fp_rise = np.maximum(fp.power.mean(axis=0) - 1.0, 0.0)
            gain = eye_emg_gain(power, fp.power.mean(axis=0), bp.t, eye)
            power = power - gain[:, None] * fp_rise[None, :]
    env = np.log10(np.maximum(power, RESIDUAL_FLOOR))
    env = _patch_pops(env, bp.t, bp.names, pops)
    return CleanEnvelopes(env, bp, {n: round(float(g), 4) for n, g in zip(bp.names, gain)}, fp_names)


def to_activation(ce: CleanEnvelopes, rows: list[int], sfreq: float) -> Activation:
    bp = ce.bp
    return Activation(bp.t, ce.env[rows].mean(axis=0), bp.rate, [bp.names[i] for i in rows],
                      bp.filtered[rows], sfreq, bp.slices)


def candidate_channels(rec: Recording, wanted: list[str]) -> list[str]:
    """Wanted channels present and usable, minus frontopolar sites (eye-dominated)."""
    idx, _ = resolve_channels(rec.ch_names, wanted)
    return [rec.ch_names[i] for i in idx
            if not FRONTOPOLAR.match(rec.ch_names[i].strip()) and rec.ch_names[i] not in rec.bad_channels]

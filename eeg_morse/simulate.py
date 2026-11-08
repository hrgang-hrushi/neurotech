"""Synthetic eego-like recordings that encode a known Morse message.

SIMULATED DATA ONLY. This exists so the pipeline can be developed, tested and
demoed before real recordings are available. The effects are modelled on
textbook descriptions (mu/beta ERD with onset lag and beta rebound, EMG bursts
for jaw clench, frontal EOG deflections for eye closure) and are cleaner than a
real single-trial recording. Never present simulated output as a live result.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal as sps

from . import morse
from .io import Recording

# ANT Neuro waveguard 32-channel layout used with eego amplifiers.
EEGO_32 = ["Fp1", "Fpz", "Fp2", "F7", "F3", "Fz", "F4", "F8", "FC5", "FC1", "FC2", "FC6",
           "M1", "T7", "C3", "Cz", "C4", "T8", "M2", "CP5", "CP1", "CP2", "CP6", "P7", "P3",
           "Pz", "P4", "P8", "POz", "O1", "Oz", "O2"]

# Spatial weights of each source (others get the default).
MU_WEIGHT = {"C3": 1.0, "FC1": 0.6, "CP1": 0.6, "Cz": 0.6, "FC5": 0.5, "CP5": 0.5,
             "C4": 0.8, "FC2": 0.5, "CP2": 0.5, "FC6": 0.4, "CP6": 0.4}
ERD_DEPTH = {"C3": 0.75, "FC1": 0.6, "CP1": 0.6, "Cz": 0.55, "FC5": 0.5, "CP5": 0.5,
             "C4": 0.4, "FC2": 0.35, "CP2": 0.35}  # right-hand movement: left (C3) strongest
EMG_WEIGHT = {"T7": 1.0, "T8": 1.0, "M1": 0.8, "M2": 0.8, "F7": 0.4, "F8": 0.4,
              "FC5": 0.3, "FC6": 0.3, "CP5": 0.25, "CP6": 0.25, "P7": 0.3, "P8": 0.3}
EOG_WEIGHT = {"Fp1": 1.0, "Fp2": 1.0, "Fpz": 1.0, "F7": 0.45, "F3": 0.4, "Fz": 0.4,
              "F4": 0.4, "F8": 0.45, "FC1": 0.15, "FC2": 0.15}


@dataclass
class Truth:
    message: str
    t_on: np.ndarray
    t_off: np.ndarray
    symbols: list[str]
    unit_s: float


def schedule(text: str, unit_s: float, jitter: float, rng: np.random.Generator,
             lead_s: float, tail_s: float) -> tuple[Truth, float]:
    """Key-down times for `text` with human-like timing jitter."""
    def j(x: float) -> float:
        return x * float(np.exp(rng.normal(0, jitter)))

    t = lead_s
    on, off, syms = [], [], []
    words = morse.encode(text)
    for wi, word in enumerate(words):
        for li, code in enumerate(word):
            for ei, s in enumerate(code):
                d = j(unit_s * (1 if s == "." else 3))
                on.append(t)
                off.append(t + d)
                syms.append(s)
                t += d
                if ei < len(code) - 1:
                    t += j(unit_s)
            if li < len(word) - 1:
                t += j(3 * unit_s)
        if wi < len(words) - 1:
            t += j(7 * unit_s)
    msg = " ".join("".join(morse.CODE_TO_CHAR[c] for c in w) for w in words)
    return Truth(msg, np.array(on), np.array(off), syms, unit_s), t + tail_s


def _pink(n_ch: int, n: int, rng: np.random.Generator) -> np.ndarray:
    f = np.fft.rfftfreq(n)
    f[0] = f[1]
    spec = (rng.normal(size=(n_ch, f.size)) + 1j * rng.normal(size=(n_ch, f.size))) / np.sqrt(f)
    x = np.fft.irfft(spec, n=n, axis=1)
    return x / x.std(axis=1, keepdims=True)


def _narrowband(n_ch: int, n: int, lo: float, hi: float, fs: float,
                rng: np.random.Generator) -> np.ndarray:
    sos = sps.butter(4, [lo, hi], btype="bandpass", fs=fs, output="sos")
    x = sps.sosfiltfilt(sos, rng.normal(size=(n_ch, n)), axis=1)
    return x / x.std(axis=1, keepdims=True)


def _smooth_step(k: np.ndarray, fs: float, lag_s: float, tau_s: float) -> np.ndarray:
    """Delay a 0/1 indicator by lag_s and pass it through a 1st-order lag."""
    shift = int(round(lag_s * fs))
    k = np.concatenate([np.zeros(shift), k[: k.size - shift]]) if shift else k
    if tau_s <= 0:
        return k
    a = np.exp(-1.0 / (tau_s * fs))
    return sps.lfilter([1 - a], [1, -a], k)


def simulate(text: str = "SOS", preset: str = "motor", sfreq: float = 500.0,
             unit_s: float | None = None, jitter: float = 0.12, noise: float = 1.0,
             line_freq: float = 60.0, seed: int = 0, lead_s: float = 6.0,
             tail_s: float = 4.0, channels: list[str] | None = None) -> tuple[Recording, Truth]:
    """Return a Recording (microvolts) plus the ground-truth key timeline."""
    rng = np.random.default_rng(seed)
    unit_s = unit_s or {"motor": 1.0, "clench": 0.3, "blink": 0.4}[preset]
    truth, dur = schedule(text, unit_s, jitter, rng, lead_s, tail_s)
    names = channels or EEGO_32
    n = int(round(dur * sfreq))
    t = np.arange(n) / sfreq
    key = np.zeros(n)
    for a, b in zip(truth.t_on, truth.t_off):
        key[int(a * sfreq): int(b * sfreq)] = 1.0

    def w(table: dict, default: float) -> np.ndarray:
        return np.array([table.get(c, default) for c in names])[:, None]

    n_ch = len(names)
    x = 8.0 * noise * _pink(n_ch, n, rng)  # background ~8 uV rms
    # posterior alpha (not movement related)
    occ = np.array([1.0 if c in ("O1", "O2", "Oz", "POz", "Pz", "P3", "P4") else 0.2 for c in names])[:, None]
    x += 6.0 * occ * _narrowband(n_ch, n, 9.0, 11.5, sfreq, rng)
    # sensorimotor mu + beta, suppressed during movement (ERD), beta rebound after
    mu = _narrowband(n_ch, n, 9.5, 12.5, sfreq, rng)
    beta = _narrowband(n_ch, n, 17.0, 24.0, sfreq, rng)
    mu_w, depth = w(MU_WEIGHT, 0.15), w(ERD_DEPTH, 0.05)
    if preset == "motor":
        erd = _smooth_step(key, sfreq, lag_s=0.2, tau_s=0.25)[None, :]
        release = np.clip(-np.diff(key, prepend=0), 0, None)
        kern_t = np.arange(int(1.5 * sfreq)) / sfreq
        rebound = np.convolve(release, (kern_t / 0.3) * np.exp(1 - kern_t / 0.3))[:n]
        x += 9.0 * mu_w * (1 - depth * erd) * mu
        x += 4.0 * mu_w * (1 - depth * erd) * (1 + 0.35 * rebound[None, :]) * beta
    else:
        x += 9.0 * mu_w * mu + 4.0 * mu_w * beta
    if preset == "clench":
        emg = _narrowband(n_ch, n, 25.0, min(200.0, 0.45 * sfreq), sfreq, rng)
        env = _smooth_step(key, sfreq, lag_s=0.03, tau_s=0.03)[None, :]
        x += 25.0 * w(EMG_WEIGHT, 0.05) * env * emg
    if preset == "blink":
        env = _smooth_step(key, sfreq, lag_s=0.05, tau_s=0.04)
        x += 140.0 * w(EOG_WEIGHT, 0.02) * env[None, :]
    # spontaneous blinks (artifacts the decoder must survive), ~1 per 8 s
    for tb in np.cumsum(rng.exponential(8.0, size=int(dur / 4) + 2)):
        if tb >= dur or preset == "blink":
            continue
        x += 90.0 * w(EOG_WEIGHT, 0.02) * np.exp(-0.5 * ((t - tb) / 0.07) ** 2)[None, :]
    # slow drift + mains interference with per-channel amplitude
    x += 15.0 * _narrowband(n_ch, n, 0.02, 0.3, sfreq, rng) if dur > 60 else 0.0
    if line_freq:
        amp = rng.uniform(1.0, 6.0, size=(n_ch, 1))
        x += amp * np.sin(2 * np.pi * line_freq * t + rng.uniform(0, 2 * np.pi))[None, :]
    rec = Recording(x, sfreq, list(names), source=f"simulated:{preset}:{text!r}:seed{seed}")
    rec.events = [(float(a), "key_down") for a in truth.t_on]
    return rec, truth

"""Shared fakes: synthetic EEG with a known signal strength, and a capture with no LSL."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from eegmove.record import write_recording

CHANNELS_24 = ["Fp1", "Fpz", "Fp2", "F7", "F3", "Fz", "F4", "F8", "FC5", "FC1", "FC2", "FC6",
               "T7", "C3", "C4", "T8", "CP5", "CP1", "CP2", "CP6", "P3", "Pz", "P4", "POz"]


class FakeInlet:
    def __init__(self, channels=("C3", "C4"), sfreq=160.0, chunks=()):
        self.channels, self.sfreq = list(channels), sfreq
        self.source = "eeg"
        self.chunks = list(chunks)

    def pull(self, timeout=0.1):
        if self.chunks:
            return self.chunks.pop(0)
        return np.empty((0, len(self.channels))), np.empty(0)


class FakeCapture:
    """Stands in for record.Capture: already holds samples and never touches LSL."""

    def __init__(self, stream=None, inlet=None, snapshot=None, seconds=10.0):
        self.inlet = inlet or FakeInlet()
        n = int(seconds * self.inlet.sfreq)
        self.chunks = [np.zeros((n, len(self.inlet.channels)))]
        self.stamps = [np.arange(n) / self.inlet.sfreq]
        self.running, self.error = True, None
        self.snapshot = snapshot

    def start(self):
        pass

    def join(self, timeout=None):
        self.running = False

    def set_session(self, cues, lsl_t0, movement):
        pass

    def drain(self):
        return np.concatenate(self.chunks), np.concatenate(self.stamps)


def motor_recording(strength: float, seed: int = 0, per_class: int = 24, channels=("C3", "C4", "Fz", "Pz"),
                    sfreq: float = 160.0, cue_s: float = 4.0, gap_s: float = 2.0,
                    baseline_s: float = 30.0):
    """Continuous EEG with rest/left/right cues and a lateralized 12 Hz drop of `strength`.

    strength 0 means the cues change nothing, so it is noise with cue labels. Slow gain drift
    keeps the noise non-stationary, like a real session.
    """
    rng = np.random.default_rng(seed)
    labels = ["rest", "left", "right"] * per_class
    rng.shuffle(labels)
    cues = [{"onset_s": 0.0, "duration_s": baseline_s, "label": "baseline"}]
    clock = baseline_s + 1.0
    for label in labels:
        cues.append({"onset_s": clock, "duration_s": cue_s, "label": label})
        clock += cue_s + gap_s
    n = int((clock + 2) * sfreq)
    t = np.arange(n) / sfreq
    eeg = rng.normal(0, 0.6, size=(n, len(channels)))
    drift = 1 + 0.25 * np.sin(2 * np.pi * t / 90 + rng.uniform(0, 6))
    amplitude = np.ones((n, 2))
    for cue in cues[1:]:
        start, stop = int(cue["onset_s"] * sfreq), int((cue["onset_s"] + cue_s) * sfreq)
        if cue["label"] == "left":
            amplitude[start:stop, 1] = 1 - strength  # left hand: right-hemisphere C4 drops
        elif cue["label"] == "right":
            amplitude[start:stop, 0] = 1 - strength
    for i in range(2):
        phase = np.cumsum(2 * np.pi * (12 + 0.3 * rng.normal(size=n)) / sfreq)
        eeg[:, i] += 2 * amplitude[:, i] * drift * np.sin(phase)
    return eeg, t, cues, list(channels), sfreq


def write_motor_recording(path: Path, strength: float, seed: int = 0, movement: str = "imagined",
                          **kwargs) -> Path:
    eeg, t, cues, channels, sfreq = motor_recording(strength, seed, **kwargs)
    return write_recording(path, eeg, t + 100.0, sfreq, channels, cues, 100.0, movement)

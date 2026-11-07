"""LSL input, plus a replay outlet that imitates the eego stream with no headset.

The docs we were given don't describe the eego stream: its name, units and any extra
channels are all unknown. So this reader finds channels by label, ignores non-EEG
channels, and prints what it found. Its input units don't matter (see whitening_matrix).
"""

from __future__ import annotations

import re
import time

import numpy as np
import pylsl

from .config import normalize_label

NON_EEG = re.compile(r"^(trigger|trg|counter|sample|bip|aux|status|stim)", re.IGNORECASE)


def stream_labels(info: pylsl.StreamInfo) -> list[str]:
    labels = []
    channel = info.desc().child("channels").child("channel")
    for _ in range(info.channel_count()):
        label = channel.child_value("label")
        if not label:
            return []
        labels.append(label)
        channel = channel.next_sibling()
    return labels


def match_channels(labels: list[str], wanted: list[str]) -> tuple[list[int], list[str]]:
    """Find `wanted` in a stream's labels. Returns (indices, labels that are missing)."""
    lookup = {normalize_label(name): i for i, name in enumerate(labels)
              if not NON_EEG.match(name)}
    found = [lookup[normalize_label(c)] for c in wanted if normalize_label(c) in lookup]
    missing = [c for c in wanted if normalize_label(c) not in lookup]
    return found, missing


class EegInlet:
    """Connect to the first EEG stream and return samples in the requested channel order."""

    def __init__(self, channels: list[str] | None = None, name: str | None = None,
                 timeout: float = 15.0):
        prop, value = ("name", name) if name else ("type", "EEG")
        print(f"Looking for an LSL stream with {prop}={value} ...")
        found = pylsl.resolve_byprop(prop, value, timeout=timeout)
        if not found:
            raise TimeoutError(
                "No LSL stream found. On the ANT router: join the ANT network, allow Local "
                "Network access for your terminal in macOS Privacy settings, and if it still "
                "fails copy lsl_api.cfg.example to lsl_api.cfg with the ANT laptop's IP."
            )
        self.inlet = pylsl.StreamInlet(found[0], max_buflen=30, recover=True,
                                       processing_flags=pylsl.proc_clocksync | pylsl.proc_dejitter)
        info = self.inlet.info(timeout=timeout)
        self.sfreq = float(info.nominal_srate())
        self.labels = stream_labels(info)
        print(f"Connected: name={info.name()!r} type={info.type()!r} channels="
              f"{info.channel_count()} rate={self.sfreq} Hz format={info.channel_format()}")
        print(f"Labels: {self.labels or 'none in the stream metadata'}")
        if self.sfreq <= 0:
            raise ValueError("Stream reports no sample rate, so it can't be filtered correctly.")

        if channels is None:
            self.picks = [i for i, name in enumerate(self.labels) if not NON_EEG.match(name)] \
                or list(range(info.channel_count()))
        elif self.labels:
            self.picks, missing = match_channels(self.labels, channels)
            if missing:
                raise ValueError(f"Model needs channels the stream lacks: {missing}. "
                                 "Rerun: eegmove pretrain --montage-from <recording>")
        else:
            print("WARNING: no channel labels, so assuming they arrive in the model's order.")
            self.picks = list(range(len(channels)))
        self.channels = list(channels) if channels else (
            [self.labels[i] for i in self.picks] if self.labels
            else [f"ch{i}" for i in self.picks])

    def pull(self, timeout: float = 0.1) -> tuple[np.ndarray, np.ndarray]:
        """Return (samples, timestamps); samples are (n_samples, n_channels)."""
        samples, stamps = self.inlet.pull_chunk(timeout=timeout)
        if not samples:
            return np.empty((0, len(self.picks))), np.empty(0)
        return np.asarray(samples, dtype=np.float64)[:, self.picks], np.asarray(stamps)


def make_outlet(name: str, labels: list[str], sfreq: float) -> pylsl.StreamOutlet:
    info = pylsl.StreamInfo(name, "EEG", len(labels), sfreq, pylsl.cf_float32, f"{name}-replay")
    channels = info.desc().append_child("channels")
    for label in labels:
        channels.append_child("channel").append_child_value("label", label)
    return pylsl.StreamOutlet(info, chunk_size=16)


def replay(signal: np.ndarray, labels: list[str], sfreq: float, name: str = "eego-replay",
           loops: int = 0) -> None:
    """Push (n_samples, n_channels) in real time. loops=0 repeats until interrupted."""
    outlet = make_outlet(name, labels, sfreq)
    chunk = max(1, int(sfreq / 32))
    print(f"Streaming {name!r}: {len(labels)} channels at {sfreq} Hz. Ctrl-C stops it.")
    played = 0
    while loops == 0 or played < loops:
        start = pylsl.local_clock()
        for sent in range(0, len(signal), chunk):
            outlet.push_chunk(signal[sent:sent + chunk].tolist())
            delay = start + (sent + chunk) / sfreq - pylsl.local_clock()
            if delay > 0:
                time.sleep(delay)
        played += 1


def physionet_replay_signal(subject: int, run: int, sfreq_out: float, units: str = "uV",
                            extra_channels: bool = True):
    """Build a stream shaped like our best guess of eego: fast, labelled, with junk channels.

    Upsampling exercises the resampler, and the trigger and counter channels check that
    non-EEG channels really are ignored.
    """
    import mne
    from mne.datasets import eegbci
    from scipy.signal import resample_poly

    from .config import DATA_DIR

    path = eegbci.load_data(subject, [run], path=str(DATA_DIR / "mne"), update_path=False,
                            verbose="ERROR")[0]
    raw = mne.io.read_raw_edf(path, preload=True, verbose="ERROR")
    eegbci.standardize(raw)
    signal = raw.get_data().T * (1e6 if units == "uV" else 1.0)
    up = int(round(sfreq_out))
    down = int(round(raw.info["sfreq"]))
    if up != down:
        signal = resample_poly(signal, up, down, axis=0)
    labels = list(raw.ch_names)
    if extra_channels:
        counter = np.arange(len(signal), dtype=float)[:, None]
        signal = np.hstack([signal, np.zeros_like(counter), counter])
        labels += ["TRIGGER", "COUNTER"]
    return signal, labels

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


def stream_channel_field(info: pylsl.StreamInfo, field: str) -> list[str]:
    values = []
    channel = info.desc().child("channels").child("channel")
    for _ in range(info.channel_count()):
        values.append(channel.child_value(field).strip())
        channel = channel.next_sibling()
    return values


def stream_labels(info: pylsl.StreamInfo) -> list[str]:
    labels = stream_channel_field(info, "label")
    return labels if all(labels) else []


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
                 timeout: float = 15.0, *, dejitter: bool = True):
        prop, value = ("name", name) if name else ("type", "EEG")
        print(f"Looking for an LSL stream with {prop}={value} ...")
        found = pylsl.resolve_byprop(prop, value, timeout=timeout)
        if not found:
            raise TimeoutError(
                "No LSL stream found. On the ANT router: join the ANT network, allow Local "
                "Network access for your terminal in macOS Privacy settings, and if it still "
                "fails copy lsl_api.cfg.example to lsl_api.cfg with the ANT laptop's IP."
            )
        processing_flags = pylsl.proc_clocksync | (pylsl.proc_dejitter if dejitter else 0)
        self.inlet = pylsl.StreamInlet(found[0], max_buflen=30, recover=True,
                                       processing_flags=processing_flags)
        info = self.inlet.info(timeout=timeout)
        self.name = info.name()
        self.source_id = info.source_id()
        self.is_replay = self.source_id.endswith("-replay")
        self.uid = info.uid()
        self.sfreq = float(info.nominal_srate())
        labels = stream_channel_field(info, "label")
        self.labels = stream_labels(info)
        self.source = "replay" if self.is_replay else "eeg"
        print(f"Connected: name={info.name()!r} type={info.type()!r} channels="
              f"{info.channel_count()} rate={self.sfreq} Hz format={info.channel_format()}")
        print(f"Labels: {self.labels or 'none in the stream metadata'}")
        if not np.isfinite(self.sfreq) or self.sfreq <= 0:
            raise ValueError("Stream reports no sample rate, so it can't be filtered correctly.")

        if channels is None:
            types = stream_channel_field(info, "type")
            self.picks = [i for i, (label, kind) in enumerate(zip(labels, types))
                          if not NON_EEG.match(label) and not NON_EEG.match(kind)]
            if not self.picks:
                raise ValueError("The stream has no EEG channels in its channel metadata.")
        elif self.labels:
            self.picks, missing = match_channels(self.labels, channels)
            if missing:
                raise ValueError(f"Model needs channels the stream lacks: {missing}. "
                                 "Rerun: eegmove pretrain --montage-from <recording>")
        else:
            if len(channels) > info.channel_count():
                raise ValueError("The unlabeled stream has fewer channels than the model needs.")
            print("WARNING: no channel labels, so assuming they arrive in the model's order.")
            self.picks = list(range(len(channels)))
        self.channels = list(channels) if channels else [labels[i] or f"ch{i}" for i in self.picks]
        units = stream_channel_field(info, "unit")
        self.units = [units[i] or None for i in self.picks]

    def flush(self) -> None:
        """Drop buffered samples, so the next data is from now and not the last 30 seconds."""
        self.inlet.flush()

    def pull(self, timeout: float = 0.1) -> tuple[np.ndarray, np.ndarray]:
        """Return (samples, timestamps); samples are (n_samples, n_channels)."""
        samples, stamps = self.inlet.pull_chunk(timeout=timeout)
        if not samples:
            return np.empty((0, len(self.picks))), np.empty(0)
        return np.asarray(samples, dtype=np.float64)[:, self.picks], np.asarray(stamps)


def make_outlet(name: str, labels: list[str], sfreq: float,
                units: list[str | None] | None = None) -> pylsl.StreamOutlet:
    info = pylsl.StreamInfo(name, "EEG", len(labels), sfreq, pylsl.cf_float32, f"{name}-replay")
    channels = info.desc().append_child("channels")
    for index, label in enumerate(labels):
        channel = channels.append_child("channel")
        channel.append_child_value("label", label)
        if units is not None and units[index]:
            channel.append_child_value("unit", units[index])
    return pylsl.StreamOutlet(info, chunk_size=16)


def replay(signal: np.ndarray, labels: list[str], sfreq: float, name: str = "eego-replay",
           loops: int = 0, units: list[str | None] | None = None) -> None:
    """Push (n_samples, n_channels) in real time. loops=0 repeats until interrupted."""
    outlet = make_outlet(name, labels, sfreq, units)
    chunk = max(1, int(sfreq / 32))
    print(f"Streaming {name!r}: {len(labels)} channels at {sfreq} Hz. Ctrl-C stops it.")
    played = 0
    start = pylsl.local_clock()
    sent = 0
    while loops == 0 or played < loops:
        for offset in range(0, len(signal), chunk):
            samples = signal[offset:offset + chunk]
            sent += len(samples)
            timestamp = start + (sent - 1) / sfreq
            delay = timestamp - pylsl.local_clock()
            if delay > 0:
                time.sleep(delay)
            # Anchor the final sample in each chunk to acquisition time, not send jitter.
            outlet.push_chunk(samples.tolist(), timestamp=timestamp)
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

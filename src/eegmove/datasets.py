"""Turn PhysioNet and team recordings into the same labelled windows."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import DATA_DIR, SignalConfig, normalize_label
from .preprocess import StreamPreprocessor

# PhysioNet EEG Motor Movement/Imagery runs (https://physionet.org/content/eegmmidb/1.0.0/)
EXECUTED_RUNS = {3: "lr", 5: "ff", 7: "lr", 9: "ff", 11: "lr", 13: "ff"}
IMAGINED_RUNS = {4: "lr", 6: "ff", 8: "lr", 10: "ff", 12: "lr", 14: "ff"}
RUN_EVENTS = {"lr": {"T0": "rest", "T1": "left", "T2": "right"},
              "ff": {"T0": "rest", "T1": "both", "T2": "feet"}}
# Recordings commonly excluded for a different sample rate or a broken run.
BAD_SUBJECTS = {38, 88, 89, 92, 100, 104}
ALL_SUBJECTS = [s for s in range(1, 110) if s not in BAD_SUBJECTS]

CUE_OFFSET_S = 0.5  # skip reaction time at the start of each cue
CROP_STRIDE_S = 0.5


@dataclass
class Windows:
    X: np.ndarray  # (n_windows, n_channels, n_times)
    y: np.ndarray
    trial: np.ndarray  # windows sharing an id came from one cue, so never split them
    subject: np.ndarray
    channels: list[str]
    classes: list[str]

    def __len__(self) -> int:
        return len(self.y)

    def select(self, mask: np.ndarray) -> "Windows":
        return Windows(self.X[mask], self.y[mask], self.trial[mask], self.subject[mask],
                       self.channels, self.classes)


def cut_trials(signal: np.ndarray, events: list[tuple[float, float, str]], classes: list[str],
               cfg: SignalConfig, first_trial: int = 0):
    """Slice (n_samples, n_channels) into windows from (onset_s, duration_s, label) events."""
    xs, ys, trials = [], [], []
    size = cfg.n_times
    stride = int(round(CROP_STRIDE_S * cfg.sfreq))
    for i, (onset, duration, label) in enumerate(events):
        if label not in classes:
            continue
        start = int(round((onset + CUE_OFFSET_S) * cfg.sfreq))
        # min(): a session cut short leaves cues running past the end of the data.
        stop = min(int(round((onset + duration) * cfg.sfreq)), len(signal))
        for begin in range(start, stop - size + 1, stride):
            xs.append(signal[begin:begin + size].T)
            ys.append(classes.index(label))
            trials.append(first_trial + i)
    if not xs:
        return np.empty((0, signal.shape[1], size), np.float32), np.empty(0, int), np.empty(0, int)
    return np.asarray(xs, np.float32), np.asarray(ys), np.asarray(trials)


def _physionet_channel_picks(raw_names: list[str], channels: list[str]) -> list[str]:
    available = {normalize_label(name): name for name in raw_names}
    missing = [c for c in channels if normalize_label(c) not in available]
    if missing:
        raise ValueError(f"Not in PhysioNet's 64 channels: {missing}")
    return [available[normalize_label(c)] for c in channels]


def _load_physionet_subject(subject: int, runs: dict[int, str], channels: list[str],
                            classes: list[str], cfg: SignalConfig):
    import mne
    from mne.datasets import eegbci

    xs, ys, trials = [], [], []
    next_trial = 0
    for run, kind in runs.items():
        path = eegbci.load_data(subject, [run], path=str(DATA_DIR / "mne"), update_path=False,
                                verbose="ERROR")[0]
        raw = mne.io.read_raw_edf(path, preload=True, verbose="ERROR")
        eegbci.standardize(raw)
        if not np.isclose(raw.info["sfreq"], cfg.sfreq):
            continue
        picks = _physionet_channel_picks(raw.ch_names, channels)
        signal = raw.get_data(picks=picks).T * 1e6
        filtered = StreamPreprocessor(cfg.sfreq, len(channels), cfg).process(signal)
        events = [(a["onset"], a["duration"], RUN_EVENTS[kind].get(a["description"], ""))
                  for a in raw.annotations]
        x, y, trial = cut_trials(filtered, events, classes, cfg, next_trial)
        next_trial += len(events)
        xs.append(x), ys.append(y), trials.append(trial)
    return np.concatenate(xs), np.concatenate(ys), np.concatenate(trials)


def _cache_key(channels: list[str], classes: list[str], cfg: SignalConfig, runs: dict) -> str:
    return hashlib.sha1(json.dumps([channels, classes, cfg.to_dict(), sorted(runs)],
                                   sort_keys=True).encode()).hexdigest()[:10]


def load_physionet(subjects: list[int], channels: list[str], classes: list[str],
                   cfg: SignalConfig, include_imagined: bool = False,
                   imagined_only: bool = False) -> Windows:
    """Load subjects into windows, caching each one because EDF parsing is the slow part."""
    runs = dict(IMAGINED_RUNS) if imagined_only else dict(EXECUTED_RUNS)
    if include_imagined:
        runs |= IMAGINED_RUNS
    cache = DATA_DIR / "cache" / _cache_key(channels, classes, cfg, runs)
    cache.mkdir(parents=True, exist_ok=True)

    Xs, ys, trials, owners = [], [], [], []
    for subject in subjects:
        file = cache / f"s{subject:03d}.npz"
        if file.exists():
            saved = np.load(file)
            x, y, trial = saved["X"], saved["y"], saved["trial"]
        else:
            x, y, trial = _load_physionet_subject(subject, runs, channels, classes, cfg)
            np.savez(file, X=x, y=y, trial=trial)
        Xs.append(x), ys.append(y), trials.append(trial + subject * 100_000)
        owners.append(np.full(len(y), subject))
    return Windows(np.concatenate(Xs), np.concatenate(ys), np.concatenate(trials),
                   np.concatenate(owners), list(channels), list(classes))


def read_export(path: Path):
    """Read an eego export. Returns (signal, sfreq, channel labels, annotations)."""
    import mne

    suffix = path.suffix.lower()
    if suffix == ".cnt":
        # eego's default EEProbe .cnt. mne.io.read_raw_cnt is the wrong reader: that is
        # for Neuroscan files, which merely share the extension.
        raw = mne.io.read_raw_ant(path, preload=True, verbose="ERROR")
    elif suffix == ".edf":
        raw = mne.io.read_raw_edf(path, preload=True, verbose="ERROR")
    elif suffix == ".vhdr":
        raw = mne.io.read_raw_brainvision(path, preload=True, verbose="ERROR")
    else:
        raise ValueError(f"Unsupported export type: {suffix}")
    raw.pick("eeg")
    return raw.get_data().T, float(raw.info["sfreq"]), list(raw.ch_names), raw.annotations


def recording_channels(path: Path) -> list[str]:
    """The labels in a recording, as used for rebuilding the pretrained model."""
    if path.suffix == ".npz":
        return [str(c) for c in np.load(path, allow_pickle=False)["channels"]]
    return read_export(path)[2]


def physionet_channels() -> list[str]:
    """PhysioNet's 64 labels, read from the header of one recording."""
    import mne
    from mne.datasets import eegbci

    path = eegbci.load_data(1, [3], path=str(DATA_DIR / "mne"), update_path=False,
                            verbose="ERROR")[0]
    raw = mne.io.read_raw_edf(path, preload=False, verbose="ERROR")
    eegbci.standardize(raw)
    return list(raw.ch_names)


def shared_channels(labels: list[str], available: list[str]) -> tuple[list[str], list[str]]:
    """Split a recording's labels into those we can pretrain on, and the rest.

    A real cap can have sites PhysioNet lacks, such as the mastoids M1 and M2, and the
    recording may use a label like 'C3-Ref'. Kept names stay in the recording's order
    and spelling, so the same labels match the live stream.
    """
    known = {normalize_label(name) for name in available}
    shared = [c for c in labels if normalize_label(c) in known]
    return shared, [c for c in labels if normalize_label(c) not in known]


def recording_movement(path: Path, schedule: Path | None = None) -> str:
    """imagined, real, or unknown for recordings made before modes existed."""
    if path.suffix == ".npz":
        saved = np.load(path, allow_pickle=False)
        return str(saved["mode"]) if "mode" in saved.files else "unknown"
    if schedule is not None:
        return str(json.loads(schedule.read_text()).get("mode", "unknown"))
    return "unknown"


def resolve_movement(stored: str, requested: str | None) -> str:
    """Which movement a recording holds. A label can fill a gap, never contradict the file."""
    if requested is None or requested == stored:
        return stored
    if stored != "unknown":
        raise ValueError(f"This recording is {stored}, so it can't be calibrated as {requested}.")
    return requested


def _select_channels(signal: np.ndarray, labels: list[str], channels: list[str]) -> np.ndarray:
    lookup = {normalize_label(name): i for i, name in enumerate(labels)}
    missing = [c for c in channels if normalize_label(c) not in lookup]
    if missing:
        raise ValueError(f"Recording lacks {missing}. Rerun: eegmove pretrain --montage-from <it>")
    return signal[:, [lookup[normalize_label(c)] for c in channels]]


def load_recording(path: Path, channels: list[str], classes: list[str], cfg: SignalConfig,
                   schedule: Path | None = None):
    """Load a team recording and return (Windows, baseline windows).

    `.npz` files from `eegmove record` carry exact labels. eego exports need the cue log
    from `eegmove record --no-lsl`; its clock starts at the first annotation in the export.
    """
    if path.suffix == ".npz":
        saved = np.load(path, allow_pickle=False)
        signal, sfreq, labels = saved["eeg"], float(saved["sfreq"]), [str(c) for c in saved["channels"]]
        # Convert cue times to sample positions using the timestamps. If the network drops
        # samples, position and time disagree, and trusting time would shift every label.
        # Cue ends need the same mapping, or a drop inside a cue labels post-cue data.
        elapsed = saved["timestamps"] - saved["timestamps"][0]
        starts = np.searchsorted(elapsed, saved["cue_onset_s"]) / sfreq
        ends = np.searchsorted(elapsed, saved["cue_onset_s"] + saved["cue_duration_s"]) / sfreq
        events = [(float(t), float(e - t), str(n)) for t, e, n in
                  zip(starts, ends, saved["cue_label"])]
    else:
        if schedule is None:
            raise ValueError("eego exports need --schedule with the cue log from the session.")
        signal, sfreq, labels, annotations = read_export(path)
        if len(annotations) == 0:
            raise ValueError("Export has no annotations, so the cue log cannot be lined up.")
        log = json.loads(schedule.read_text())
        t0 = float(annotations[0]["onset"])
        events = [(t0 + c["onset_s"], c["duration_s"], c["label"]) for c in log["cues"]]

    signal = _select_channels(signal, labels, channels)
    bad = ~np.isfinite(signal).all(axis=1)
    if bad.any():
        kept = [e for e in events
                if not bad[int(e[0] * sfreq):int((e[0] + e[1]) * sfreq) + 1].any()]
        print(f"Dropped {len(events) - len(kept)} cues containing non-finite samples.")
        events = kept
    filtered = StreamPreprocessor(sfreq, len(channels), cfg).process(signal)
    x, y, trial = cut_trials(filtered, events, classes, cfg)
    windows = Windows(x, y, trial, np.zeros(len(y), int), list(channels), list(classes))

    baseline = [e for e in events if e[2] == "baseline"]
    if baseline:
        base_x, _, _ = cut_trials(filtered, baseline, ["baseline"], cfg)
    else:
        base_x = x[np.array(windows.y) == classes.index("rest")] if "rest" in classes else x
    return windows, base_x

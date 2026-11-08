"""Loading EEG recordings, with eego (ANT Neuro) formats first.

Supported inputs
----------------
.cnt          eego / eego mylab / eego sports native recording. Needs
              `pip install mne antio` (MNE >= 1.9 provides mne.io.read_raw_ant).
.xdf          LSL recording made with LabRecorder while eego streams over LSL.
              Needs `pip install pyxdf`.
.edf / .bdf   Generic exports. Needs `pip install mne`.
.fif          MNE format. Needs `pip install mne`.
.npz          Arrays saved by this package (simulator) or by your own scripts:
              keys `data` (n_channels x n_samples), `sfreq`, `ch_names`.
.csv          One column per channel, optional `time` column, header row with
              channel labels; pass --sfreq if there is no time column.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# Channel labels that are not scalp EEG and must stay out of the common average.
NON_EEG = re.compile(
    r"^(BIP\d*|AUX\d*|EOG.*|VEOG|HEOG|ECG.*|EKG|EMG.*|TRIG.*|TRG|STATUS|STI.*|"
    r"COUNTER|TIME.*|TIMESTAMP|MARKER.*|GSR|RESP.*|ACC.*|GYRO.*)$",
    re.IGNORECASE,
)


@dataclass
class Recording:
    data: np.ndarray  # (n_channels, n_samples), any consistent unit (V or uV)
    sfreq: float
    ch_names: list[str]
    ch_types: list[str] = field(default_factory=list)  # "eeg" or "misc"
    source: str = ""
    events: list[tuple[float, str]] = field(default_factory=list)  # (seconds, label)

    def __post_init__(self) -> None:
        self.data = np.asarray(self.data, dtype=np.float64)
        if self.data.ndim != 2:
            raise ValueError("data must be 2-D (n_channels, n_samples)")
        if self.data.shape[0] != len(self.ch_names):
            raise ValueError(
                f"{self.data.shape[0]} channels in data but {len(self.ch_names)} names"
            )
        if not self.ch_types:
            self.ch_types = [guess_type(c) for c in self.ch_names]

    @property
    def duration(self) -> float:
        return self.data.shape[1] / self.sfreq

    def crop(self, start: float | None = None, stop: float | None = None) -> "Recording":
        a = 0 if start is None else max(0, int(round(start * self.sfreq)))
        b = self.data.shape[1] if stop is None else int(round(stop * self.sfreq))
        t0 = a / self.sfreq
        ev = [(t - t0, lab) for t, lab in self.events if a / self.sfreq <= t < b / self.sfreq]
        return Recording(self.data[:, a:b], self.sfreq, self.ch_names, self.ch_types,
                         self.source, ev)

    def summary(self) -> str:
        eeg = [c for c, t in zip(self.ch_names, self.ch_types) if t == "eeg"]
        other = [c for c, t in zip(self.ch_names, self.ch_types) if t != "eeg"]
        lines = [
            f"source:   {self.source or '(in memory)'}",
            f"sfreq:    {self.sfreq:g} Hz",
            f"duration: {self.duration:.1f} s",
            f"EEG ({len(eeg)}): {', '.join(eeg)}",
        ]
        if other:
            lines.append(f"other ({len(other)}): {', '.join(other)}")
        if self.events:
            lines.append(f"events:   {len(self.events)} (first: {self.events[0]})")
        return "\n".join(lines)


def guess_type(name: str) -> str:
    return "misc" if NON_EEG.match(name.strip()) else "eeg"


def _missing(pkg: str, fmt: str) -> ImportError:
    return ImportError(
        f"Reading {fmt} files needs `{pkg}`. Install it with: pip install {pkg}"
    )


def _from_mne_raw(raw, source: str) -> Recording:
    picks_types = raw.get_channel_types()
    data = raw.get_data()
    types = ["eeg" if t == "eeg" and guess_type(n) == "eeg" else "misc"
             for n, t in zip(raw.ch_names, picks_types)]
    events = [(float(a["onset"]), str(a["description"])) for a in raw.annotations]
    return Recording(data, float(raw.info["sfreq"]), list(raw.ch_names), types, source, events)


def load_cnt(path: str | Path) -> Recording:
    """eego .cnt via mne.io.read_raw_ant (MNE >= 1.9, needs antio)."""
    try:
        import mne  # noqa: F401
        from mne.io import read_raw_ant
    except ImportError as e:  # pragma: no cover - depends on environment
        raise _missing("mne antio", "eego .cnt") from e
    raw = read_raw_ant(str(path), preload=True, verbose="error")
    return _from_mne_raw(raw, str(path))


def load_mne_generic(path: str | Path) -> Recording:
    try:
        import mne
    except ImportError as e:  # pragma: no cover
        raise _missing("mne", Path(path).suffix) from e
    raw = mne.io.read_raw(str(path), preload=True, verbose="error")
    return _from_mne_raw(raw, str(path))


def load_xdf(path: str | Path, stream_name: str | None = None) -> Recording:
    """LSL .xdf recording (e.g. eego -> LSL -> LabRecorder)."""
    try:
        import pyxdf
    except ImportError as e:  # pragma: no cover
        raise _missing("pyxdf", ".xdf") from e
    streams, _ = pyxdf.load_xdf(str(path))
    eeg = [s for s in streams if s["info"]["type"][0].upper() == "EEG"]
    if stream_name:
        eeg = [s for s in streams if s["info"]["name"][0] == stream_name]
    if not eeg:
        names = [(s["info"]["name"][0], s["info"]["type"][0]) for s in streams]
        raise ValueError(f"no EEG stream in {path}; streams found: {names}")
    s = eeg[0]
    data = np.asarray(s["time_series"], dtype=np.float64).T
    sfreq = float(s["info"]["nominal_srate"][0]) or float(
        1.0 / np.median(np.diff(s["time_stamps"]))
    )
    try:
        chans = s["info"]["desc"][0]["channels"][0]["channel"]
        names = [c["label"][0] for c in chans]
    except (KeyError, IndexError, TypeError):
        names = [f"ch{i + 1}" for i in range(data.shape[0])]
    t0 = s["time_stamps"][0]
    events = []
    for m in streams:
        if m is s or m["info"]["type"][0].upper() == "EEG":
            continue
        for ts, val in zip(m["time_stamps"], m["time_series"]):
            events.append((float(ts - t0), str(val[0] if len(val) else "")))
    return Recording(data, sfreq, names, source=str(path), events=sorted(events))


def load_npz(path: str | Path) -> Recording:
    z = np.load(str(path), allow_pickle=False)
    names = [str(n) for n in z["ch_names"]]
    events = []
    if "event_times" in z and "event_labels" in z:
        events = [(float(t), str(l)) for t, l in zip(z["event_times"], z["event_labels"])]
    return Recording(z["data"], float(z["sfreq"]), names, source=str(path), events=events)


def load_csv(path: str | Path, sfreq: float | None = None) -> Recording:
    import pandas as pd

    df = pd.read_csv(str(path))
    time_cols = [c for c in df.columns if str(c).strip().lower() in ("time", "t", "timestamp", "seconds")]
    if time_cols:
        t = df[time_cols[0]].to_numpy(dtype=float)
        est = 1.0 / np.median(np.diff(t))
        sfreq = sfreq or float(est)
        df = df.drop(columns=time_cols)
    if sfreq is None:
        raise ValueError("CSV has no time column; pass the sampling rate (--sfreq)")
    df = df.select_dtypes(include=[np.number])
    return Recording(df.to_numpy().T, float(sfreq), [str(c).strip() for c in df.columns],
                     source=str(path))


def load(path: str | Path, sfreq: float | None = None) -> Recording:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    ext = p.suffix.lower()
    if ext == ".cnt":
        return load_cnt(p)
    if ext == ".xdf":
        return load_xdf(p)
    if ext in (".edf", ".bdf", ".fif", ".vhdr", ".set", ".gdf"):
        return load_mne_generic(p)
    if ext == ".npz":
        return load_npz(p)
    if ext in (".csv", ".tsv", ".txt"):
        return load_csv(p, sfreq)
    raise ValueError(f"unsupported file type {ext!r}")


def save_npz(rec: Recording, path: str | Path, **extra) -> None:
    np.savez_compressed(
        str(path),
        data=rec.data.astype(np.float32),
        sfreq=rec.sfreq,
        ch_names=np.array(rec.ch_names),
        event_times=np.array([t for t, _ in rec.events], dtype=float),
        event_labels=np.array([l for _, l in rec.events]),
        **extra,
    )

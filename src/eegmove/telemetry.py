"""Publish a model-independent view of EEG samples and their measured spectrum."""

from __future__ import annotations

import json
import socket
import time

import numpy as np
from scipy.signal import welch

from .streaming import EegInlet

WINDOW_SECONDS = 2.0
PUBLISH_INTERVAL = 0.25
WAVEFORM_POINTS = 162
SPECTRUM_POINTS = 192


def display_values(values: np.ndarray) -> list[float]:
    # Keep the same relative precision for EEG streams measured in volts or microvolts.
    return [float(f"{value:.6g}") for value in values]


def waveform(values: np.ndarray, times: np.ndarray) -> dict:
    """Keep extrema when reducing dense traces for display and UDP transport."""
    if len(values) > WAVEFORM_POINTS:
        buckets = np.array_split(np.arange(1, len(values) - 1), (WAVEFORM_POINTS - 2) // 2)
        extrema = [0, len(values) - 1]
        for bucket in buckets:
            samples = values[bucket]
            extrema.extend((bucket[samples.argmin()], bucket[samples.argmax()]))
        picks = np.unique(extrema)
        times, values = times[picks], values[picks]
    return {"time_s": np.round(times, 5).tolist(), "values": display_values(values)}


def spectrum(values: np.ndarray, rate: float) -> dict | None:
    """One-sided Welch PSD in the stream's native amplitude unit squared per Hz."""
    segment = max(2, round(rate))
    if len(values) < segment:
        return None

    frequencies, density = welch(values, fs=rate, nperseg=segment, scaling="density")
    if not np.isfinite(density).all():
        return None

    if len(frequencies) > SPECTRUM_POINTS:
        detailed_bins = int(np.searchsorted(frequencies, 100, side="right"))
        groups = np.array_split(np.arange(detailed_bins, len(frequencies)),
                                SPECTRUM_POINTS - detailed_bins)
        centers = [frequencies[group].mean() for group in groups]
        means = [density[group].mean() for group in groups]
        frequencies = np.concatenate((frequencies[:detailed_bins], centers))
        density = np.concatenate((density[:detailed_bins], means))
    return {"frequency_hz": display_values(frequencies), "power_density": display_values(density)}


def channel_frames(inlet: EegInlet, source: str, samples: np.ndarray,
                   timestamps: np.ndarray):
    """Yield independently bounded packets, including channels missing current data."""
    relative_times = timestamps - timestamps[-1]
    for index, (label, unit) in enumerate(zip(inlet.channels, inlet.units)):
        values = samples[:, index]
        invalid = np.flatnonzero(~np.isfinite(values))
        # Do not draw a straight line or estimate a spectrum across missing data.
        start = int(invalid[-1]) + 1 if len(invalid) else 0
        usable = values[start:]
        yield {
            "type": "eeg_channel",
            "source": source,
            "stream_id": inlet.uid,
            "stream_name": inlet.name,
            "channel": label,
            "channel_index": index,
            "channel_count": len(inlet.channels),
            "sample_rate_hz": inlet.sfreq,
            "unit": unit,
            "waveform": waveform(usable, relative_times[start:]),
            "spectrum": spectrum(usable, inlet.sfreq),
        }


def run_monitor(stream: str | None = None, source: str = "live", port: int = 9996,
                duration: float | None = None) -> None:
    inlet = EegInlet(name=stream, dejitter=False)
    if source == "live" and inlet.source_id.endswith("-replay"):
        raise ValueError(f"{inlet.name!r} is a replay outlet. Run the monitor with --source replay.")

    width = max(2, round(WINDOW_SECONDS * inlet.sfreq))
    gap_threshold = max(0.05, 4 / inlet.sfreq)
    samples = np.empty((0, len(inlet.channels)))
    timestamps = np.empty(0)
    started = time.monotonic()
    next_send = started
    destination = ("127.0.0.1", port)
    print(f"Monitoring {len(inlet.channels)} EEG channels. Sending {source} telemetry to UDP {port}.",
          flush=True)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        while duration is None or time.monotonic() - started < duration:
            chunk, stamps = inlet.pull(timeout=PUBLISH_INTERVAL)
            if not len(stamps):
                continue

            invalid_stamps = np.flatnonzero(~np.isfinite(stamps))
            if len(invalid_stamps):
                start = int(invalid_stamps[-1]) + 1
                chunk, stamps = chunk[start:], stamps[start:]
                samples, timestamps = samples[:0], timestamps[:0]
                if not len(stamps):
                    continue

            samples = np.concatenate((samples, chunk))[-width:]
            timestamps = np.concatenate((timestamps, stamps))[-width:]
            intervals = np.diff(timestamps)
            # A vendor may stamp whole chunks when they are sent. Allow ordinary
            # scheduling jitter while avoiding spectra that span longer signal gaps.
            gaps = np.flatnonzero(np.abs(intervals) > gap_threshold)
            if len(gaps):
                start = int(gaps[-1]) + 1
                samples, timestamps = samples[start:], timestamps[start:]

            now = time.monotonic()
            if now < next_send:
                continue
            next_send = now + PUBLISH_INTERVAL
            for frame in channel_frames(inlet, source, samples, timestamps):
                sender.sendto(json.dumps(frame, allow_nan=False, separators=(",", ":")).encode(),
                              destination)

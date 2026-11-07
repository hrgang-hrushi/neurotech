import threading
import time
import uuid

import numpy as np
import pylsl

from eegmove.cli import main
from eegmove.streaming import EegInlet, replay


def test_replayed_stream_arrives_in_model_channel_order_without_junk_channels():
    """Exercises real LSL on this machine, with extra channels like an unknown vendor stream."""
    name = f"test-{uuid.uuid4().hex[:8]}"
    sfreq = 200.0
    n = int(sfreq * 3)
    c3, c4 = np.arange(n, dtype=float), 1000 + np.arange(n, dtype=float)
    signal = np.column_stack([c3, np.zeros(n), c4, np.arange(n, dtype=float)])
    labels = ["C3-Ref", "TRIGGER", "C4-Ref", "COUNTER"]
    threading.Thread(target=replay, args=(signal, labels, sfreq, name, 1), daemon=True).start()

    inlet = EegInlet(channels=["C4", "C3"], name=name, timeout=8)
    assert inlet.sfreq == sfreq
    samples = []
    stop = time.time() + 6
    while time.time() < stop and sum(len(s) for s in samples) < 100:
        chunk, _ = inlet.pull(timeout=0.1)
        if len(chunk):
            samples.append(chunk)
    received = np.concatenate(samples)
    assert received.shape[1] == 2
    np.testing.assert_allclose(received[:, 0] - received[:, 1], 1000.0)
    assert (np.diff(received[:, 1]) == 1).all(), "samples were dropped or reordered"


def test_replay_command_runs(monkeypatch):
    """--run once shadowed the command itself, so `eegmove replay` crashed on start."""
    played = []
    monkeypatch.setattr("eegmove.streaming.physionet_replay_signal",
                        lambda subject, run, sfreq, units: (played.append(run) or np.zeros((1, 1)), ["C3"]))
    monkeypatch.setattr("eegmove.streaming.replay", lambda *args, **kwargs: None)
    assert main(["replay", "--run", "4"]) == 0
    assert played == [4]


def test_stream_source_says_replay_or_live():
    name = f"test-{uuid.uuid4().hex[:8]}"
    outlets = {}
    for suffix, source_id in (("a", f"{name}-replay"), ("b", "amplifier-1234")):
        info = pylsl.StreamInfo(f"{name}{suffix}", "EEG", 2, 100.0, pylsl.cf_float32, source_id)
        outlets[suffix] = pylsl.StreamOutlet(info)
    assert EegInlet(name=f"{name}a", timeout=8).source == "replay"
    assert EegInlet(name=f"{name}b", timeout=8).source == "eeg"

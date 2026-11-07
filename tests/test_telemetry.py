import json
import socket
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from eegmove.streaming import replay
from eegmove.telemetry import WAVEFORM_POINTS, run_monitor


def test_monitor_reads_lsl_channels_and_sends_measured_spectra():
    name = f"test-monitor-{uuid.uuid4().hex[:8]}"
    rate = 400.0
    elapsed = np.arange(int(rate * 3.5)) / rate
    samples = np.column_stack((
        40 * np.sin(2 * np.pi * 10 * elapsed),
        np.zeros_like(elapsed),
        20 * np.sin(2 * np.pi * 22 * elapsed),
    ))
    labels = ["C3-Ref", "TRIGGER", "C4-Ref"]

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(1)
        with ThreadPoolExecutor() as pool:
            outlet = pool.submit(replay, samples, labels, rate, name, 1, ["uV", None, "uV"])
            monitor = pool.submit(run_monitor, name, "replay", receiver.getsockname()[1], 4)
            received = {}
            deadline = time.monotonic() + 7
            while time.monotonic() < deadline and len(received) < 2:
                if monitor.done():
                    monitor.result()
                try:
                    packet = json.loads(receiver.recv(65536))
                except TimeoutError:
                    continue
                assert packet["type"] == "eeg_channel"
                assert packet["source"] == "replay"
                assert packet["stream_name"] == name
                assert packet["stream_id"]
                assert packet["channel_count"] == 2
                assert packet["sample_rate_hz"] == rate
                assert packet["unit"] == "uV"
                waveform = packet["waveform"]
                assert len(waveform["values"]) == len(waveform["time_s"]) <= WAVEFORM_POINTS
                assert waveform["time_s"][-1] == 0
                if packet["spectrum"] is not None:
                    received[packet["channel"]] = packet
            monitor.result()
            outlet.result()

    assert set(received) == {"C3-Ref", "C4-Ref"}
    for index, (channel, frequency) in enumerate((("C3-Ref", 10), ("C4-Ref", 22))):
        packet = received[channel]
        assert packet["channel_index"] == index
        spectrum = packet["spectrum"]
        peak = spectrum["frequency_hz"][np.argmax(spectrum["power_density"])]
        assert abs(peak - frequency) < 1

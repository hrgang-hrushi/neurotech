"""Eye/electrode artifact handling for clench decoding (eeg_morse.artifacts, clean_decode)."""
import warnings

import numpy as np
import pytest

from eeg_morse import decode, preset
from eeg_morse.artifacts import FRONTOPOLAR, candidate_channels, detect_eye_events, detect_pops
from eeg_morse.clean_decode import decode_clean, is_clench_like
from eeg_morse.config import PipelineConfig
from eeg_morse.io import Recording
from eeg_morse.pipeline import ensure_bad_channels
from eeg_morse.simulate import REAL_CAP_CLENCH_WEIGHT, simulate

warnings.filterwarnings("ignore")
TEAM4 = PipelineConfig.load("models/team4_clench.json")


def test_simulator_without_artifacts_is_unchanged():
    a, _ = simulate("SOS", preset="clench", seed=4)
    b, _ = simulate("SOS", preset="clench", seed=4, artifacts=0.0)
    assert np.array_equal(a.data, b.data)


def test_eye_events_found_on_frontopolar_blinks():
    rec, _ = simulate("E", preset="clench", seed=2, artifacts=1.0, lead_s=20.0)
    ensure_bad_channels(rec)
    blinks = [e for e in detect_eye_events(rec) if e.kind == "blink"]
    # ~1 blink per 4 s over ~25 s of recording
    assert 3 <= len(blinks) <= 15


def test_no_eye_events_in_clean_clench():
    rec, _ = simulate("TEST", preset="clench", seed=3)
    ensure_bad_channels(rec)
    events = detect_eye_events(rec)
    assert len(events) <= 6  # only the plain simulator's few slow spontaneous blinks


def test_pop_detected_on_the_right_channel():
    rec, _ = simulate("E", preset="clench", seed=5)
    k = rec.ch_names.index("C3")
    i = int(5.0 * rec.sfreq)
    rec.data[k, i:] += 300.0 * np.exp(-np.arange(rec.data.shape[1] - i) / (0.3 * rec.sfreq))
    ensure_bad_channels(rec)
    pops = detect_pops(rec)
    assert any(p.channel == "C3" and abs(p.t_on - 5.0) < 0.1 for p in pops)


def test_frontopolar_never_used_as_clench_channel():
    rec, _ = simulate("E", preset="clench", seed=0)
    chans = candidate_channels(rec, ["Fp1", "Fp2", "AF3", "T7", "F3"])
    assert chans == ["T7", "F3"]
    assert all(not FRONTOPOLAR.match(c) for c in chans)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_blinks_on_clench_sites_no_longer_break_decoding(seed):
    """The failure the benchmark found: real-cap clench sites + blinks wreck plain decoding."""
    rec, truth = simulate("WHERE IS THE DOCTOR", preset="clench", seed=seed, artifacts=3.0,
                          emg_weight=REAL_CAP_CLENCH_WEIGHT, noise=1.5)
    assert decode(rec, TEAM4).text != truth.message
    assert decode_clean(rec, TEAM4).result.text == truth.message


def test_clean_decode_matches_plain_without_artifacts():
    rec, truth = simulate("HELP ME", preset="clench", seed=7)
    assert decode_clean(rec, preset("clench")).result.text == truth.message == decode(rec, preset("clench")).text


def test_non_emg_presets_fall_back_to_plain_decode():
    assert not is_clench_like(preset("blink")) and not is_clench_like(preset("motor"))
    rec, truth = simulate("EE", preset="blink", seed=0)
    out = decode_clean(rec, preset("blink"))
    assert not out.artifact_aware and out.result.text == truth.message


def test_missing_frontopolar_channels_warns():
    rec, truth = simulate("TT", preset="clench", seed=1)
    keep = [i for i, c in enumerate(rec.ch_names) if not c.startswith("Fp")]
    rec2 = Recording(rec.data[keep], rec.sfreq, [rec.ch_names[i] for i in keep])
    out = decode_clean(rec2, preset("clench"))
    assert out.result.text == truth.message
    assert any("frontopolar" in w for w in out.result.warnings)


def test_mostly_constant_channel_is_not_one_long_pop():
    rec, _ = simulate("E", preset="clench", seed=6)
    k = rec.ch_names.index("T7")
    held = rec.data[k].copy()
    held[np.arange(held.size) % 10 < 7] = 0.0  # held/clipped 70% of samples
    rec.data[k] = held
    ensure_bad_channels(rec)
    assert sum(p.channel == "T7" for p in detect_pops(rec)) < 5

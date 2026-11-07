import numpy as np
import pytest

from eegmove.config import SignalConfig, mirror_pairs, normalize_label
from eegmove.datasets import cut_trials, shared_channels
from eegmove.preprocess import StreamPreprocessor, apply_whitening, whitening_matrix
from eegmove.streaming import match_channels


@pytest.mark.parametrize("sfreq", [160.0, 500.0, 512.0, 1000.0])
def test_chunked_output_matches_one_shot(sfreq):
    """If this breaks, offline accuracy stops predicting live behaviour."""
    cfg = SignalConfig()
    signal = np.random.default_rng(0).normal(size=(int(sfreq * 6), 8)) * 30
    whole = StreamPreprocessor(sfreq, 8, cfg).process(signal)

    streaming = StreamPreprocessor(sfreq, 8, cfg)
    sizes = np.random.default_rng(1).integers(1, 40, size=2000)
    parts, start = [], 0
    for size in sizes:
        parts.append(streaming.process(signal[start:start + size]))
        start += size
        if start >= len(signal):
            break
    chunked = np.concatenate(parts)
    n = min(len(whole), len(chunked))
    assert abs(len(whole) - len(chunked)) <= 1
    assert abs(n - 6 * cfg.sfreq) <= 2
    np.testing.assert_allclose(whole[:n], chunked[:n], atol=1e-6)


def test_preprocessor_keeps_mu_and_rejects_mains_and_drift():
    cfg = SignalConfig()
    sfreq = 500.0
    t = np.arange(int(sfreq * 10)) / sfreq

    def power(frequency):
        wave = np.sin(2 * np.pi * frequency * t)
        signal = np.column_stack([wave, -wave])  # survives common average reference
        out = StreamPreprocessor(sfreq, 2, cfg).process(signal)
        return out[len(out) // 2:, 0].std()

    assert power(12) > 0.5
    assert power(60) < 0.01
    assert power(1) < 0.05


def test_whitening_flattens_covariance_and_ignores_units():
    rng = np.random.default_rng(0)
    mixing = rng.normal(size=(6, 6))
    x = (mixing @ rng.normal(size=(50, 6, 320))).astype(np.float64)
    aligned = apply_whitening(x, whitening_matrix(x))
    cov = (aligned @ aligned.transpose(0, 2, 1)).mean(axis=0) / x.shape[-1]
    np.testing.assert_allclose(cov, np.eye(6), atol=0.25)

    in_volts = apply_whitening(x * 1e-6, whitening_matrix(x * 1e-6))
    np.testing.assert_allclose(aligned, in_volts, rtol=1e-3, atol=1e-3)


def test_whitening_survives_common_average_reference():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(30, 8, 320))
    x = x - x.mean(axis=1, keepdims=True)
    assert np.isfinite(apply_whitening(x, whitening_matrix(x))).all()


def test_flat_baseline_is_reported_not_silently_used():
    with pytest.raises(ValueError, match="flat"):
        whitening_matrix(np.zeros((5, 4, 100)))


def test_labels_normalize_across_vendor_formats():
    assert {normalize_label(x) for x in ["C3", "c3 ", "EEG C3-Ref", "C3-CPz"]} == {"c3"}


def test_match_channels_follows_labels_and_skips_non_eeg():
    labels = ["TRIGGER", "C4-Ref", "C3-Ref", "COUNTER", "BIP1"]
    assert match_channels(labels, ["C3", "C4"]) == ([2, 1], [])
    assert match_channels(labels, ["C3", "Pz"]) == ([2], ["Pz"])
    assert match_channels(labels, ["BIP1"]) == ([], ["BIP1"])


def test_mirror_pairs_flip_left_and_right():
    assert mirror_pairs(["C3", "Cz", "C4", "FC5", "FC6"]) == [2, 1, 0, 4, 3]
    assert mirror_pairs(["C3", "Cz"]) is None


def test_recording_cut_short_keeps_complete_windows_and_drops_the_rest():
    cfg = SignalConfig()
    signal = np.zeros((int(cfg.sfreq * 6), 2))  # recording stops mid-way through the second cue
    x, y, _ = cut_trials(signal, [(0.0, 4.0, "left"), (3.5, 4.0, "right"), (9.0, 4.0, "left")],
                         ["left", "right"], cfg)
    assert x.shape == (len(y), 2, cfg.n_times)
    assert (y == 1).sum() == 1  # only the first crop of the interrupted cue fits
    assert len(y) == 5


def test_shared_channels_drops_sites_physionet_lacks_and_keeps_our_spelling():
    shared, dropped = shared_channels(["C3-Ref", "M1-Ref", "Cz-Ref"], ["C3", "Cz", "Pz"])
    assert shared == ["C3-Ref", "Cz-Ref"]
    assert dropped == ["M1-Ref"]


def test_cut_trials_keeps_each_cue_in_one_group():
    cfg = SignalConfig()
    signal = np.zeros((int(cfg.sfreq * 20), 2))
    x, y, trial = cut_trials(signal, [(1.0, 4.0, "left"), (8.0, 4.0, "right"), (14.0, 4.0, "skip")],
                             ["left", "right"], cfg)
    assert x.shape[1:] == (2, cfg.n_times)
    assert len(y) == 8  # four 2 s crops fit in each 4 s cue after the 0.5 s offset
    assert set(trial[y == 0]).isdisjoint(trial[y == 1])

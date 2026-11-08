"""The owner's risk: a faint signal lost in noise. Endpoints sit far from the bar on purpose,
because scores near it wobble between seeds and a test there would flake."""

from pathlib import Path

import numpy as np
import pytest

from eegmove.config import ASSUMED_MONTAGE, DATA_DIR, SignalConfig
from eegmove.datasets import load_physionet
from eegmove.preprocess import whitening_matrix, apply_whitening
from eegmove.quality import SnrMonitor, WindowGate, band_power, hand_sites
from eegmove.train import calibrate, evaluate_session, baseline_of
from eegmove.verdict import judge, load_verdict
from synthetic import write_motor_recording

CLASSES = ["rest", "left", "right"]
GOOD_LIVE = {"source": "eeg", "clean_s": 120.0, "false_per_min": 0.0, "correct": 20, "cues": 20}
SFREQ = 160.0


def offline_score(tmp_path, strength, seed=0, **options):
    folder = tmp_path / f"{strength}-{seed}"
    folder.mkdir()
    recording = write_motor_recording(folder / "r.npz", strength, seed, **options)
    out = folder / "m.joblib"
    calibrate(recording, None, ["C3", "C4", "Fz", "Pz"], CLASSES, SignalConfig(), None, out,
              use_net=False, movement="imagined")
    return load_verdict(out)["offline"]


def test_go_verdict_flips_as_snr_falls(tmp_path):
    verdicts = [judge(offline_score(tmp_path, strength), GOOD_LIVE, "imagined")[0]
                for strength in (0.9, 0.0)]
    assert verdicts == [True, False]


@pytest.mark.parametrize("seed", [0, 1])
def test_weak_signal_below_bar_gets_no_go(tmp_path, seed):
    offline = offline_score(tmp_path, 0.9, seed, hit_rate=0.5)  # half the attempts do nothing
    assert 0.55 < offline["left_right"] < 0.85
    assert not judge(offline, GOOD_LIVE, "imagined")[0]


def spectral_noise(mu_gain, n=320, windows=60, channels=2, seed=0):
    """White noise with the mu band scaled by a known gain."""
    rng = np.random.default_rng(seed)
    spectrum = np.fft.rfft(rng.normal(size=(windows, channels, n)), axis=-1)
    freqs = np.fft.rfftfreq(n, 1 / SFREQ)
    spectrum[..., (freqs >= 7) & (freqs <= 14)] *= mu_gain
    return np.fft.irfft(spectrum, n=n, axis=-1)


@pytest.mark.parametrize("gain", [1.0, 3.0, 10.0])
def test_snr_estimate_recovers_known_level(gain):
    monitor = SnrMonitor(spectral_noise(1.0), ["C3", "C4"], SFREQ)
    measured = np.median([monitor.ratio_db(w) for w in spectral_noise(gain, seed=1)])
    assert measured == pytest.approx(20 * np.log10(gain), abs=1.0)


def test_band_power_is_flat_for_white_noise():
    x = spectral_noise(1.0)
    low, high = band_power(x, SFREQ, (8, 13)).mean(), band_power(x, SFREQ, (24, 29)).mean()
    assert low == pytest.approx(high, rel=0.15)


def test_low_snr_warns_during_live():
    monitor = SnrMonitor(spectral_noise(4.0), ["C3", "C4"], SFREQ)
    healthy = spectral_noise(4.0, seed=1)
    assert all(monitor.update(w, "rest")[1] is None for w in healthy)
    faded = spectral_noise(1.0, seed=2)
    warnings = [monitor.update(w, "rest")[1] for w in faded]
    assert warnings[-1] is not None and "fading" in warnings[-1]


def test_imagined_movement_is_not_read_as_signal_loss():
    monitor = SnrMonitor(spectral_noise(4.0), ["C3", "C4"], SFREQ)
    for window in spectral_noise(4.0, seed=1):
        monitor.update(window, "rest")
    for window in spectral_noise(1.0, seed=2):  # mu drops, as it should while imagining
        assert monitor.update(window, "left")[1] is None


def test_noise_growth_also_warns():
    monitor = SnrMonitor(spectral_noise(4.0), ["C3", "C4"], SFREQ)
    noisy = spectral_noise(4.0, seed=1) + 3 * np.random.default_rng(3).normal(size=(60, 2, 320))
    assert [monitor.update(w, "rest")[1] for w in noisy][-1] is not None


def test_montage_without_hand_sites_still_reports():
    monitor = SnrMonitor(spectral_noise(2.0), ["Fp1", "O2"], SFREQ)
    assert hand_sites(["Fp1", "O2"]) is None
    assert "all channels" in monitor.region
    assert hand_sites(["C3-Ref", "Pz", "C4-Ref"]).label == "C3/C4"


def imagined_files(subjects) -> bool:
    found = {p.name for p in (DATA_DIR / "mne").rglob("*R14.edf")}
    return all(f"S{s:03d}R14.edf" in found for s in subjects)


@pytest.mark.skipif(not imagined_files([1, 2, 3]), reason="imagined runs aren't downloaded")
def test_real_imagined_physionet_runs_through_gate():
    cfg = SignalConfig()
    channels = list(ASSUMED_MONTAGE)
    scores = []
    for subject in (1, 2, 3):
        data = load_physionet([subject], channels, CLASSES, cfg, imagined_only=True)
        rest = baseline_of(data, 20)
        gate = WindowGate(rest)
        keep = gate.mask(data.X)
        assert keep.mean() > 0.5, "the gate rejects most of a real recording"
        monitor = SnrMonitor(rest, channels, cfg.sfreq)
        assert np.isfinite(monitor.baseline_db)
        kept = data.select(keep)
        whitening = whitening_matrix(rest)
        aligned = kept.select(np.ones(len(kept), bool))
        aligned.X = apply_whitening(kept.X, whitening)
        result = evaluate_session(aligned, cfg, None, folds=3, use_net=False)["riemann"]
        scores.append(result["left_right"])
        go, reasons = judge({"left_right": result["left_right"],
                             "three_class": result["balanced_raw"]}, None, "imagined")
        assert not go and "no live check yet" in reasons
    print(f"Imagined left vs right by subject: {scores}")
    assert np.mean(scores) > 0.5, "real imagined movement should beat chance on average"

import numpy as np
import torch

from eegmove.config import SignalConfig
from eegmove.datasets import Windows
from eegmove.live import MORSE_DEBOUNCE, Debouncer, RingBuffer
from eegmove.models import ShallowNet, TrainConfig, _augment, fit_net, make_riemann, net_probs
from eegmove.record import build_schedule
from eegmove.train import evaluate_session

CHANNELS = ["C3", "C4", "Fz", "Pz"]
CLASSES = ["rest", "left", "right"]


def fake_erd(n_trials=45, seed=0):
    """Mimic ERD: moving one hand suppresses 12 Hz power over the opposite hemisphere."""
    cfg = SignalConfig()
    rng = np.random.default_rng(seed)
    t = np.arange(cfg.n_times) / cfg.sfreq
    xs, ys, trials = [], [], []
    for trial in range(n_trials):
        label = trial % 3
        gain = {0: (1.0, 1.0), 1: (1.0, 0.25), 2: (0.25, 1.0)}[label]  # (C3, C4)
        for _ in range(3):
            phase = rng.uniform(0, 2 * np.pi, size=2)
            x = rng.normal(0, 0.4, size=(4, len(t)))
            x[0] += gain[0] * 2 * np.sin(2 * np.pi * 12 * t + phase[0])
            x[1] += gain[1] * 2 * np.sin(2 * np.pi * 12 * t + phase[1])
            xs.append(x), ys.append(label), trials.append(trial)
    return Windows(np.asarray(xs, np.float32), np.asarray(ys), np.asarray(trials),
                   np.zeros(len(ys), int), CHANNELS, CLASSES), cfg


def test_riemann_learns_lateralized_power():
    data, _ = fake_erd()
    test, _ = fake_erd(seed=1)
    model = make_riemann().fit(data.X.astype(np.float64), data.y)
    assert (model.predict(test.X.astype(np.float64)) == test.y).mean() > 0.9


def test_net_learns_lateralized_power():
    data, cfg = fake_erd()
    test, _ = fake_erd(seed=1)
    net = ShallowNet(4, cfg.n_times, 3)
    fit_net(net, data.X, data.y, TrainConfig(epochs=15, batch_size=32))
    assert (net_probs(net, test.X).argmax(1) == test.y).mean() > 0.8


def test_session_evaluation_runs_on_a_small_recording():
    data, cfg = fake_erd(n_trials=24)
    results = evaluate_session(data, cfg, pretrained=None, folds=3)
    assert set(results) == {"riemann", "net", "ensemble"}
    assert results["riemann"]["accuracy"] > 0.8


def test_mirror_augmentation_swaps_side_and_label_together():
    cfg = TrainConfig(flip=[1, 0], flip_labels=[0, 2, 1])
    x = torch.tensor([[[10.0] * 4, [0.0] * 4]]).repeat(200, 1, 1)
    y = torch.ones(200, dtype=torch.long)
    out_x, out_y = _augment(x, y, cfg)
    flipped = out_y == 2
    assert 0 < flipped.sum() < 200
    assert out_x[flipped][:, 0].mean() < 1 < 9 < out_x[flipped][:, 1].mean()
    assert out_x[~flipped][:, 0].mean() > 9


def test_debouncer_needs_a_stable_signal_and_fires_once():
    debounce = Debouncer(["rest", "left"], alpha=1.0, threshold=0.6, dwell=3, refractory=4)
    left, rest = np.array([0.1, 0.9]), np.array([0.9, 0.1])

    assert debounce.update(left) == ("rest", None)  # one window is not enough
    debounce.update(rest), debounce.update(rest), debounce.update(rest)
    events = [debounce.update(left)[1] for _ in range(8)]
    assert events.count("left") == 1


LR = ["rest", "left", "right"]
REST, LEFT, RIGHT = (np.eye(3)[i] * 0.9 + 0.05 for i in range(3))
UNSURE = np.array([0.45, 0.3, 0.25])


def morse_debouncer(**options):
    settings = dict(alpha=1.0, threshold=0.6, dwell=3, refractory=12, rest_dwell=8)
    return Debouncer(LR, **{**settings, **options})


def play(debounce, *script):
    events = []
    for probs, count in script:
        for _ in range(count):
            _, event = debounce.update(probs)
            if event:
                events.append(event)
    return events


def test_symbol_during_cooldown_is_not_lost():
    debounce = morse_debouncer(refractory=20)
    # Rest re-arms at update 11 of the cooldown, then right is held past its end.
    assert play(debounce, (LEFT, 3), (REST, 8), (RIGHT, 12)) == ["left", "right"]
    assert debounce.state == "right"


def test_repeat_requires_return_to_rest():
    debounce = morse_debouncer()
    assert play(debounce, (LEFT, 60)) == ["left"]
    assert play(debounce, (REST, 3), (LEFT, 20)) == []  # 0.75 s of rest doesn't re-arm
    assert play(debounce, (REST, 8), (LEFT, 12)) == ["left"]


def test_low_confidence_fires_nothing():
    debounce = morse_debouncer(threshold=0.96)
    assert play(debounce, (LEFT, 30)) == []
    assert debounce.state == "rest"


def test_dip_inside_a_hold_does_not_double_fire():
    debounce = morse_debouncer()
    assert play(debounce, (LEFT, 5), (UNSURE, 4), (LEFT, 5), (REST, 3), (LEFT, 8)) == ["left"]


def test_switching_symbols_needs_rest():
    debounce = morse_debouncer(refractory=4)
    assert play(debounce, (LEFT, 6), (RIGHT, 12)) == ["left"]
    assert debounce.state == "left"
    assert play(debounce, (REST, 8), (RIGHT, 4)) == ["right"]


def test_low_confidence_pauses_the_return_to_rest():
    debounce = morse_debouncer()
    play(debounce, (LEFT, 4), (REST, 5), (UNSURE, 3))
    assert debounce.state == "left"
    play(debounce, (REST, 3))
    assert debounce.state == "rest"


def test_stuck_state_releases():
    debounce = morse_debouncer(release_after=16)
    play(debounce, (LEFT, 4), (UNSURE, 15))
    assert debounce.state == "left"
    play(debounce, (UNSURE, 1))
    assert debounce.state == "rest"
    assert play(debounce, (LEFT, 3)) == ["left"]


def test_a_confirmed_hold_never_releases():
    debounce = morse_debouncer(release_after=16)
    play(debounce, (LEFT, 100))
    assert debounce.state == "left"


def test_rest_only_counts_when_confident():
    debounce = morse_debouncer(release_after=2)
    play(debounce, (LEFT, 4), (np.array([0.2, 0.45, 0.35]), 3))
    assert debounce.state == "rest" and not debounce.rest_sure
    play(debounce, (UNSURE, 1))  # rest leads here, but below the threshold
    assert not debounce.rest_sure
    play(debounce, (REST, 1))
    assert debounce.rest_sure


def test_a_confident_rebound_never_releases_into_a_symbol():
    debounce = morse_debouncer(**MORSE_DEBOUNCE)
    assert play(debounce, (LEFT, 6), (RIGHT, 60)) == ["left"]
    assert debounce.state == "left"


def test_rejected_window_clears_the_streak():
    debounce = morse_debouncer()
    play(debounce, (LEFT, 2))
    debounce.hold()
    assert play(debounce, (LEFT, 2)) == []
    assert play(debounce, (LEFT, 1)) == ["left"]


def test_ring_buffer_returns_newest_samples_in_order():
    ring = RingBuffer(n_channels=1, n_times=4)
    ring.push(np.arange(3.0)[:, None])
    assert not ring.ready
    ring.push(np.arange(3.0, 6.0)[:, None])
    assert ring.ready
    assert ring.window().tolist() == [[2.0, 3.0, 4.0, 5.0]]


def test_schedule_is_balanced_and_starts_with_a_baseline():
    cues = build_schedule(CLASSES, per_class=10, blocks=3, seed=1)
    assert cues[0]["label"] == "baseline"
    for name in CLASSES:
        assert sum(c["label"] == name for c in cues) == 10
    onsets = [c["onset_s"] for c in cues]
    assert onsets == sorted(onsets)

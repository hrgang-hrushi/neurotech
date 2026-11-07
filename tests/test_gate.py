import numpy as np
import pytest
import torch

from eegmove.config import SignalConfig
from eegmove.datasets import _cache_key, load_physionet
from eegmove import datasets, train
from eegmove.models import ShallowNet
from eegmove.train import _finetune, cue_folds, evaluate_session, left_right_score, score
from test_decoding import fake_erd


def test_score_left_right_uses_only_those_columns():
    classes = ["rest", "left", "right"]
    y = np.array([1, 1, 2, 2, 0, 0])
    # Rest is the top class everywhere, and left and right still separate perfectly.
    probs = np.array([[.8, .15, .05], [.8, .15, .05], [.8, .05, .15], [.8, .05, .15],
                      [.1, .9, 0], [.1, 0, .9]])
    assert left_right_score(y, probs, classes) == 1.0
    assert score(y, probs, classes)["accuracy_raw"] == 0.0  # three-way, the rest row never wins
    assert left_right_score(y, probs[:, [0, 2, 1]], classes) == 0.0


def test_score_keeps_values_unrounded_for_the_rule():
    y = np.array([0] * 8496 + [1] * 1504)
    probs = np.zeros((10000, 2))
    probs[:, 0] = 1
    result = score(y, probs, ["a", "b"])
    assert result["accuracy"] == 0.85
    assert result["accuracy_raw"] < 0.85


def test_small_recording_keeps_every_class_in_folds():
    data, _ = fake_erd(n_trials=9)
    for train_idx, test_idx in cue_folds(data, folds=4):
        assert set(data.y[train_idx].tolist()) == {0, 1, 2}
        assert not set(data.trial[train_idx]) & set(data.trial[test_idx])


def test_class_with_one_cue_is_refused_clearly():
    data, _ = fake_erd(n_trials=9)
    keep = (data.y != 2) | (data.trial == data.trial[data.y == 2][0])
    with pytest.raises(ValueError, match=r"right \(1\)"):
        cue_folds(data.select(keep), folds=3)


def test_class_with_no_windows_is_refused_clearly():
    data, _ = fake_erd(n_trials=9)
    with pytest.raises(ValueError, match=r"right \(0\)"):
        evaluate_session(data.select(data.y != 2), SignalConfig(), None, use_net=False)


def test_folds_keep_every_class_with_uneven_windows():
    data, _ = fake_erd(n_trials=12)
    # Gating left most cues with one window, and one cue with all three.
    first = np.unique(data.trial, return_index=True)[1]
    keep = np.zeros(len(data), bool)
    keep[first] = True
    keep[data.trial == data.trial[-1]] = True
    uneven = data.select(keep)
    for train_idx, _ in cue_folds(uneven, folds=4):
        assert set(uneven.y[train_idx].tolist()) == {0, 1, 2}


def test_riemann_only_evaluation_needs_no_net():
    data, cfg = fake_erd(n_trials=24)
    assert set(evaluate_session(data, cfg, None, folds=3, use_net=False)) == {"riemann"}


def test_calibrate_handles_a_different_class_set(tmp_path):
    data, cfg = fake_erd(n_trials=12)
    net = ShallowNet(4, cfg.n_times, 4)
    path = tmp_path / "pretrained.pt"
    torch.save({"state": net.state_dict(), "channels": data.channels, "cfg": cfg.to_dict(),
                "classes": ["rest", "left", "right", "feet"], "results": {}, "subjects": []}, path)
    assert _finetune(path, data, cfg).head.out_features == 3


def test_imagined_runs_are_included(monkeypatch, tmp_path):
    seen = []

    def spy(subject, runs, channels, classes, cfg):
        seen.append(sorted(runs))
        return np.zeros((1, 2, 4)), np.zeros(1, int), np.zeros(1, int)

    monkeypatch.setattr(datasets, "DATA_DIR", tmp_path)
    monkeypatch.setattr(datasets, "_load_physionet_subject", spy)
    cfg = SignalConfig()
    load_physionet([1], ["C3", "C4"], ["rest"], cfg, include_imagined=True)
    load_physionet([1], ["C3", "C4"], ["rest"], cfg, imagined_only=True)
    load_physionet([1], ["C3", "C4"], ["rest"], cfg)
    assert seen == [[3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14], [4, 6, 8, 10, 12, 14],
                    [3, 5, 7, 9, 11, 13]]


def test_cache_separates_imagined_runs():
    cfg = SignalConfig()
    keys = {_cache_key(["C3"], ["rest"], cfg, runs) for runs in
            (datasets.EXECUTED_RUNS, datasets.IMAGINED_RUNS,
             datasets.EXECUTED_RUNS | datasets.IMAGINED_RUNS)}
    assert len(keys) == 3


def test_heldout_uses_the_same_runs(monkeypatch, tmp_path):
    data, cfg = fake_erd(n_trials=6)
    calls = []

    def fake_load(subjects, channels, classes, cfg_, include_imagined=False, imagined_only=False):
        calls.append((subjects, include_imagined, imagined_only))
        return data

    monkeypatch.setattr(train, "load_physionet", fake_load)
    monkeypatch.setattr(train, "ARTIFACT_DIR", tmp_path)
    train.pretrain([1], [90], data.channels, data.classes, cfg, 1, True)
    assert calls == [([1], True, False), ([90], False, True)]


# --- The go/no-go rule ---

import json  # noqa: E402
import socket  # noqa: E402

import joblib  # noqa: E402

from eegmove import typing_app  # noqa: E402
from eegmove import live, verdict  # noqa: E402
from eegmove.check import (build_check_cues, collect_rest, run_check, score_cues,  # noqa: E402
                           summarize_rest)
from eegmove.cli import main  # noqa: E402
from eegmove.datasets import load_recording, resolve_movement  # noqa: E402
from eegmove.live import MORSE_DEBOUNCE, Debouncer, LiveSession, WindowDecider  # noqa: E402
from eegmove.models import SessionModel, make_riemann  # noqa: E402
from eegmove.morse import MorseTyper  # noqa: E402
from eegmove.quality import SnrMonitor, WindowGate  # noqa: E402
from eegmove.record import write_recording  # noqa: E402
from eegmove.train import calibrate  # noqa: E402
from eegmove.verdict import (GoRule, Refused, begin_attempt, choose_model, judge,  # noqa: E402
                             load_verdict, read_attempts, save_live, save_offline, session_path)
from synthetic import CHANNELS_24, FakeInlet, write_motor_recording  # noqa: E402

CLASSES = ["rest", "left", "right"]
GOOD_OFFLINE = {"left_right": 0.9, "three_class": 0.8}
GOOD_LIVE = {"source": "eeg", "clean_s": 120.0, "false_activations": 0, "false_per_min": 0.0,
             "correct": 18, "cues": 20, "threshold": 0.6}
GOOD_SCORES = {"left_right": 0.9, "balanced_raw": 0.8, "n": 100}
BAD_SCORES = {"left_right": 0.6, "balanced_raw": 0.5, "n": 100}


def calibrated_verdict(tmp_path, strength, **options):
    recording = write_motor_recording(tmp_path / "recording.npz", strength, **options)
    out = tmp_path / "model.joblib"
    calibrate(recording, None, ["C3", "C4", "Fz", "Pz"], CLASSES, SignalConfig(), None, out,
              use_net=False, movement="imagined")
    return load_verdict(out)


def test_noise_only_recording_gets_no_go(tmp_path):
    record = calibrated_verdict(tmp_path, strength=0.0)
    go, reasons = judge(record["offline"], GOOD_LIVE, "imagined")
    assert not go
    assert any("left vs right" in r for r in reasons)
    assert record["offline"]["left_right"] < 0.7


def test_separable_recording_gets_go(tmp_path):
    record = calibrated_verdict(tmp_path, strength=0.9)
    assert judge(record["offline"], GOOD_LIVE, "imagined") == (True, [])


def test_left_right_score_decides_not_rest():
    go, reasons = judge({"left_right": 0.6, "three_class": 0.9}, GOOD_LIVE, "imagined")
    assert not go and len(reasons) == 1 and "left vs right" in reasons[0]


@pytest.mark.parametrize("change,expected", [
    ({"left_right": 0.85}, True), ({"left_right": 0.8499999}, False),
    ({"three_class": 0.70}, True), ({"three_class": 0.6999999}, False)])
def test_go_rule_boundaries(change, expected):
    assert judge({**GOOD_OFFLINE, **change}, GOOD_LIVE, "imagined")[0] is expected


@pytest.mark.parametrize("change,expected", [
    ({"false_per_min": 0.5}, True), ({"false_per_min": 0.51}, False),
    ({"correct": 17}, True), ({"correct": 16}, False),
    ({"clean_s": 119.75, "false_per_min": 0.0}, False), ({"cues": 19, "correct": 19}, False),
    ({"cues": 40, "correct": 17}, False), ({"cues": 200, "correct": 100}, False)])
def test_live_rule_boundaries(change, expected):
    assert judge(GOOD_OFFLINE, {**GOOD_LIVE, **change}, "imagined")[0] is expected


def rest_message(event=None, ok=True):
    return {"ok": ok, "event": event, "step_s": 0.25}


def test_check_counts_false_activations():
    messages = [rest_message() for _ in range(480)]
    messages[100] = rest_message("left")
    summary = summarize_rest(messages + [rest_message("right")], rest_s=120.0)
    assert summary == {"clean_s": 120.0, "false_activations": 1, "false_per_min": 0.5}


def test_rest_without_clean_windows_is_no_go():
    summary = summarize_rest([rest_message(ok=False) for _ in range(1000)])
    assert summary["clean_s"] == 0.0 and summary["false_activations"] == 0
    go, reasons = judge(GOOD_OFFLINE, {**GOOD_LIVE, **summary}, "imagined")
    assert not go and "clean rest" in reasons[0]


def test_replay_source_is_no_go():
    go, reasons = judge(GOOD_OFFLINE, {**GOOD_LIVE, "source": "replay"}, "imagined")
    assert not go and "replay" in reasons[0]


def test_old_model_counts_as_unknown(tmp_path):
    model = SessionModel(["C3"], CLASSES, SignalConfig(), np.eye(1), None, None, "riemann")
    assert model.movement == "unknown"
    del model.__dict__["movement"]  # exactly what a file saved before this field looks like
    joblib.dump(model, tmp_path / "old.joblib")
    assert joblib.load(tmp_path / "old.joblib").movement == "unknown"
    assert not judge(GOOD_OFFLINE, GOOD_LIVE, "unknown")[0]


def test_model_mode_survives_save_and_load(tmp_path):
    model = SessionModel(["C3"], CLASSES, SignalConfig(), np.eye(1), None, None, "riemann", "real")
    joblib.dump(model, tmp_path / "m.joblib")
    loaded = joblib.load(tmp_path / "m.joblib")
    assert (loaded.mode, loaded.movement) == ("riemann", "real")


def approve(folder, movement, scores=GOOD_SCORES, live=GOOD_LIVE):
    path = session_path(movement, folder)
    path.write_bytes(movement.encode())
    save_offline(path, movement, "riemann", scores)
    if live:
        save_live(path, live)
    return path


def test_imagined_is_chosen_when_it_passes(tmp_path):
    approve(tmp_path, "imagined")
    approve(tmp_path, "real")
    choice = choose_model(tmp_path)
    assert choice.movement == "imagined" and "IMAGINED" in choice.banner


def test_no_go_uses_real_model_and_labels_it(tmp_path):
    approve(tmp_path, "imagined", BAD_SCORES)
    approve(tmp_path, "real")
    choice = choose_model(tmp_path)
    assert choice.movement == "real" and "REAL MOVEMENT FALLBACK" in choice.banner


def test_fallback_needs_its_own_passing_check(tmp_path):
    approve(tmp_path, "imagined", BAD_SCORES)
    path = approve(tmp_path, "real", live=None)
    with pytest.raises(Refused, match="no live check"):
        choose_model(tmp_path)
    save_live(path, GOOD_LIVE)
    assert choose_model(tmp_path).movement == "real"


def test_both_no_go_refuses_loudly(tmp_path):
    approve(tmp_path, "imagined", BAD_SCORES)
    approve(tmp_path, "real", BAD_SCORES)
    with pytest.raises(Refused) as caught:
        choose_model(tmp_path)
    assert "imagined:" in str(caught.value) and "real:" in str(caught.value)


def test_missing_verdict_refuses_to_start(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(typing_app, "run_window", lambda *a: pytest.fail("opened a window"))
    assert typing_app.run_app(artifact_dir=tmp_path) == 2
    assert "No model may type" in capsys.readouterr().out


def test_corrupt_verdict_counts_as_missing(tmp_path):
    path = approve(tmp_path, "imagined")
    path.with_suffix(".verdict.json").write_text("{broken")
    assert load_verdict(path) is None


def test_recalibrating_clears_the_verdict(tmp_path):
    path = approve(tmp_path, "imagined")
    assert load_verdict(path)["go"]
    path.write_bytes(b"a new model")
    assert load_verdict(path) is None
    assert save_offline(path, "imagined", "riemann", GOOD_SCORES)["live"] is None
    assert not load_verdict(path)["go"]


def test_attempts_survive_recalibrating(tmp_path):
    path = approve(tmp_path, "imagined")
    begin_attempt(path)
    assert begin_attempt(path) == 2
    path.write_bytes(b"a new model")
    save_offline(path, "imagined", "riemann", GOOD_SCORES)
    assert begin_attempt(path) == 3
    assert read_attempts("imagined", tmp_path) == 3
    assert read_attempts("real", tmp_path) == 0


def test_stopping_a_check_still_counts_the_attempt(tmp_path):
    path = approve(tmp_path, "imagined", live=None)

    class Stopped(StuckSession):
        def collect_baseline(self, seconds):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_check(path, session=Stopped(None))
    assert read_attempts("imagined", tmp_path) == 1


def test_check_refuses_before_it_starts_without_a_calibration(tmp_path):
    (tmp_path / "m.joblib").write_bytes(b"model")
    with pytest.raises(Refused, match="calibrate"):
        run_check(tmp_path / "m.joblib", session=StuckSession(None))


def test_a_changed_verdict_file_cannot_grant_a_go(tmp_path):
    path = approve(tmp_path, "imagined", BAD_SCORES)
    file = path.with_suffix(".verdict.json")
    file.write_text(file.read_text().replace('"go": false', '"go": true'))
    with pytest.raises(Refused):
        choose_model(tmp_path)


def test_a_recording_cannot_be_relabelled():
    assert resolve_movement("imagined", None) == "imagined"
    assert resolve_movement("unknown", "real") == "real"
    with pytest.raises(ValueError, match="real"):
        resolve_movement("real", "imagined")


def test_calibrate_command_refuses_a_relabelled_recording(tmp_path, capsys):
    path = write_motor_recording(tmp_path / "r.npz", 0.9, movement="real", per_class=2)
    assert main(["calibrate", str(path), "--pretrained", "none", "--mode", "imagined"]) == 2
    assert "can't be calibrated as imagined" in capsys.readouterr().out


def test_live_command_refuses_with_no_approved_model(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(verdict, "ARTIFACT_DIR", tmp_path)
    assert main(["live"]) == 2
    assert "No model may type" in capsys.readouterr().out


class TypingStream:
    """Plays a whole check: quiet rest, then one event for each cue it is shown."""

    movement, source, threshold = "imagined", "eeg", 0.6

    def __init__(self, clock, wrong=0):
        self.clock, self.wrong, self.pending, self.printed = clock, wrong, None, []

    def collect_baseline(self, seconds):
        return True

    def flush(self):
        pass

    def signal_strength(self):
        return {"baseline_db": 3.0, "current_db": 2.5, "region": "C3/C4"}

    def say(self, text):
        self.printed.append(text)
        for label in ("LEFT", "RIGHT"):
            if f"{label} HAND" in text:
                self.pending = label.lower()
                if self.wrong:
                    self.wrong -= 1
                    self.pending = {"left": "right", "right": "left"}[self.pending]

    def decode(self):
        while True:
            self.clock.t += 0.25
            event, self.pending = self.pending, None
            yield {"ok": True, "event": event, "step_s": 0.25, "lsl_time": self.clock.t,
                   "latency_ms": 40.0, "warning": "Signal fading" if event else None}


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


@pytest.mark.parametrize("wrong,passes", [(3, True), (4, False)])
def test_full_check_reaches_the_symbol_rule(tmp_path, wrong, passes):
    path = approve(tmp_path, "imagined", live=None)
    clock = Clock()
    stream = TypingStream(clock, wrong)
    record = run_check(path, session=stream, now=clock, clock=clock, say=stream.say)
    assert record["live"]["correct"] == 20 - wrong and record["live"]["cues"] == 20
    assert record["live"]["clean_s"] == 120.0
    assert record["go"] is passes
    assert record["live"]["warnings"] == ["Signal fading"]
    assert any("Signal strength" in line and "C3/C4" in line for line in stream.printed)


def test_each_attempt_gets_a_new_cue_order(tmp_path):
    path = approve(tmp_path, "imagined", live=None)
    seeds = set()
    for _ in range(4):
        record = run_check(path, session=StuckSession(None), now=ticking(), clock=ticking())
        seeds.add(record["live"]["seed"])
    assert len(seeds) == 4
    assert build_check_cues(20, 1) != build_check_cues(20, 2)


def test_decoder_uncertainty_does_not_finish_a_letter():
    """The whole path, not a hand-set flag: real probabilities through the real debouncer."""

    class Unsure(AlwaysLeft):
        probs = np.array([[0.05, 0.9, 0.05]])

        def predict_proba(self, aligned):
            return self.probs

    model = Unsure()
    step = WindowDecider(model, np.eye(24), WindowGate(rest_windows()),
                         Debouncer(CLASSES, **MORSE_DEBOUNCE), None)
    typer = MorseTyper()
    window = rest_windows(seed=1)[0]

    def feed(seq):
        typer.feed({"run": "a", "seq": seq, "step_s": 0.25, "source": "eeg", **step.step(window)})

    for seq in range(20):
        feed(seq)
    assert typer.sequence == "."
    model.probs = np.array([[0.45, 0.30, 0.25]])  # rest leads, below the threshold
    for seq in range(20, 120):
        feed(seq)
    assert typer.sequence == "." and typer.text == ""
    model.probs = np.array([[0.9, 0.05, 0.05]])
    for seq in range(120, 140):
        feed(seq)
    assert typer.text == "E"


def test_fading_signal_reaches_the_typing_screen():
    healthy = np.fft.irfft(np.fft.rfft(rest_windows(2, 40), axis=-1) * mu_gain(4.0), n=320, axis=-1)
    monitor = SnrMonitor(healthy, ["C3", "C4"], 160.0)

    class Rest(AlwaysLeft):
        def predict_proba(self, aligned):
            return np.array([[0.9, 0.05, 0.05]])

    step = WindowDecider(Rest(), np.eye(2), None, Debouncer(CLASSES, alpha=1.0), monitor)
    step.gate = WindowGate(rest_windows(2, 40) * 0 + healthy)
    step.gate.check = lambda window: (True, None)
    typer = MorseTyper()
    for seq, window in enumerate(rest_windows(2, 40, seed=5)):
        typer.feed({"run": "a", "seq": seq, "step_s": 0.25, "source": "eeg", **step.step(window)})
    assert "fading" in typer.view().warning


def mu_gain(gain):
    freqs = np.fft.rfftfreq(320, 1 / 160.0)
    return np.where((freqs >= 7) & (freqs <= 14), gain, 1.0)


class Recorded:
    """Stands in for tkinter widgets and remembers what the screen showed."""

    shown = []

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return lambda *args, **kwargs: None

    def configure(self, **options):
        Recorded.shown.append(options.get("text"))

    def create_rectangle(self, *args, **kwargs):
        return 1


def test_screen_shows_the_movement_it_is_using(tmp_path, monkeypatch):
    import tkinter

    approve(tmp_path, "imagined", BAD_SCORES)
    approve(tmp_path, "real")
    Recorded.shown = []
    for name in ("Tk", "Label", "Canvas"):
        monkeypatch.setattr(tkinter, name, Recorded)
    assert typing_app.run_app(port=0, artifact_dir=tmp_path) == 0
    assert any(text and "REAL MOVEMENT FALLBACK" in text for text in Recorded.shown)


def test_live_command_sends_messages_and_prints_warnings(tmp_path, monkeypatch, capsys):
    class Session:
        movement, sha = "imagined", "abc"

        def __init__(self, *args, **kwargs):
            pass

        def collect_baseline(self, seconds):
            return True

        def decode(self):
            yield None
            yield {"ok": False, "reason": "burst", "state": "rest", "event": None,
                   "latency_ms": 1.0, "warning": "Signal fading"}
            raise KeyboardInterrupt

    monkeypatch.setattr(live, "LiveSession", Session)
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(2)
    log = live.run_live(tmp_path / "m", port=receiver.getsockname()[1], quiet=True)
    assert len(log) == 1
    assert json.loads(receiver.recv(65536))["reason"] == "burst"
    assert "WARNING: Signal fading" in capsys.readouterr().out


def test_threshold_must_match_the_verdict(tmp_path):
    approve(tmp_path, "imagined")
    choice = choose_model(tmp_path)
    assert choice.threshold == 0.6
    typer = MorseTyper(expect_model=choice.sha, expect_threshold=choice.threshold)
    typer.feed({"run": "a", "seq": 0, "ok": True, "rest": False, "step_s": 0.25, "state": "left",
                "event": "left", "source": "eeg", "model": choice.sha, "threshold": 0.4})
    assert typer.sequence == ""
    assert "threshold" in typer.warning


def slot_message(time_s, event=None, latency_ms=50.0):
    return {"lsl_time": time_s, "event": event, "latency_ms": latency_ms}


def test_extra_event_in_a_slot_counts_as_wrong():
    slots = [("left", 0.0, 9.0), ("right", 9.0, 18.0), ("left", 18.0, 27.0)]
    messages = [slot_message(3, "left"), slot_message(7, "right"),  # rebound in the first slot
                slot_message(12, "left"),  # wrong symbol
                slot_message(21, "left")]
    assert score_cues(slots, messages) == {"correct": 1, "cues": 3}


def test_no_event_in_a_slot_counts_as_wrong():
    assert score_cues([("left", 0.0, 9.0)], [slot_message(3)])["correct"] == 0


def test_buffered_samples_are_scored_by_acquisition_time():
    slots = [("left", 0.0, 9.0), ("right", 9.0, 18.0)]
    # Arrival order is scrambled, and only the time of the data decides the slot.
    assert score_cues(slots, [slot_message(12, "right"), slot_message(3, "left")])["correct"] == 2
    late = [slot_message(3, "left", latency_ms=5000.0), slot_message(12, "right")]
    assert score_cues(slots, late)["correct"] == 1


class StuckSession:
    """A decoder that never produces anything usable."""

    movement, source, threshold = "imagined", "eeg", 0.6

    def __init__(self, messages):
        self.messages = messages

    def collect_baseline(self, seconds):
        return False

    def flush(self):
        pass

    def signal_strength(self):
        return None

    def decode(self):
        while True:
            yield self.messages


def ticking():
    clock = {"t": 0.0}

    def now():
        clock["t"] += 1.0
        return clock["t"]

    return now


@pytest.mark.parametrize("messages", [None, {"ok": False, "event": None, "step_s": 0.25}],
                         ids=["no samples", "rejected windows"])
def test_rest_check_times_out_as_no_go(tmp_path, messages):
    path = session_path("imagined", tmp_path)
    path.write_bytes(b"model")
    save_offline(path, "imagined", "riemann", GOOD_SCORES)
    record = run_check(path, session=StuckSession(messages), now=ticking(), clock=ticking())
    assert not record["go"]
    assert read_attempts("imagined", tmp_path) == 1
    assert record["live"]["clean_s"] == 0.0 and record["live"]["cues"] == 0
    assert any("clean rest" in r for r in record["reasons"])


def test_stream_with_no_samples_times_out_as_no_go():
    assert collect_rest(StuckSession(None), 120.0, 180.0, ticking()) == []


def test_endless_rejected_windows_time_out_as_no_go():
    rejected = {"ok": False, "event": None, "step_s": 0.25}
    assert summarize_rest(collect_rest(StuckSession(rejected), 120.0, 180.0, ticking()))["clean_s"] == 0


class NoSocket:
    def __init__(self, *args, **kwargs):
        pytest.fail("simulate mode opened a socket")


def test_simulate_starts_with_no_models(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(typing_app, "run_window", lambda typer, sock, keys, label: opened.append(sock))
    monkeypatch.setattr(socket, "socket", NoSocket)
    assert typing_app.run_app(simulate=True, artifact_dir=tmp_path) == 0
    assert opened == [None]


def test_simulate_starts_with_two_no_go_verdicts(tmp_path, monkeypatch):
    approve(tmp_path, "imagined", BAD_SCORES)
    approve(tmp_path, "real", BAD_SCORES)
    opened = []
    monkeypatch.setattr(typing_app, "run_window", lambda *a: opened.append(a))
    assert typing_app.run_app(simulate=True, artifact_dir=tmp_path) == 0
    assert len(opened) == 1


# --- The quality gate ---


def rest_windows(n_channels=24, n=30, seed=0):
    """Common-average-referenced noise, as every window is by the time it reaches the gate."""
    x = np.random.default_rng(seed).normal(size=(n, n_channels, 320))
    return x - x.mean(axis=1, keepdims=True)


class AlwaysLeft:
    classes = CLASSES

    def predict_proba(self, aligned):
        return np.array([[0.05, 0.9, 0.05]])


def decider(gate=None):
    return WindowDecider(AlwaysLeft(), np.eye(24), gate,
                         Debouncer(CLASSES, alpha=1.0, dwell=1), None)


def test_clean_window_passes_quality_gate():
    rest = rest_windows()
    gate = WindowGate(rest)
    assert gate.check(rest_windows(seed=1)[0]) == (True, None)
    assert decider(gate).step(rest_windows(seed=1)[0])["event"] == "left"


def test_noise_burst_makes_no_decision():
    gate = WindowGate(rest_windows())
    window = rest_windows(seed=1)[0]
    window[5] *= 8
    message = decider(gate).step(window)
    assert message["ok"] is False and message["reason"] == "burst"
    assert message["event"] is None and message["rest"] is False


def test_single_spike_is_a_burst():
    gate = WindowGate(rest_windows())
    window = rest_windows(seed=1)[0]
    window[5, 100] = 50.0
    assert gate.check(window).reason == "burst"


def test_flat_window_makes_no_decision():
    """A dead channel after common average reference, which is not actually flat."""
    rest = rest_windows()
    window = np.random.default_rng(1).normal(size=(24, 320))
    window[3] = 0.0
    window = window - window.mean(axis=0, keepdims=True)
    assert np.abs(window[3]).max() > 0
    gate = WindowGate(rest)
    assert gate.check(window).reason == "flat"
    assert decider(gate).step(window)["event"] is None


def test_channel_dead_at_baseline_is_rejected():
    raw = np.random.default_rng(2).normal(size=(30, 24, 320))
    raw[:, 3] = 0.0
    rest = raw - raw.mean(axis=1, keepdims=True)
    assert WindowGate(rest).check(rest[0]).reason == "flat"


def test_nonfinite_window_is_rejected():
    window = rest_windows()[0]
    window[0, 0] = np.nan
    assert WindowGate(rest_windows()).check(window).reason == "nonfinite"


def test_no_baseline_fails_closed():
    message = decider(None).step(rest_windows()[0])
    assert message["ok"] is False and message["reason"] == "no_baseline"
    assert message["event"] is None


def small_model(tmp_path):
    data, cfg = fake_erd(n_trials=12)
    model = SessionModel(data.channels, data.classes, cfg, np.eye(4), None,
                         make_riemann().fit(data.X.astype(np.float64), data.y), "riemann",
                         "imagined")
    joblib.dump(model, tmp_path / "m.joblib")
    return tmp_path / "m.joblib", data.channels, cfg


def test_nonfinite_samples_reject_until_they_leave_the_window(tmp_path):
    path, channels, cfg = small_model(tmp_path)
    rng = np.random.default_rng(0)
    chunk = lambda n=40: (rng.normal(size=(n, 4)), np.arange(n) / 160.0)  # noqa: E731
    rest = [chunk() for _ in range(80)]
    session = LiveSession(path, inlet=FakeInlet(channels, 160.0, rest))
    assert session.collect_baseline(0.3)

    samples, stamps = chunk()
    samples[10, 2] = np.nan
    session.inlet.chunks = [(samples, stamps)] + [chunk() for _ in range(30)]
    decode = session.decode()
    messages = [m for m in (next(decode) for _ in range(31)) if m]
    reasons = [m["reason"] for m in messages]
    assert reasons[0] == "nonfinite"
    assert reasons.count("nonfinite") == 8  # the 2 s window at 0.25 s steps
    assert all(m["reason"] != "nonfinite" for m in messages[8:])
    assert any(m["ok"] for m in messages[8:])


def test_cue_with_nonfinite_samples_is_dropped(tmp_path):
    cfg = SignalConfig()
    n = int(30 * cfg.sfreq)
    eeg = np.random.default_rng(0).normal(size=(n, 2))
    eeg[int(5 * cfg.sfreq), 1] = np.inf
    cues = [{"onset_s": 4.0, "duration_s": 4.0, "label": "left"},
            {"onset_s": 12.0, "duration_s": 4.0, "label": "right"}]
    path = write_recording(tmp_path / "r.npz", eeg, np.arange(n) / cfg.sfreq, cfg.sfreq,
                           ["C3", "C4"], cues, 0.0, "real")
    data, _ = load_recording(path, ["C3", "C4"], ["left", "right"], cfg)
    assert set(data.y.tolist()) == {1}
    assert np.isfinite(data.X).all()


def test_verdict_files_are_plain_json(tmp_path):
    path = approve(tmp_path, "imagined")
    assert json.loads(path.with_suffix(".verdict.json").read_text())["go"] is True
    assert GoRule().symbols == 17
    assert len(CHANNELS_24) == 24


def test_calibrate_command_carries_movement_into_the_model(tmp_path):
    path = write_motor_recording(tmp_path / "r.npz", 0.9, movement="real", per_class=3)
    out = tmp_path / "out.joblib"
    assert main(["calibrate", str(path), "--pretrained", "none", "--out", str(out)]) == 0
    assert joblib.load(out).movement == "real"
    assert load_verdict(out)["movement"] == "real"


def test_live_command_uses_the_threshold_that_passed(tmp_path, monkeypatch):
    monkeypatch.setattr(verdict, "ARTIFACT_DIR", tmp_path)
    path = approve(tmp_path, "imagined", live={**GOOD_LIVE, "threshold": 0.7})
    calls = []
    monkeypatch.setattr(live, "run_live", lambda model, **options: calls.append((model, options)))
    assert main(["live"]) == 0
    assert calls[0][0] == path and calls[0][1]["threshold"] == 0.7


def test_incomplete_verdict_counts_as_missing(tmp_path):
    path = approve(tmp_path, "imagined")
    file = path.with_suffix(".verdict.json")
    record = json.loads(file.read_text())
    del record["offline"]
    file.write_text(json.dumps(record))
    assert load_verdict(path) is None
    with pytest.raises(Refused):
        choose_model(tmp_path)


NAN, INF = float("nan"), float("inf")


@pytest.mark.parametrize("bad", [NAN, INF, -0.1, 1.5, "0.9", True, None])
@pytest.mark.parametrize("field", ["left_right", "three_class"])
def test_broken_offline_scores_are_no_go(field, bad):
    assert not judge({**GOOD_OFFLINE, field: bad}, GOOD_LIVE, "imagined")[0]


@pytest.mark.parametrize("change", [
    {"false_per_min": NAN}, {"false_per_min": None}, {"false_per_min": -1},
    {"clean_s": NAN}, {"clean_s": INF, "false_per_min": NAN},
    {"correct": NAN}, {"correct": 25}, {"cues": NAN}, {"correct": "18"}])
def test_broken_live_scores_are_no_go(change):
    assert not judge(GOOD_OFFLINE, {**GOOD_LIVE, **change}, "imagined")[0]


def test_nan_scores_in_a_verdict_file_cannot_type(tmp_path):
    path = approve(tmp_path, "imagined")
    file = path.with_suffix(".verdict.json")
    record = json.loads(file.read_text())
    record["offline"]["left_right"] = NAN
    record["go"] = True
    file.write_text(json.dumps(record))
    with pytest.raises(Refused, match="left vs right"):
        choose_model(tmp_path)

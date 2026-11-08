import json
import tkinter

import numpy as np
import pytest

from eegmove import record
from eegmove.config import SignalConfig
from eegmove.datasets import load_recording, recording_movement
from eegmove.record import (Capture, CUE_BG, IMAGINED_PROMPTS, build_schedule, prompts_for,
                            run_session, save, snapshot_path, write_recording)
from synthetic import FakeCapture, FakeInlet


def test_imagined_prompts_say_keep_still():
    for label in ("left", "right"):
        big, small = prompts_for("imagined")[label]
        assert "imagine" in small and "still" in small
        assert "imagine" not in prompts_for("real")[label][1]
    with pytest.raises(ValueError, match="mode"):
        prompts_for("thinking")


class FakeTk:
    """Runs scheduled callbacks in order, then does what a test asks."""

    instances = []

    def __init__(self):
        self.queue, self.protocols, self.commands, self.colors = [], {}, {}, []
        self.destroyed = False
        FakeTk.instances.append(self)

    def title(self, *_): pass
    def attributes(self, *_): pass
    def geometry(self, *_): pass
    def bind(self, *_): pass
    def unbind(self, *_): pass
    def update(self): pass
    def destroy(self): self.destroyed = True
    def protocol(self, name, handler): self.protocols[name] = handler
    def createcommand(self, name, handler): self.commands[name] = handler
    def after(self, _ms, callback): self.queue.append(callback)
    def configure(self, **options): self.colors.append(options.get("bg"))

    def mainloop(self):
        for _ in range(FakeTk.steps):
            if self.queue and not self.destroyed:
                self.queue.pop(0)()
        FakeTk.on_idle(self)


class FakeLabel:
    labels = []

    def __init__(self, root, **options):
        FakeLabel.labels.append(self)
        self.backgrounds = [options.get("bg")]

    def pack(self, **_): pass
    def configure(self, **options): self.backgrounds.append(options.get("bg"))


@pytest.fixture
def session(monkeypatch, tmp_path):
    FakeTk.instances, FakeLabel.labels = [], []
    FakeTk.steps, FakeTk.on_idle = 30, lambda root: None
    monkeypatch.setattr(tkinter, "Tk", FakeTk)
    monkeypatch.setattr(tkinter, "Label", FakeLabel)
    monkeypatch.setattr(record, "Capture", FakeCapture)

    def start(name="imagined", **options):
        out = tmp_path / name
        run_session(out, ["rest", "left", "right"], 2, 1, 0, use_lsl=True, stream=None,
                    baseline_s=1.0, fullscreen=False, autostart=True, movement=name, **options)
        return out

    return start


def test_cue_screens_share_one_background(session):
    session()
    root = FakeTk.instances[0]
    seen = {c for c in root.colors if c} | {b for label in FakeLabel.labels for b in label.backgrounds}
    assert seen == {CUE_BG}


@pytest.mark.parametrize("how", ["protocol", "command"])
def test_window_close_saves(session, how):
    def close(root):
        handler = (root.protocols["WM_DELETE_WINDOW"] if how == "protocol"
                   else root.commands["tk::mac::Quit"])
        handler()

    FakeTk.on_idle = close
    out = session()
    saved = np.load(out.with_suffix(".npz"))
    assert str(saved["mode"]) == "imagined"
    assert FakeTk.instances[0].destroyed


def test_interrupt_inside_mainloop_still_saves(session, tmp_path):
    def interrupt(root):
        raise KeyboardInterrupt

    FakeTk.on_idle = interrupt
    with pytest.raises(KeyboardInterrupt):
        session()
    assert recording_movement(tmp_path / "imagined.npz") == "imagined"


def test_closing_before_go_saves_nothing(session):
    FakeTk.steps = 0
    FakeTk.on_idle = lambda root: root.protocols["WM_DELETE_WINDOW"]()
    out = session()
    assert not out.with_suffix(".npz").exists()


def test_existing_recording_is_not_overwritten(session, tmp_path):
    (tmp_path / "imagined.npz").write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        session()
    assert (tmp_path / "imagined.npz").read_bytes() == b"keep me"


def test_leftover_snapshot_is_not_overwritten(session, tmp_path):
    snapshot = snapshot_path(tmp_path / "imagined")
    snapshot.write_bytes(b"crash data")
    with pytest.raises(FileExistsError, match="didn't finish"):
        session()
    assert snapshot.read_bytes() == b"crash data"


def test_failed_snapshot_keeps_sampling(tmp_path, capsys):
    sfreq = 160.0
    blocked = tmp_path / "a-file"
    blocked.write_text("not a folder")
    chunks = [(np.zeros((16, 2)), np.arange(16) / sfreq + i) for i in range(5)]
    capture = Capture(None, inlet=FakeInlet(chunks=chunks), snapshot=blocked / "s.npz",
                      snapshot_every_s=0.0)
    capture.set_session([{"onset_s": 0.0, "duration_s": 1.0, "label": "rest"}], 0.0, "real")
    capture.start()
    capture.join(timeout=0.5)
    capture.running = False
    capture.join(timeout=2)
    assert capture.error is None and capture.snapshot_error is not None
    assert len(capture.drain()[0]) == 80
    assert capsys.readouterr().out.count("crash snapshot failed") == 1


def test_mode_is_saved_in_recording(tmp_path):
    capture = FakeCapture()
    cues = build_schedule(["rest", "left"], 1, 1, 0, baseline_s=1.0)
    save(tmp_path / "a", cues, capture, 0.0, True, "real")
    assert recording_movement(tmp_path / "a.npz") == "real"
    save(tmp_path / "b", cues, None, 0.0, False, "imagined")
    log = json.loads((tmp_path / "b.json").read_text())
    assert log["mode"] == "imagined"
    assert recording_movement(tmp_path / "recording.cnt", tmp_path / "b.json") == "imagined"


def test_recording_without_a_mode_is_unknown(tmp_path):
    np.savez(tmp_path / "old.npz", eeg=np.zeros((2, 2)))
    assert recording_movement(tmp_path / "old.npz") == "unknown"
    assert recording_movement(tmp_path / "x.cnt") == "unknown"


def test_snapshot_survives_a_crash(tmp_path):
    """The snapshot is a complete recording on its own, and loads like one."""
    sfreq = 160.0
    n = int(40 * sfreq)
    inlet = FakeInlet(chunks=[(np.random.default_rng(0).normal(size=(n, 2)), np.arange(n) / sfreq)])
    out = tmp_path / "session"
    capture = Capture(None, inlet=inlet, snapshot=snapshot_path(out), snapshot_every_s=0.0)
    cues = [{"onset_s": 0.0, "duration_s": 10.0, "label": "baseline"},
            {"onset_s": 12.0, "duration_s": 4.0, "label": "left"},
            {"onset_s": 18.0, "duration_s": 4.0, "label": "rest"}]
    capture.set_session(cues, 0.0, "imagined")
    capture.start()
    capture.join(timeout=0.5)
    capture.running = False  # the process would simply die here, with no save() call
    capture.join(timeout=2)
    path = snapshot_path(out)
    assert path.name == "session.snapshot.npz"
    data, baseline = load_recording(path, ["C3", "C4"], ["rest", "left"], SignalConfig())
    assert len(data) > 0 and len(baseline) > 0
    assert recording_movement(path) == "imagined"


def test_capture_errors_are_kept_not_swallowed():
    class Broken(FakeInlet):
        def pull(self, timeout=0.1):
            raise OSError("stream lost")

    capture = Capture(None, inlet=Broken())
    capture.start()
    capture.join(timeout=2)
    assert isinstance(capture.error, OSError)


def test_final_save_removes_the_snapshot(tmp_path):
    out = tmp_path / "session"
    snapshot_path(out).write_bytes(b"old")
    save(out, [{"onset_s": 0.0, "duration_s": 1.0, "label": "baseline"}], FakeCapture(), 0.0, True)
    assert not snapshot_path(out).exists()


def test_dropped_samples_keep_labels_aligned(tmp_path):
    """Drop 1 s inside a cue: labelled data must stop where the cue really stopped."""
    cfg = SignalConfig()
    sfreq = cfg.sfreq
    keep = np.r_[0:int(10 * sfreq), int(11 * sfreq):int(30 * sfreq)]
    stamps = 50 + np.arange(int(30 * sfreq))[keep] / sfreq
    eeg = np.zeros((len(stamps), 2))
    cues = [{"onset_s": 8.0, "duration_s": 6.0, "label": "left"},
            {"onset_s": 20.0, "duration_s": 4.0, "label": "rest"}]
    path = write_recording(tmp_path / "gap.npz", eeg, stamps, sfreq, ["C3", "C4"], cues, 50.0, "real")

    saved = np.load(path)
    elapsed = saved["timestamps"] - saved["timestamps"][0]
    # After the gap, position 19 s of samples is 20 s of real time.
    data, _ = load_recording(path, ["C3", "C4"], ["rest", "left"], cfg)
    assert elapsed[int(19 * sfreq)] == pytest.approx(20.0)
    # 8-14 s real time holds 5 s of samples, minus the 0.5 s offset: crops at 8.5...10.5 of samples.
    assert (data.y == 1).sum() == 6
    assert (data.y == 0).sum() == 4


def test_default_cue_wording_covers_the_default_classes():
    from eegmove.config import DEFAULT_CLASSES

    assert set(DEFAULT_CLASSES) <= set(IMAGINED_PROMPTS)

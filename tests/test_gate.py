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

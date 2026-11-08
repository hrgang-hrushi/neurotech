"""Segments, labeled events and training (the features real eego files need)."""
import os
import warnings
from pathlib import Path

import numpy as np
import pytest

from eeg_morse import decode, load, preset
from eeg_morse.detect import Segment
from eeg_morse.io import Annotation, Recording, read_seg_file, segments_from_impedance
from eeg_morse.simulate import simulate
from eeg_morse.train import match, train

warnings.filterwarnings("ignore")


def test_seg_file_with_implicit_first_segment(tmp_path):
    p = tmp_path / "r.seg"
    p.write_text("NumberSegments=      3\n4.6e4 0.5 100\n4.6e4 0.1 200\n")
    assert read_seg_file(p, 350) == [(0, 50), (50, 150), (150, 350)]
    assert read_seg_file(p, 250) is None  # listed segments longer than the file -> ignored


def test_segments_from_impedance_pairs():
    assert segments_from_impedance([5764, 5767, 25519, 25523, 84509], 84512) == [
        (0, 5767), (5767, 25523), (25523, 84512)]


def test_match_prefers_overlap_over_order():
    segs = [Segment(130.4, 133.3), Segment(136.2, 139.0)]
    anns = [Annotation(128.9, 0.7, "Long"), Annotation(131.0, 4.8, "Long"),
            Annotation(137.7, 4.4, "Long")]
    m, unmatched = match(segs, anns, tol_s=1.0)
    assert [x.hit for x in m] == [False, True, True] and unmatched == []


def segmented_clench(seed=0):
    """Two 'resumed' segments with a large DC jump and a contact change between them."""
    a, _ = simulate("TTT", preset="clench", seed=seed)
    b, truth_b = simulate("E E", preset="clench", seed=seed + 1)
    _, truth_a = simulate("TTT", preset="clench", seed=seed)
    data = np.concatenate([a.data + 20000.0, 1.8 * b.data - 15000.0], axis=1)
    off = a.data.shape[1] / a.sfreq
    anns = [Annotation(float(x), float(y - x), "Clench") for x, y in zip(truth_a.t_on, truth_a.t_off)]
    anns += [Annotation(float(x + off), float(y - x), "Clench") for x, y in zip(truth_b.t_on, truth_b.t_off)]
    return Recording(data, a.sfreq, a.ch_names, annotations=anns,
                     segments=[(0, a.data.shape[1]), (a.data.shape[1], data.shape[1])])


def test_decode_handles_pause_and_dc_jump():
    rec = segmented_clench()
    res = decode(rec, preset("clench"))
    assert res.text == "TTT E E"  # the pause is a word break, no fake key-down at the jump


def test_train_finds_all_labeled_events(tmp_path):
    rec = segmented_clench(3)
    res = train(rec, preset("clench"), ["clench"])
    assert res.score.recall == 1.0 and res.score.false_alarms == 0
    res.config.save(tmp_path / "m.json")
    assert decode(segmented_clench(5), res.config).text == "TTT E E"


def test_train_learns_short_long_boundary():
    a, ta = simulate("EEEE", preset="blink", seed=1)  # short = dots
    b, tb = simulate("TTTT", preset="blink", seed=2)  # long = dashes
    off = a.data.shape[1] / a.sfreq
    anns = [Annotation(float(x), float(y - x), "Short Blink") for x, y in zip(ta.t_on, ta.t_off)]
    anns += [Annotation(float(x + off), float(y - x), "Long Blink") for x, y in zip(tb.t_on, tb.t_off)]
    rec = Recording(np.concatenate([a.data, b.data], axis=1), a.sfreq, a.ch_names,
                    annotations=anns, segments=[(0, a.data.shape[1]), (a.data.shape[1], a.data.shape[1] + b.data.shape[1])])
    res = train(rec, preset("blink"), ["blink"], short="short", long="long")
    assert res.short_long is not None and res.short_long.accuracy == 1.0
    assert 0.4 < res.short_long.threshold_s < 1.2


REAL = os.environ.get("EEG_MORSE_REAL_CNT")


@pytest.mark.skipif(not REAL or not Path(REAL).exists(), reason="set EEG_MORSE_REAL_CNT to a labeled eego .cnt")
def test_real_recording_clench():  # pragma: no cover - needs a local recording
    pytest.importorskip("antio")
    rec = load(REAL)
    res = train(rec, preset("clench"), ["clench"])
    assert res.score.recall == 1.0 and res.score.false_alarms == 0

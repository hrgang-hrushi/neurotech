import numpy as np

from eeg_morse import morse
from eeg_morse.config import DetectConfig, TimingConfig
from eeg_morse.detect import Segment, clean, detect, hysteresis, otsu, runs
from eeg_morse.timing import estimate_unit, transcribe


def segments_for(text: str, unit: float, bias: float = 0.0, t0: float = 1.0) -> list[Segment]:
    """Ideal key-down intervals for `text`, each lengthened by `bias`."""
    segs, t = [], t0
    words = morse.encode(text)
    for wi, w in enumerate(words):
        for li, code in enumerate(w):
            for ei, sym in enumerate(code):
                d = unit * (1 if sym == "." else 3)
                segs.append(Segment(t - bias / 2, t + d + bias / 2))
                t += d + (unit if ei < len(code) - 1 else 0)
            t += 3 * unit if li < len(w) - 1 else 0
        t += 7 * unit if wi < len(words) - 1 else 0
    return segs


def test_transcribe_ideal_timing():
    tr = transcribe(segments_for("SOS HELP", 0.5), TimingConfig())
    assert tr.text == "SOS HELP"
    assert abs(tr.unit_s - 0.5) < 1e-6


def test_bias_is_estimated_and_corrected():
    # every key-down 40% of a unit too long, gaps correspondingly short
    tr = transcribe(segments_for("THE QUICK FOX", 1.0, bias=0.4), TimingConfig())
    assert tr.text == "THE QUICK FOX"
    assert abs(tr.unit_s - 1.0) < 0.05 and abs(tr.bias_s - 0.4) < 0.05


def test_unit_falls_back_when_only_dots():
    unit, bias, src = estimate_unit([0.5, 0.52, 0.49], TimingConfig(default_unit_s=0.5))
    assert src.startswith("default") and unit == 0.5
    assert transcribe(segments_for("E E E", 0.5), TimingConfig(default_unit_s=0.5)).text == "E E E"


def test_short_blips_are_ignored():
    segs = segments_for("SOS", 1.0)
    segs.insert(3, Segment(segs[2].t_off + 1.5, segs[2].t_off + 1.6))  # 0.1 s blip in a letter gap
    tr = transcribe(sorted(segs, key=lambda s: s.t_on), TimingConfig())
    assert tr.text == "SOS"


def test_otsu_on_bimodal():
    rng = np.random.default_rng(0)
    x = np.concatenate([rng.normal(0, 1, 2000), rng.normal(10, 1, 1000)])
    thr, mu0, mu1, eta = otsu(x)
    assert 3 < thr < 7 and eta > 0.8


def test_hysteresis_and_cleaning():
    a = np.array([0, 0, 5, 5, 3, 5, 5, 0, 0, 0, 5, 0, 0], float)
    st = hysteresis(a, lo=2, hi=4)
    assert st.tolist() == [0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 1, 0, 0]
    iv = clean(runs(st), rate=1.0, min_on_s=2, min_off_s=1)
    assert iv == [(2, 7)]


def test_detect_square_wave():
    rate = 50.0
    t = np.arange(0, 20, 1 / rate)
    act = ((t > 5) & (t < 6)) * 1.0 + ((t > 8) & (t < 11)) * 1.0
    act += np.random.default_rng(1).normal(0, 0.05, t.size)
    segs, th = detect(t, act, rate, DetectConfig())
    assert len(segs) == 2
    assert abs(segs[0].duration - 1.0) < 0.1 and abs(segs[1].duration - 3.0) < 0.1

"""End-to-end on SIMULATED eego-like recordings (see eeg_morse/simulate.py)."""
import json
import warnings

import numpy as np
import pytest

from eeg_morse import PipelineConfig, calibrate, decode, load, preset
from eeg_morse.__main__ import main
from eeg_morse.io import Recording, save_npz
from eeg_morse.simulate import simulate
from eeg_morse.stream import ReplayInlet, StreamingDecoder, run_live

warnings.filterwarnings("ignore", message="channels not found")
MSG = "SOS HELP 42"


@pytest.mark.parametrize("name", ["clench", "blink"])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_offline_decodes_exactly(name, seed):
    rec, _ = simulate(MSG, preset=name, seed=seed)
    assert decode(rec, preset(name)).text == MSG


def test_offline_motor_slow_units():
    # Motor ERD is slow and noisy: use ~1.5 s dots. Allow one wrong character.
    ok = 0
    for seed in range(5):
        rec, _ = simulate(MSG, preset="motor", seed=seed, unit_s=1.5)
        text = decode(rec, preset("motor")).text
        ok += sum(a != b for a, b in zip(text, MSG)) + abs(len(text) - len(MSG)) <= 1
    assert ok >= 4


def test_motor_sparse_cap_with_known_unit():
    # 9-channel montage: preset channels that are missing are skipped. With few
    # channels ERD is noisier, so pass the unit (from `calibrate` or --unit).
    ch = ["C3", "Cz", "C4", "Fz", "Pz", "O1", "O2", "T7", "T8"]
    cfg = preset("motor", timing=dict(unit_s=1.5))
    ok = sum(decode(simulate("HELP", preset="motor", seed=s, unit_s=1.5, channels=ch)[0], cfg).text
             == "HELP" for s in range(4))
    assert ok >= 3


def test_report_is_json_serialisable():
    rec, _ = simulate("HI", preset="clench", seed=0)
    rep = decode(rec, preset("clench")).report()
    s = json.dumps(rep)
    assert rep["text"] == "HI" and rep["morse"] == ".... .." and "separability" in s


def test_no_activity_gives_warning():
    rec = Recording(np.random.default_rng(0).normal(size=(4, 500 * 20)), 500.0,
                    ["T7", "T8", "C3", "C4"])
    res = decode(rec, preset("clench"))
    assert res.warnings  # weak contrast or nothing detected


def test_calibrate_round_trip(tmp_path):
    rec, _ = simulate("PARIS", preset="clench", seed=5)
    cal = calibrate(rec, preset("clench"), "PARIS")
    assert cal.result.text == "PARIS" and cal.text_similarity == 1.0
    path = tmp_path / "cal.json"
    cal.config.save(path)
    cfg = PipelineConfig.load(path)
    rec2, _ = simulate(MSG, preset="clench", seed=6)
    assert decode(rec2, cfg).text == MSG


@pytest.mark.parametrize("name", ["clench", "blink"])
def test_streaming_after_calibration_matches(name):
    cal = calibrate(simulate("PARIS", preset=name, seed=9)[0], preset(name), "PARIS").config
    rec, _ = simulate(MSG, preset=name, seed=4)
    dec = StreamingDecoder(cal, rec.sfreq, rec.ch_names, rest_s=5.0)
    rng = np.random.default_rng(0)
    pos = 0
    while pos < rec.data.shape[1]:  # irregular chunk sizes, like LSL
        n = int(rng.integers(1, 300))
        dec.push(rec.data[:, pos:pos + n])
        pos += n
    dec.flush()
    assert dec.text == MSG


def test_streaming_warm_up_then_lock():
    rec, _ = simulate("PARIS " + MSG, preset="clench", seed=3)
    dec = StreamingDecoder(preset("clench"), rec.sfreq, rec.ch_names, rest_s=5.0)
    events = dec.push(rec.data) + dec.flush()
    kinds = [e.kind for e in events]
    assert kinds[0] == "ready" and "locked" in kinds
    assert dec.text.endswith(MSG)


def test_run_live_with_replay_inlet():
    rec, _ = simulate("HI", preset="clench", seed=1)
    cal = calibrate(rec, preset("clench"), "HI").config
    seen = []
    dec = run_live(ReplayInlet(rec, speed=None), rec.sfreq, rec.ch_names, cal,
                   rest_s=5.0, on_event=seen.append)
    assert dec.text == "HI" and any(e.kind == "letter" for e in seen)


def test_io_npz_and_csv_round_trip(tmp_path):
    rec, _ = simulate("E", preset="clench", seed=0)
    save_npz(rec, tmp_path / "r.npz")
    back = load(tmp_path / "r.npz")
    assert back.ch_names == rec.ch_names and back.sfreq == rec.sfreq
    assert np.allclose(back.data, rec.data, atol=1e-3)
    csv = tmp_path / "r.csv"
    assert main(["simulate", "HI", "--preset", "clench", "--out", str(csv)]) == 0
    assert decode(load(csv), preset("clench")).text == "HI"


def test_cli_decode_writes_outputs(tmp_path, capsys):
    npz = tmp_path / "s.npz"
    assert main(["simulate", "OK", "--preset", "clench", "--out", str(npz)]) == 0
    out_json, out_png = tmp_path / "r.json", tmp_path / "r.png"
    assert main(["decode", str(npz), "--preset", "clench", "--json", str(out_json),
                 "--plot", str(out_png)]) == 0
    assert json.loads(out_json.read_text())["text"] == "OK"
    assert out_png.stat().st_size > 10_000
    assert "text  : OK" in capsys.readouterr().out


def test_cli_missing_file_is_clean_error():
    assert main(["decode", "does-not-exist.cnt"]) == 2

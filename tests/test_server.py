"""Upload validation and the HTTP decode API (eeg_morse.uploads, eeg_morse.server)."""
import io
import warnings

import pytest
from fastapi.testclient import TestClient

from eeg_morse import uploads
from eeg_morse.io import save_npz
from eeg_morse.server import create_app
from eeg_morse.simulate import REAL_CAP_CLENCH_WEIGHT, simulate
from eeg_morse.uploads import Incoming, UploadError, plan, safe_name, stage

warnings.filterwarnings("ignore")


LOCAL = "http://127.0.0.1:8770"


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app(), base_url=LOCAL)


@pytest.fixture(scope="module")
def question_npz(tmp_path_factory):
    rec, _ = simulate("HOW ARE YOU", preset="clench", seed=1, artifacts=1.5,
                      emg_weight=REAL_CAP_CLENCH_WEIGHT)
    path = tmp_path_factory.mktemp("rec") / "question.npz"
    save_npz(rec, path)
    return path


# --- uploads -----------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("../../etc/passwd", "passwd"),
    ("C:\\Users\\me\\session.cnt", "session.cnt"),
    ("my session (1).cnt", "my session _1_.cnt"),
    (".hidden.npz", "hidden.npz"),
])
def test_safe_name_strips_paths_and_odd_characters(raw, expected):
    assert safe_name(raw) == expected


def test_safe_name_rejects_empty():
    with pytest.raises(UploadError):
        safe_name("../")


def test_plan_accepts_cnt_with_sidecars():
    assert plan(["s.cnt", "s.evt", "S.SEG"]) == "s.cnt"


@pytest.mark.parametrize("names, message", [
    ([], "No files"),
    (["a.exe"], "Unsupported"),
    (["a.cnt", "b.npz"], "exactly one"),
    (["a.cnt", "b.evt"], "does not match"),
    (["a.npz", "a.seg"], "only belongs next to"),
    (["a.evt"], "exactly one"),
    (["a.cnt", "a.evt", "a.seg", "a.npz"], "one recording at a time"),
])
def test_plan_rejects_bad_sets(names, message):
    with pytest.raises(UploadError, match=message):
        plan(names)


def test_stage_aligns_sidecar_stems(tmp_path):
    files = [Incoming("Session.cnt", io.BytesIO(b"x")), Incoming("session.SEG", io.BytesIO(b"y"))]
    main = stage(files, tmp_path)
    assert main.name == "Session.cnt" and (tmp_path / "Session.seg").read_bytes() == b"y"


def test_stage_enforces_size_limit(tmp_path):
    with pytest.raises(UploadError) as e:
        stage([Incoming("a.npz", io.BytesIO(b"0" * 100))], tmp_path, max_bytes=10)
    assert e.value.status == 413


def test_stage_rejects_empty_file(tmp_path):
    with pytest.raises(UploadError, match="empty"):
        stage([Incoming("a.npz", io.BytesIO(b""))], tmp_path)


# --- HTTP API ------------------------------------------------------------------

def test_health_lists_models(client):
    body = client.get("/api/health").json()
    assert body["success"] and body["error"] is None
    assert body["data"]["models"][0] == "clench"


def test_decode_question_end_to_end(client, question_npz):
    with question_npz.open("rb") as f:
        r = client.post("/api/recordings/decode", files={"files": ("question.npz", f)},
                        data={"expected": "how are you"})
    body = r.json()
    assert r.status_code == 200 and body["success"], body["error"]
    data = body["data"]
    assert data["text"] == "How are you?"
    assert data["sentence_types"] == ["question"]
    assert data["score"] == {"expected": "HOW ARE YOU", "cer": 0.0, "exact": True}
    assert data["quality"]["n_artifacts"] > 0 and data["quality"]["artifact_aware"]
    assert {a["kind"] for a in data["artifacts"]} <= {"blink", "eye_movement", "electrode_pop"}
    assert len(data["trace"]["t"]) == len(data["trace"]["activation"]) <= 4000
    assert all(e["symbol"] in ".-" for e in data["elements"])


def test_decode_rejects_unsupported_type_with_envelope(client):
    r = client.post("/api/recordings/decode", files={"files": ("notes.docx", b"hello")})
    assert r.status_code == 400
    assert r.json() == {"success": False, "data": None, "error": r.json()["error"]}
    assert "Unsupported" in r.json()["error"]


def test_decode_rejects_corrupt_npz_before_loading(client):
    r = client.post("/api/recordings/decode", files={"files": ("broken.npz", b"not a zip")})
    assert r.status_code == 400 and "not a valid .npz" in r.json()["error"]


def test_decode_unknown_model(client, question_npz):
    with question_npz.open("rb") as f:
        r = client.post("/api/recordings/decode", files={"files": ("q.npz", f)},
                        data={"model": "nope"})
    assert r.status_code == 422 and "Unknown model" in r.json()["error"]


def test_decode_without_files_uses_envelope(client):
    r = client.post("/api/recordings/decode")
    assert r.status_code == 422 and r.json()["success"] is False


def test_decode_bad_sfreq(client, question_npz):
    with question_npz.open("rb") as f:
        r = client.post("/api/recordings/decode", files={"files": ("q.npz", f)},
                        data={"sfreq": "-5"})
    assert r.status_code == 400 and "sfreq" in r.json()["error"]


def test_cors_allows_dashboard_origin(client):
    r = client.options("/api/recordings/decode", headers={
        "Origin": "http://localhost:3088", "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3088"


def test_cors_blocks_other_origins(client):
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


# --- security ------------------------------------------------------------------

def test_foreign_host_header_rejected(client):
    """DNS rebinding: a hostile domain resolving to 127.0.0.1 keeps its own Host header."""
    assert client.get("/api/health", headers={"Host": "evil.example.com"}).status_code == 400


def test_cross_site_post_rejected_before_decoding(client, question_npz):
    with question_npz.open("rb") as f:
        r = client.post("/api/recordings/decode", files={"files": ("q.npz", f)},
                        headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["success"] is False


def test_oversized_content_length_rejected_early(client, monkeypatch):
    from eeg_morse import server
    monkeypatch.setattr(server, "MAX_BODY_BYTES", 10)
    r = TestClient(server.create_app(), base_url=LOCAL).post(
        "/api/recordings/decode", files={"files": ("a.npz", b"0" * 100)})
    assert r.status_code == 413


def test_npz_decompression_bomb_rejected(client, tmp_path):
    import numpy as np
    bomb = tmp_path / "bomb.npz"
    np.savez_compressed(bomb, data=np.zeros((4, 20_000_000), dtype=np.float32), sfreq=500.0,
                        ch_names=np.array(["a", "b", "c", "d"]))
    with bomb.open("rb") as f:
        r = client.post("/api/recordings/decode", files={"files": ("bomb.npz", f)})
    assert r.status_code == 413 and "too large" in r.json()["error"]


def test_errors_do_not_leak_temp_paths(client):
    r = client.post("/api/recordings/decode", files={"files": ("x.csv", b"a,b\n1,2\n")})
    assert r.status_code == 422
    assert "eeg_upload_" not in r.json()["error"] and "/tmp" not in r.json()["error"]


def test_wildcard_cors_origin_refused(monkeypatch):
    from eeg_morse import server
    monkeypatch.setenv(server.CORS_ENV, "*")
    with pytest.raises(ValueError, match="no"):
        server.create_app()


def test_serve_refuses_public_interface():
    from eeg_morse import server
    with pytest.raises(ValueError, match="refusing"):
        server.serve("0.0.0.0", 0)


def test_upload_limit_constant_is_sane():
    assert uploads.MAX_TOTAL_BYTES >= 100 * 1024 * 1024


def test_long_names_keep_their_extension():
    assert safe_name("x" * 300 + ".npz").endswith(".npz")


def test_nan_channel_is_dropped_not_fatal(client, tmp_path):
    import numpy as np
    rec, _ = simulate("TEST", preset="clench", seed=2)
    rec.data[3, 100] = np.nan
    path = tmp_path / "nan.npz"
    save_npz(rec, path)
    with path.open("rb") as f:
        r = client.post("/api/recordings/decode", files={"files": ("nan.npz", f)})
    body = r.json()
    assert r.status_code == 200, body["error"]
    assert rec.ch_names[3] in body["data"]["bad_channels"]
    assert any("NaN" in w for w in body["data"]["quality"]["warnings"])
    # a NaN channel decodes exactly like the same recording without it
    from eeg_morse.service import DecodeRequest, decode_file
    clean_path = tmp_path / "clean.npz"
    rec.data[3, 100] = 0.0
    save_npz(rec, clean_path)
    assert body["data"]["raw_text"] == decode_file(DecodeRequest(clean_path, "clean.npz"))["raw_text"]


def test_too_low_sampling_rate_is_a_clear_422(client, tmp_path):
    import numpy as np
    path = tmp_path / "slow.npz"
    np.savez(path, data=np.random.default_rng(0).normal(size=(4, 2000)), sfreq=50.0,
             ch_names=np.array(["T7", "T8", "Fp1", "Fp2"]))
    with path.open("rb") as f:
        r = client.post("/api/recordings/decode", files={"files": ("slow.npz", f)})
    assert r.status_code == 422 and "too low" in r.json()["error"]


def test_noise_recording_produces_no_invented_sentence(tmp_path):
    """Real-data regression (7-8 Nov): weak contrast must not be 'corrected' into fake words."""
    import numpy as np
    from eeg_morse.service import DecodeRequest, decode_file
    from eeg_morse.simulate import EEGO_32
    rng = np.random.default_rng(0)
    path = tmp_path / "noise.npz"
    np.savez(path, data=rng.normal(scale=10.0, size=(len(EEGO_32), 500 * 60)), sfreq=500.0,
             ch_names=np.array(EEGO_32))
    out = decode_file(DecodeRequest(path, "noise.npz"))
    assert out["reliable"] is False
    assert out["text"] == "" and out["sentence_types"] == [] and out["corrections"] == []
    assert out["corrected_text"] == out["raw_text"]
    assert out["quality"]["warnings"][0].startswith("No clear Morse signal")


def test_clean_recording_is_reliable(question_npz):
    from eeg_morse.service import DecodeRequest, decode_file
    out = decode_file(DecodeRequest(question_npz, "q.npz"))
    assert out["reliable"] is True and out["text"] == "How are you?"


def test_disconnected_cap_gets_a_clear_message(tmp_path):
    """Real-data regression (Kevin, 8 Nov): 20 flat channels + 4 saturated ones."""
    import numpy as np
    from eeg_morse.service import DecodeRequest, decode_file
    from eeg_morse.simulate import EEGO_32
    data = np.zeros((len(EEGO_32), 500 * 20))
    data[:4] = 40_000.0 + np.random.default_rng(0).normal(scale=8_000.0, size=(4, 500 * 20))
    path = tmp_path / "disconnected.npz"
    np.savez(path, data=data, sfreq=500.0, ch_names=np.array(EEGO_32))
    with pytest.raises(ValueError, match="cap was probably not connected"):
        decode_file(DecodeRequest(path, "disconnected.npz"))

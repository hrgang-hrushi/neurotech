import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from eegmove.morse import ACCEPT, DELETE, MAX_SEQUENCE, MORSE, MorseTyper, SimulatedKeys
from eegmove.typing_app import drain_socket
from eegmove.words import WordList, load_words


class Stream:
    """Feeds a typer the way the decoder does: one numbered message per 0.25 s step."""

    def __init__(self, typer, run="a"):
        self.typer, self.run, self.seq = typer, run, -1

    def send(self, event=None, state="rest", rest=True, ok=True, **extra):
        self.seq += 1
        message = {"run": self.run, "seq": self.seq, "ok": ok, "rest": rest, "step_s": 0.25,
                   "state": state, "event": event, "source": "eeg", "reason": None, **extra}
        self.typer.feed(message)
        return message

    def rest(self, seconds):
        for _ in range(int(seconds / 0.25)):
            self.send()

    def symbols(self, code):
        for symbol in code:
            self.send(event={".": "left", "-": "right"}[symbol], state="left")
            self.rest(1.0)

    def letter(self, code):
        self.symbols(code)
        self.rest(3.0)


@pytest.fixture
def typed():
    typer = MorseTyper(WordList(["hello", "help", "water"]))
    return typer, Stream(typer)


def test_morse_table_is_complete_and_unique():
    assert sorted(MORSE.values()) == [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    assert len(MORSE) == 26
    assert DELETE not in MORSE and ACCEPT not in MORSE
    assert max(map(len, MORSE)) == MAX_SEQUENCE


@pytest.mark.parametrize("code,letter", list(MORSE.items()))
def test_sequence_becomes_letter_after_gap(code, letter):
    typer = MorseTyper()
    stream = Stream(typer)
    stream.symbols(code)
    assert typer.view().sequence == code
    stream.rest(3.0)
    assert typer.view().text == letter and typer.view().sequence == ""


def test_letter_waits_for_the_full_gap(typed):
    typer, stream = typed
    stream.send(event="left", state="left")
    stream.rest(2.75)
    assert typer.text == "" and typer.sequence == "."
    stream.send()
    assert typer.text == "E"


def test_a_symbol_restarts_the_gap(typed):
    typer, stream = typed
    stream.send(event="left", state="left")
    stream.rest(2.75)
    stream.send(event="right", state="right")
    stream.rest(2.75)
    assert typer.text == "" and typer.sequence == ".-"


def test_invalid_sequence_types_nothing(typed):
    typer, stream = typed
    stream.letter(".-.-")
    assert typer.text == ""
    assert "isn't a letter" in typer.warning


def test_overlong_sequence_is_rejected_at_the_limit(typed):
    typer, stream = typed
    stream.symbols("....")
    assert typer.sequence == "...."
    stream.symbols(".")
    assert typer.sequence == ""
    assert "too long" in typer.warning
    stream.rest(8.0)
    assert typer.text == ""


def test_four_dashes_delete_last_letter(typed):
    typer, stream = typed
    stream.letter("....")
    stream.letter("..")
    assert typer.text == "HI"
    stream.letter(DELETE)
    assert typer.text == "H"


def test_delete_on_empty_text_is_safe(typed):
    typer, stream = typed
    stream.letter(DELETE)
    assert typer.text == ""


def test_word_gap_adds_one_space(typed):
    typer, stream = typed
    stream.letter("..")
    stream.rest(30.0)
    assert typer.text == "I "


def test_word_gap_on_empty_text_adds_nothing(typed):
    typer, stream = typed
    stream.rest(30.0)
    assert typer.text == ""


def test_stalled_stream_does_not_end_the_letter(typed):
    typer, stream = typed
    stream.send(event="left", state="left")
    stream.rest(2.0)
    # Nothing arrives for a minute. Wall-clock fields jump, and only messages move the clock.
    stream.send(t=9999.0, lsl_time=9999.0)
    assert typer.text == "" and typer.sequence == "."


def test_rejected_window_does_not_advance_the_gap(typed):
    typer, stream = typed
    stream.send(event="left", state="left")
    for _ in range(40):
        stream.send(ok=False, reason="burst")
    assert typer.text == "" and typer.sequence == "."
    assert "burst" in typer.warning


def test_low_confidence_hold_does_not_end_a_letter(typed):
    typer, stream = typed
    stream.send(event="left", state="left")
    for _ in range(60):
        stream.send(state="left", rest=False)
    assert typer.text == "" and typer.sequence == "."


def test_uncertainty_longer_than_both_timers_keeps_the_letter_open(typed):
    typer, stream = typed
    stream.send(event="left", state="left")
    for _ in range(60):  # released to idle, and rest still doesn't lead
        stream.send(state="rest", rest=False)
    assert typer.text == "" and typer.sequence == "."
    assert typer.view().uncertain


def test_a_hold_restarts_the_clock(typed):
    typer, stream = typed
    stream.send(event="left", state="left")
    stream.rest(2.75)
    stream.send(state="left", rest=False)
    stream.rest(2.75)
    assert typer.text == ""


def test_duplicate_or_old_message_is_ignored(typed):
    typer, stream = typed
    message = stream.send(event="left", state="left")
    typer.feed(message)
    typer.feed({**message, "seq": message["seq"] - 1})
    assert typer.sequence == "."


def test_new_run_resets_sequence_tracking(typed):
    typer, stream = typed
    for _ in range(50):
        stream.send()
    stream.symbols("..")
    restarted = Stream(typer, run="b")
    assert typer.sequence == ".."
    restarted.send()
    assert typer.sequence == ""
    restarted.letter("-")
    assert typer.text == "T"


def test_old_run_packet_after_restart_is_ignored(typed):
    typer, stream = typed
    late = {"run": "a", "seq": 99, "ok": True, "rest": False, "step_s": 0.25, "state": "left",
            "event": "left", "source": "eeg"}
    stream.send()
    new = Stream(typer, run="b")
    new.send(event="right", state="right")
    typer.feed(late)
    assert typer.sequence == "-"
    assert typer.run == "b"


def test_wrong_model_changes_nothing():
    typer = MorseTyper(expect_model="approved", expect_threshold=0.6)
    stream = Stream(typer)
    stream.send(event="left", state="left", model="other", threshold=0.6)
    assert typer.sequence == "" and typer.run is None
    assert "model" in typer.warning
    stream.send(event="left", state="left", model="approved", threshold=0.5)
    assert typer.sequence == ""
    assert "threshold" in typer.warning
    stream.send(event="left", state="left", model="approved", threshold=0.6)
    assert typer.sequence == "."


@pytest.mark.parametrize("data", [b"not json", b"[1, 2]", b"\xff\xfe", b'{"run": 3}',
                                  b'{"run":"a","seq":"x","ok":true,"rest":true,"step_s":0.25,'
                                  b'"state":"rest","source":"eeg"}'])
def test_malformed_message_is_ignored_loudly(typed, data):
    typer, _ = typed
    typer.feed_raw(data)
    assert typer.bad_messages == 1
    assert "Ignored" in typer.warning


def test_real_datagram_is_accepted(typed):
    typer, stream = typed
    typer.feed_raw(json.dumps({"run": "a", "seq": 0, "ok": True, "rest": False, "step_s": 0.25,
                               "state": "left", "event": "left", "source": "eeg"}).encode())
    assert typer.sequence == "." and typer.bad_messages == 0


@pytest.mark.parametrize("source,banner", [("sim", "SIMULATED INPUT"),
                                           ("replay", "REPLAY, NOT LIVE EEG"),
                                           ("mystery", "UNKNOWN SOURCE"), ("eeg", None)])
def test_simulated_input_is_labelled(source, banner):
    typer = MorseTyper()
    typer.feed({"run": "a", "seq": 0, "ok": True, "rest": True, "step_s": 0.25, "state": "rest",
                "source": source})
    assert typer.view().banner == banner


def test_simulated_rest_finishes_a_letter():
    typer, keys = MorseTyper(), SimulatedKeys()
    typer.feed(keys.key("."))
    assert keys.key("x") is None
    for _ in range(12):
        typer.feed(keys.tick())
    assert typer.text == "E"
    assert typer.view().banner == "SIMULATED INPUT"


def test_common_words_rank_first():
    words = WordList(["help", "hello", "helmet"])
    assert words.complete("hel") == "HELP"
    assert load_words().complete("th") == "THE"


def test_no_match_suggests_nothing(typed):
    typer, stream = typed
    assert WordList(["help"]).complete("zzz") is None
    assert WordList(["help"]).complete("") is None
    assert WordList(["help"]).complete("help") is None
    stream.letter("--..")
    assert typer.view().suggestion is None


def test_accepting_completes_the_word_with_one_space(typed):
    typer, stream = typed
    stream.letter("....")
    assert typer.view().suggestion == "HELLO"
    stream.letter(ACCEPT)
    assert typer.text == "HELLO "
    stream.rest(10.0)
    assert typer.text == "HELLO "


def test_accept_without_suggestion_is_safe(typed):
    typer, stream = typed
    stream.letter(ACCEPT)
    assert typer.text == ""
    stream.letter("--..")
    stream.letter(ACCEPT)
    assert typer.text == "Z"


def test_word_list_ships_with_package(tmp_path):
    root = Path(__file__).resolve().parents[1]
    assert len(load_words().words) >= 200
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv isn't on the path")
    build = subprocess.run([uv, "build", "--wheel", "--out-dir", str(tmp_path)], cwd=root,
                           capture_output=True, text=True, timeout=120)
    if build.returncode != 0:
        if "network" in build.stderr.lower() or "dns" in build.stderr.lower():
            pytest.skip("the build backend isn't available offline")
        pytest.fail(build.stderr)
    wheel = next(tmp_path.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        assert "eegmove/wordlist.txt" in archive.namelist()


def test_socket_drain_reads_what_is_waiting(typed):
    import socket

    typer, _ = typed
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.setblocking(False)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    assert drain_socket(receiver, typer) == 0
    sender.sendto(b"broken", receiver.getsockname())
    for _ in range(100):
        if drain_socket(receiver, typer):
            break
    assert typer.bad_messages == 1

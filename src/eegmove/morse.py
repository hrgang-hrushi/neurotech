"""Turn decoder messages into typed text. No sockets or screens, so it can all be tested.

Left is a dot and right is a dash. Time here is counted in accepted messages, never by the
clock on the wall, so a stalled stream can't look like a pause and end a letter.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from .words import WordList

EVENT_SYMBOLS = {"left": ".", "right": "-"}
MORSE = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E", "..-.": "F", "--.": "G",
    "....": "H", "..": "I", ".---": "J", "-.-": "K", ".-..": "L", "--": "M", "-.": "N",
    "---": "O", ".--.": "P", "--.-": "Q", ".-.": "R", "...": "S", "-": "T", "..-": "U",
    "...-": "V", ".--": "W", "-..-": "X", "-.--": "Y", "--..": "Z",
}
DELETE, ACCEPT = "----", "..--"  # neither is a letter
MAX_SEQUENCE = 4
MAX_STEP_S = 1.0  # a message claiming more would end a letter in one go
SOURCE_BANNERS = {"eeg": None, "replay": "REPLAY, NOT LIVE EEG", "sim": "SIMULATED INPUT"}
REQUIRED = {"run": str, "seq": int, "ok": bool, "rest": bool, "step_s": (int, float),
            "state": str, "source": str}


@dataclass(frozen=True)
class TypingView:
    text: str
    sequence: str
    suggestion: str | None
    gap_fraction: float
    banner: str | None
    warning: str | None
    uncertain: bool


class MorseTyper:
    def __init__(self, words: WordList | None = None, letter_gap_s: float = 3.0,
                 word_gap_s: float = 7.0, expect_model: str | None = None,
                 expect_threshold: float | None = None):
        self.words = words or WordList([])
        self.letter_gap_s, self.word_gap_s = letter_gap_s, word_gap_s
        self.expect_model, self.expect_threshold = expect_model, expect_threshold
        self.text, self.sequence = "", ""
        self.clock = 0.0
        self.run: str | None = None
        self.retired: set[str] = set()
        self.last_seq = -1
        self.bad_messages = 0
        self.banner: str | None = None
        self.decoder_warning: str | None = None  # replaced by each message
        self.notice: str | None = None  # stays up until the next symbol
        self.uncertain = False

    @property
    def warning(self) -> str | None:
        return self.decoder_warning or self.notice

    def feed_raw(self, data: bytes) -> None:
        """Feed one datagram. A broken message warns and never stops the app."""
        try:
            message = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            self._reject("Ignored a message that wasn't valid JSON.")
            return
        self.feed(message)

    def feed(self, message: dict) -> None:
        if not self._valid(message):
            self._reject("Ignored a malformed decoder message.")
            return
        if self._mismatched(message):
            return
        if not self._current(message):
            return
        self.banner = SOURCE_BANNERS.get(message["source"], "UNKNOWN SOURCE")
        self.decoder_warning = message.get("warning")
        if not message["ok"]:  # rejected window: nothing happened, so no time passed either
            self.decoder_warning = f"Signal rejected: {message.get('reason')}"
            return
        self._apply(message)

    def _valid(self, message) -> bool:
        if not isinstance(message, dict) or not all(
                isinstance(message.get(key), kind) for key, kind in REQUIRED.items()):
            return False
        step = message["step_s"]
        return (not isinstance(message["seq"], bool)
                and not isinstance(step, bool) and math.isfinite(step) and 0 < step <= MAX_STEP_S
                and isinstance(message.get("event"), (str, type(None)))
                and isinstance(message.get("warning"), (str, type(None))))

    def _reject(self, reason: str) -> None:
        self.bad_messages += 1
        self.notice = f"{reason} ({self.bad_messages} so far)"

    def _mismatched(self, message: dict) -> bool:
        if self.expect_model is not None and message.get("model") != self.expect_model:
            self.notice = "REFUSED: this decoder isn't running the approved model."
            return True
        if self.expect_threshold is not None and message.get("threshold") != self.expect_threshold:
            self.notice = "REFUSED: this decoder isn't using the approved threshold."
            return True
        return False

    def _current(self, message: dict) -> bool:
        run = message["run"]
        if run in self.retired:
            return False  # a late packet from a decoder that has since restarted
        if run != self.run:
            if self.run is not None:
                self.retired.add(self.run)
            self.run, self.last_seq, self.sequence, self.clock = run, -1, "", 0.0
        if message["seq"] <= self.last_seq:
            return False
        self.last_seq = message["seq"]
        return True

    def _apply(self, message: dict) -> None:
        event = message.get("event")
        if event in EVENT_SYMBOLS:
            self.sequence += EVENT_SYMBOLS[event]
            self.clock = 0.0
            self.notice = None
            if len(self.sequence) > MAX_SEQUENCE:
                self.sequence = ""
                self.notice = f"Sequence too long, so it was cleared ({MAX_SEQUENCE} is the limit)."
            self.uncertain = False
            return
        rest = message["rest"]
        self.clock = self.clock + message["step_s"] if rest else 0.0
        self.uncertain = not rest and message["state"] == "rest"
        if self.sequence and self.clock >= self.letter_gap_s:
            self._commit()
        if not self.sequence and self.clock >= self.word_gap_s and self.text \
                and not self.text.endswith(" "):
            self.text += " "

    def _commit(self) -> None:
        sequence, self.sequence = self.sequence, ""
        if sequence == DELETE:
            self.text = self.text.rstrip()[:-1]
        elif sequence == ACCEPT:
            self._accept()
        elif sequence in MORSE:
            self.text += MORSE[sequence]
        else:
            self.notice = f"{sequence} isn't a letter, so nothing was typed."

    def _word(self) -> str:
        return "" if self.text.endswith(" ") else self.text.rsplit(" ", 1)[-1]

    def _accept(self) -> None:
        word, suggestion = self._word(), self.words.complete(self._word())
        if suggestion is not None:
            self.text = self.text[:len(self.text) - len(word)] + suggestion + " "

    def view(self) -> TypingView:
        limit = self.letter_gap_s if self.sequence else self.word_gap_s
        return TypingView(self.text, self.sequence, self.words.complete(self._word()),
                          min(1.0, self.clock / limit), self.banner, self.warning, self.uncertain)


class SimulatedKeys:
    """Keyboard stand-in for the decoder, labelled as simulated all the way through."""

    STEP_S = 0.25

    def __init__(self):
        self.seq = -1

    def _message(self, event: str | None) -> dict:
        self.seq += 1
        return {"run": "simulated", "seq": self.seq, "ok": True, "rest": event is None,
                "step_s": self.STEP_S, "state": event or "rest", "event": event, "source": "sim",
                "reason": None}

    def key(self, symbol: str) -> dict | None:
        event = {".": "left", "-": "right"}.get(symbol)
        return self._message(event) if event else None

    def tick(self) -> dict:
        """One quiet step. Only messages move the gap clock, so letters need these to finish."""
        return self._message(None)

"""Corrected Morse words -> readable sentences.

Morse arrives as uppercase words with no punctuation unless the sender keyed
it (`?` is ..--.., `.` is .-.-.-, `!` is -.-.--). This adds what a reader
expects, conservatively and deterministically:

  - sentence boundaries at keyed punctuation and at long pauses
  - sentence case, a capital "I" (and I'm, I'll, ...), SOS kept uppercase
  - end punctuation: "?" for questions (wh-words, or an auxiliary verb
    first: "CAN YOU HELP ME" -> "Can you help me?"), "!" for emergencies
    ("HELP", "SOS"), "." otherwise. Keyed punctuation always wins.
"""
from __future__ import annotations

from dataclasses import dataclass

WH_WORDS = {"WHAT", "WHERE", "WHEN", "WHY", "WHO", "WHOM", "WHOSE", "WHICH", "HOW"}
AUXILIARIES = {"AM", "IS", "ARE", "WAS", "WERE", "DO", "DOES", "DID", "CAN", "COULD",
               "WILL", "WOULD", "SHALL", "SHOULD", "MAY", "MIGHT", "MUST", "HAVE", "HAS",
               "HAD", "ISN'T", "AREN'T", "DON'T", "DOESN'T", "DIDN'T", "CAN'T", "WON'T",
               "WOULDN'T", "COULDN'T", "SHOULDN'T", "WASN'T", "WEREN'T"}
# Words that can follow an auxiliary as its subject, which is what makes
# "IS IT COLD" a question but "WAS GOOD" not.
SUBJECTS = {"I", "YOU", "HE", "SHE", "IT", "WE", "THEY", "THIS", "THAT", "THERE", "THESE",
            "THOSE", "MY", "YOUR", "HIS", "HER", "OUR", "THEIR", "THE", "A", "AN", "ANYONE",
            "SOMEONE", "EVERYONE", "ANYBODY", "SOMEBODY", "WE'RE", "SOMETHING", "ANYTHING"}
URGENT_START = {"HELP", "SOS", "EMERGENCY", "FIRE", "STOP", "DANGER"}
KEYED_END = {"?": "question", "!": "exclamation", ".": "statement"}
END_MARK = {"question": "?", "exclamation": "!", "statement": "."}
ALWAYS_UPPER = {"SOS", "OK", "TV", "ID"}
EXCLAMATIVE_SECOND = {"A", "AN"}  # "WHAT A DAY" is an exclamation, not a question


@dataclass(frozen=True)
class Sentence:
    words: tuple[str, ...]
    kind: str  # "question", "statement", "exclamation"
    text: str


@dataclass(frozen=True)
class Polished:
    sentences: tuple[Sentence, ...]

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)

    @property
    def kinds(self) -> list[str]:
        return [s.kind for s in self.sentences]


def classify(words: list[str]) -> str:
    """Sentence type from word order alone (uppercase words; keyed commas are ignored)."""
    words = [w.rstrip(",") for w in words]
    if not words:
        return "statement"
    first = words[0]
    if first in URGENT_START:
        return "exclamation"
    if first in WH_WORDS:
        if len(words) > 1 and words[1] in EXCLAMATIVE_SECOND:
            return "exclamation"
        return "question"
    if first in AUXILIARIES and len(words) > 1 and words[1] in SUBJECTS:
        return "question"
    return "statement"


def _case(word: str, first: bool) -> str:
    if word in ALWAYS_UPPER:
        return word
    if word == "I" or word.startswith("I'"):
        return "I" + word[1:].lower()
    low = word.lower()
    return low[:1].upper() + low[1:] if first else low


def _strip_keyed(word: str) -> tuple[str, str | None]:
    """Split keyed end punctuation off a word: 'YOU?' -> ('YOU', '?'), 'YOU?!' -> ('YOU', '!')."""
    bare = word.rstrip("".join(KEYED_END))
    return (bare, word[-1]) if bare != word else (word, None)


def split_sentences(words: list[str], starts: list[bool] | None = None) -> list[tuple[list[str], str | None]]:
    """Sentences as (words, keyed end mark or None)."""
    starts = starts or [False] * len(words)
    out: list[tuple[list[str], str | None]] = []
    cur: list[str] = []
    for w, new in zip(words, starts):
        if new and cur:
            out.append((cur, None))
            cur = []
        bare, mark = _strip_keyed(w)
        if bare:
            cur.append(bare)
        if mark and cur:
            out.append((cur, mark))
            cur = []
    if cur:
        out.append((cur, None))
    return out


def polish(words: list[str], starts: list[bool] | None = None) -> Polished:
    sentences = []
    for ws, mark in split_sentences(words, starts):
        kind = KEYED_END[mark] if mark else classify(ws)
        body = " ".join(_case(w, i == 0) for i, w in enumerate(ws))
        sentences.append(Sentence(tuple(ws), kind, body + (mark or END_MARK[kind])))
    return Polished(tuple(sentences))

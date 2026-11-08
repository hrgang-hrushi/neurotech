"""Morse-aware word correction: decoded Morse words -> likely English words.

Errors from an EEG/EMG key are timing errors, not typos, so candidates are
scored by edits to the *Morse*, not to the letters:

  dot <-> dash                  1.0   (key held too long / too short)
  missing or extra element      1.0   (missed or spurious key-down)
  missing or extra letter gap   0.5   (pause misjudged inside a word)
  missing or extra word gap     0.5   (handled by splitting / merging words)

A word that is already English is kept. Otherwise the lowest
`cost * COST_WEIGHT - zipf_frequency` candidate within `MAX_COST` wins.
The lexicon is `wordfreq`'s English list (offline once installed); words with
apostrophes are keyed without them, so IM -> I'M and DONT -> DON'T.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from functools import lru_cache

from . import morse
from .timing import Transcript

LEXICON_SIZE = 30_000  # wordfreq's English "small" list holds this many
MAX_COST = 2.0
MAX_COST_SHORT = 1.0  # words of <= 2 letters have too many neighbours
MAX_COST_LONG = 1.5  # longer words: the search space explodes and fewer edits are plausible
LONG_WORD_LETTERS = 5
COST_WEIGHT = 2.0
GAP_COST = 0.5
ELEMENT_COST = 1.0
SPLIT_COST = GAP_COST  # a missed word gap
MERGE_COST = GAP_COST  # a spurious word gap
# Prefer the apostrophe form only when it is this much more frequent (zipf),
# e.g. CANT -> CAN'T but ITS stays ITS and WERE stays WERE.
APOSTROPHE_MARGIN = 1.2
# A decoded word that is already English gets this many zipf points of credit,
# so it is only replaced by a much more common word one cheap edit away
# (e.g. NEL -> NEED), never by a merely similar one.
TRUST_BONUS = 1.5
KEEP_AS_IS = {"SOS"}
ZIPF_MAX = 9.0  # zipf = log10(frequency per billion words), so log10 P = zipf - 9
SINGLE_LETTER_WORDS = {"A", "I"}
SEP = "|"


@dataclass(frozen=True)
class Entry:
    word: str  # display form, uppercase, may contain an apostrophe
    zipf: float


@lru_cache(maxsize=1)
def lexicon() -> dict[str, Entry]:
    """Morse key ('.-|-...') -> most likely English word with that Morse."""
    from wordfreq import top_n_list, zipf_frequency

    best: dict[str, Entry] = {}
    for w in top_n_list("en", LEXICON_SIZE):
        bare = w.replace("'", "").upper()
        if not bare.isalpha() or not bare.isascii():
            continue
        if len(bare) == 1 and bare not in SINGLE_LETTER_WORDS:
            continue
        entry = Entry(w.upper(), zipf_frequency(w, "en"))
        key = SEP.join(morse.MORSE[c] for c in bare)
        cur = best.get(key)
        if cur is None:
            best[key] = entry
            continue
        cur_has_apos, new_has_apos = "'" in cur.word, "'" in entry.word
        if cur_has_apos == new_has_apos:
            if entry.zipf > cur.zipf:
                best[key] = entry
        elif new_has_apos and entry.zipf > cur.zipf + APOSTROPHE_MARGIN:
            best[key] = entry
        elif cur_has_apos and cur.zipf <= entry.zipf + APOSTROPHE_MARGIN:
            best[key] = entry
    return best


def key_of(codes: list[str]) -> str:
    return SEP.join(codes)


def _valid_key(k: str) -> bool:
    return bool(k) and not k.startswith(SEP) and not k.endswith(SEP) and SEP * 2 not in k


def neighbours(key: str, max_cost: float) -> dict[str, float]:
    """All Morse keys within max_cost of `key` (uniform-cost search over edits)."""
    best = {key: 0.0}
    heap = [(0.0, key)]
    while heap:
        cost, k = heapq.heappop(heap)
        if cost > best.get(k, float("inf")):
            continue
        for nk, step in _edits(k):
            nc = cost + step
            if nc <= max_cost + 1e-9 and nc < best.get(nk, float("inf")) and _valid_key(nk):
                best[nk] = nc
                heapq.heappush(heap, (nc, nk))
    return best


def _edits(k: str):
    for i, ch in enumerate(k):
        if ch == ".":
            yield k[:i] + "-" + k[i + 1:], ELEMENT_COST
        elif ch == "-":
            yield k[:i] + "." + k[i + 1:], ELEMENT_COST
        yield k[:i] + k[i + 1:], GAP_COST if ch == SEP else ELEMENT_COST
    for i in range(len(k) + 1):
        for ins, c in ((".", ELEMENT_COST), ("-", ELEMENT_COST), (SEP, GAP_COST)):
            yield k[:i] + ins + k[i:], c


@dataclass(frozen=True)
class Candidate:
    words: tuple[str, ...]
    cost: float
    zipfs: tuple[float, ...]

    @property
    def score(self) -> float:
        """Edit cost plus unigram surprisal: -log10 P(word) = 9 - zipf, summed over words."""
        return self.cost * COST_WEIGHT + sum(ZIPF_MAX - z for z in self.zipfs)

    def __add__(self, other: "Candidate") -> "Candidate":
        return Candidate(self.words + other.words, self.cost + other.cost, self.zipfs + other.zipfs)


@lru_cache(maxsize=8192)
def best_word(key: str, max_cost: float) -> Candidate | None:
    lex = lexicon()
    found = [Candidate((lex[k].word,), c, (lex[k].zipf,))
             for k, c in neighbours(key, max_cost).items() if k in lex]
    return min(found, key=lambda c: (c.score, c.words)) if found else None


def best_split(codes: list[str], max_cost: float,
               split_costs: list[float] | None = None) -> Candidate | None:
    """The word was really two words sent without a word gap ("INEED" -> "I NEED").

    split_costs[i-1] is the cost of a word gap before letter i (cheap when the
    measured pause there was nearly a word gap); uniform SPLIT_COST without timing.
    """
    out = None
    for i in range(1, len(codes)):
        if not (correctable(codes[:i]) and correctable(codes[i:])):
            continue
        split = split_costs[i - 1] if split_costs else SPLIT_COST
        budget = max_cost - split
        left = best_word(key_of(codes[:i]), _limit_for(codes[:i], budget))
        right = best_word(key_of(codes[i:]), _limit_for(codes[i:], budget))
        if not (left and right) or left.cost + right.cost > budget + 1e-9:
            continue
        cand = Candidate((), split, ()) + left + right
        if out is None or cand.score < out.score:
            out = cand
    return out


def _limit_for(codes: list[str], budget: float) -> float:
    return max(0.0, min(budget, _limit(len(codes))))


@dataclass(frozen=True)
class GapTiming:
    """Measured pauses, so word-gap errors cost less where the pause was borderline."""
    letter_gaps: list[list[float]]  # per word: pause before each letter after the first
    word_gaps: list[float | None]  # pause before each word (None = first word, inf = recording paused)
    letter_thr: float  # pause above this = letter gap
    word_thr: float  # pause above this = word gap


MIN_GAP_FRACTION = 0.1


def _soft(distance: float, span: float) -> float:
    """GAP_COST scaled by how far a pause was from the threshold it would have to cross."""
    frac = float(min(1.0, max(0.0, distance / span))) if span > 0 else 1.0
    return GAP_COST * (MIN_GAP_FRACTION + (1 - MIN_GAP_FRACTION) * frac)


def split_costs(timing: GapTiming | None, w: int) -> list[float] | None:
    if timing is None:
        return None
    span = timing.word_thr - timing.letter_thr
    return [_soft(timing.word_thr - g, span) for g in timing.letter_gaps[w]]


def merge_cost(timing: GapTiming | None, w: int) -> float | None:
    """Cost of joining word w with word w+1; None when a recording pause separates them."""
    if timing is None:
        return MERGE_COST
    g = timing.word_gaps[w + 1]
    if g is None or g >= SENTENCE_GAP_FACTOR * timing.word_thr:  # incl. recording pauses (inf)
        return None
    return _soft(g - timing.word_thr, timing.word_thr - timing.letter_thr)


@dataclass(frozen=True)
class WordFix:
    original: str
    corrected: str
    cost: float


@dataclass(frozen=True)
class Corrected:
    words: list[str]  # corrected words, uppercase
    fixes: list[WordFix]
    raw_words: list[str]
    sentence_starts: list[bool] = field(default_factory=list)  # True: a long pause came before

    @property
    def upper_text(self) -> str:
        return " ".join(self.words)


def _decoded(codes: list[str]) -> str:
    return "".join(morse.decode_code(c, True)[0] for c in codes)


def _entry(text: str) -> Entry | None:
    if not text.isalpha() or not text.isascii():
        return None
    entry = lexicon().get(key_of([morse.MORSE[c] for c in text]))
    return entry if entry and entry.word.replace("'", "") == text else None


def is_word(codes: list[str]) -> bool:
    """All codes are valid letters (none guessed by Morse repair) and spell an English word."""
    if not all(len(morse.CODE_TO_CHAR.get(c, "")) == 1 for c in codes):
        return _decoded(codes) in KEEP_AS_IS
    return _decoded(codes) in KEEP_AS_IS or _entry(_decoded(codes)) is not None


def _limit(n_letters: int) -> float:
    if n_letters <= 2:
        return MAX_COST_SHORT
    return MAX_COST if n_letters <= LONG_WORD_LETTERS else MAX_COST_LONG


def _as_sent(codes: list[str]) -> Candidate | None:
    """The decoded word itself as a candidate, if it is English (cost 0, trust bonus)."""
    if not is_word(codes):
        return None
    raw = _decoded(codes)
    entry = _entry(raw)
    if entry is None:  # KEEP_AS_IS
        return Candidate((raw,), 0.0, (ZIPF_MAX,))
    return Candidate((entry.word,), 0.0, (entry.zipf + TRUST_BONUS,))


# Correction search grows steeply with word length: whole words up to this many
# letters are corrected; longer runs (a missed word gap) may still be split into
# two words of at most this length each, up to MAX_SPLIT_LETTERS in total.
MAX_CORRECT_LETTERS = 8
MAX_SPLIT_LETTERS = 12


def _letter_or_garbled(code: str) -> bool:
    """A letter code, or no valid code at all (a garbled letter). Digits, marks and SOS are neither."""
    ch = morse.CODE_TO_CHAR.get(code)
    return ch is None or (len(ch) == 1 and ch.isalpha())


def correctable(codes: list[str], max_letters: int = MAX_CORRECT_LETTERS) -> bool:
    """Words are corrected only when short enough to search and made of letters."""
    return 0 < len(codes) <= max_letters and all(_letter_or_garbled(c) for c in codes)


def word_options(codes: list[str], splits: list[float] | None = None) -> Candidate | None:
    """Best reading of one decoded Morse word: as sent, corrected, or split in two.

    None means "leave as decoded" (not an all-letter word, or too long to search).
    """
    if not correctable(codes, MAX_SPLIT_LETTERS):
        return None
    limit = _limit(len(codes))
    whole = correctable(codes)
    options = [c for c in (_as_sent(codes) if whole else None,
                           best_word(key_of(codes), limit) if whole else None,
                           best_split(codes, limit, splits) if len(codes) >= 2 else None) if c]
    return min(options, key=lambda c: (c.score, len(c.words))) if options else None


def _try_merge(a: list[str], b: list[str], cost: float | None,
               splits_a: list[float] | None, splits_b: list[float] | None) -> Candidate | None:
    """One word with a spurious word gap ("HE LP" -> "HELP"), if that reads better."""
    if cost is None or not correctable(a + b):
        return None
    merged = best_word(key_of(a + b), MAX_COST_SHORT)
    if merged is None:
        return None
    merged = Candidate((), cost, ()) + merged
    left, right = word_options(a, splits_a), word_options(b, splits_b)
    if left and right and (left + right).score <= merged.score:
        return None
    return merged


# A pause this many times the word-gap threshold (or a recording pause) ends a sentence.
SENTENCE_GAP_FACTOR = 2.0


def _long_pause_before(timing: GapTiming | None, w: int) -> bool:
    if timing is None or w == 0:
        return False
    g = timing.word_gaps[w]
    return g is not None and g >= SENTENCE_GAP_FACTOR * timing.word_thr


KEYED_MARKS = {"?", "!", ".", ","}


def _split_mark(codes: list[str]) -> tuple[list[str], str]:
    """Keyed punctuation at the end of a word ('YOU?') is kept out of correction."""
    if len(codes) > 1 and morse.CODE_TO_CHAR.get(codes[-1]) in KEYED_MARKS:
        return codes[:-1], morse.CODE_TO_CHAR[codes[-1]]
    return codes, ""


def correct_words(words: list[list[str]], timing: GapTiming | None = None) -> Corrected:
    raw = [_decoded(w) for w in words]
    parts = [_split_mark(w) for w in words]
    out: list[str] = []
    starts: list[bool] = []
    fixes: list[WordFix] = []
    i = 0
    while i < len(words):
        starts.append(_long_pause_before(timing, i))
        (codes, mark), splits = parts[i], split_costs(timing, i)
        if mark:
            splits = splits[:len(codes) - 1] if splits else None
        elif i + 1 < len(words):
            nxt_codes, nxt_mark = parts[i + 1]
            merged = _try_merge(codes, nxt_codes, merge_cost(timing, i), splits,
                                split_costs(timing, i + 1))
            if merged:
                out.append(merged.words[0] + nxt_mark)
                fixes.append(WordFix(f"{raw[i]} {raw[i + 1]}", out[-1], merged.cost))
                i += 2
                continue
        pick = word_options(codes, splits)
        fixed = list(pick.words) if pick else [_decoded(codes)]
        fixed[-1] += mark
        out.extend(fixed)
        starts.extend([False] * (len(fixed) - 1))
        if " ".join(fixed).replace("'", "") != raw[i]:
            fixes.append(WordFix(raw[i], " ".join(fixed), pick.cost if pick else 0.0))
        i += 1
    return Corrected(out, fixes, raw, starts)


def gap_timing(tr: Transcript, breaks: list[float] | None = None) -> GapTiming:
    """Pauses per word/letter from a transcript's elements (same grouping as `transcribe`)."""
    letter_gaps: list[list[float]] = []
    word_gaps: list[float | None] = []
    for i, e in enumerate(tr.elements):
        if e.boundary in ("start", "word"):
            paused = i > 0 and breaks and any(tr.elements[i - 1].t_off <= b <= e.t_on for b in breaks)
            word_gaps.append(float("inf") if paused else e.gap_before)
            letter_gaps.append([])
        elif e.boundary == "letter":
            letter_gaps[-1].append(float(e.gap_before))
    return GapTiming(letter_gaps, word_gaps, tr.letter_gap_s, tr.word_gap_s)


def correct_transcript(tr: Transcript, breaks: list[float] | None = None) -> Corrected:
    if not tr.words:
        return Corrected([], [], [])
    return correct_words(tr.words, gap_timing(tr, breaks))

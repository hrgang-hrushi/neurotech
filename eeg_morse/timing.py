"""Timing stage: key-down intervals -> dots/dashes -> letters/words -> English."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from . import morse
from .config import TimingConfig
from .detect import Segment


@dataclass
class Element:
    t_on: float
    t_off: float
    symbol: str  # "." or "-"
    gap_before: float | None  # seconds of key-up before this element
    boundary: str  # "start", "intra", "letter" or "word"

    @property
    def duration(self) -> float:
        return self.t_off - self.t_on


@dataclass
class Letter:
    code: str
    char: str
    status: str  # ok / split / nearest / unknown
    t_start: float
    t_end: float


@dataclass
class Transcript:
    elements: list[Element]
    letters: list[Letter]
    words: list[list[str]]
    morse: str
    text: str
    unit_s: float
    bias_s: float  # detector lengthens key-downs (and shortens gaps) by this much
    dash_threshold_s: float
    letter_gap_s: float
    word_gap_s: float
    unit_source: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        for e, src in zip(d["elements"], self.elements):
            e["duration"] = round(src.duration, 4)
        return d


def _two_means_log(d: np.ndarray) -> tuple[float, float] | None:
    """Split durations into short/long groups (1-D Otsu on log duration)."""
    if d.size < 2:
        return None
    x = np.sort(np.log(d))
    best, k_best = -1.0, None
    for k in range(1, x.size):
        a, b = x[:k], x[k:]
        score = k * (x.size - k) * (a.mean() - b.mean()) ** 2
        if score > best:
            best, k_best = score, k
    a, b = x[:k_best], x[k_best:]
    return float(np.exp(a.mean())), float(np.exp(b.mean()))


def estimate_unit(durations: list[float], cfg: TimingConfig) -> tuple[float, float, str]:
    """Return (unit, bias, source).

    The detector lengthens every key-down by roughly the same amount `bias`
    (and shortens every gap by it), so measured dot = u + b and dash = 3u + b.
    With both clusters present, solve for u and b; otherwise use the config.
    """
    if cfg.unit_s:
        return float(cfg.unit_s), float(cfg.bias_s), "fixed"
    d = np.asarray([x for x in durations if x > 0], dtype=float)
    split = _two_means_log(d)
    if split is not None:
        short, long_ = split
        if long_ / short >= 1.6:
            u = (long_ - short) / 2.0
            b = short - u
            if u > 0 and abs(b) <= 0.5 * u:
                return u, b, "estimated"
            return (short + long_ / 3.0) / 2.0, 0.0, "estimated"
    return float(cfg.default_unit_s), float(cfg.bias_s), "default (could not separate dots from dashes)"


def thresholds_for(unit: float, bias: float, cfg: TimingConfig) -> tuple[float, float, float]:
    """(dash threshold on key-down length, letter-gap and word-gap thresholds on key-up length)."""
    return (cfg.dash_ratio * unit + bias,
            cfg.letter_gap_ratio * unit - bias,
            cfg.word_gap_ratio * unit - bias)


def transcribe(segments: list[Segment], cfg: TimingConfig, correct: bool = True,
               breaks: list[float] | None = None) -> Transcript:
    """breaks: times where the recording was paused; a pause is always a word break."""
    notes: list[str] = []
    unit, bias, source = estimate_unit([s.duration for s in segments], cfg)
    # Two-pass: a real dot lasts ~1 unit, so much shorter key-downs are noise.
    # Drop them, then re-estimate the unit without their pull.
    kept = [s for s in segments if s.duration >= cfg.min_dot_ratio * unit]
    if len(kept) < len(segments):
        notes.append(f"Ignored {len(segments) - len(kept)} key-down blip(s) shorter than "
                     f"{cfg.min_dot_ratio * unit:.2f}s.")
        segments = kept
        unit, bias, source = estimate_unit([s.duration for s in segments], cfg)
    if source.startswith("default") and segments:
        notes.append(
            "All key-down durations look alike, so the unit fell back to "
            f"{unit:g}s; pass --unit or calibrate for reliable dot/dash calls."
        )
    dash_thr, letter_gap, word_gap = thresholds_for(unit, bias, cfg)

    elements: list[Element] = []
    for i, s in enumerate(segments):
        sym = "-" if s.duration > dash_thr else "."
        if i == 0:
            gap, kind = None, "start"
        else:
            gap = s.t_on - segments[i - 1].t_off
            kind = "intra" if gap <= letter_gap else ("letter" if gap <= word_gap else "word")
            if breaks and any(segments[i - 1].t_off <= br <= s.t_on for br in breaks):
                kind = "word"
        elements.append(Element(s.t_on, s.t_off, sym, gap, kind))

    words: list[list[str]] = []
    letters: list[Letter] = []
    code, t0 = "", 0.0
    for i, e in enumerate(elements):
        if e.boundary in ("letter", "word") and code:
            ch, st = morse.decode_code(code, correct)
            letters.append(Letter(code, ch, st, t0, elements[i - 1].t_off))
            words[-1].append(code)
            code = ""
        if e.boundary in ("start", "word"):
            words.append([])
        if not code:
            t0 = e.t_on
        code += e.symbol
    if code:
        ch, st = morse.decode_code(code, correct)
        letters.append(Letter(code, ch, st, t0, elements[-1].t_off))
        words[-1].append(code)

    bad = [l for l in letters if l.status != "ok"]
    if bad:
        notes.append(
            f"{len(bad)} letter code(s) were not valid Morse and were "
            + ("repaired: " if correct else "marked '?': ")
            + ", ".join(f"{l.code}->{l.char}" for l in bad)
        )
    return Transcript(
        elements=elements,
        letters=letters,
        words=words,
        morse=morse.to_string(words),
        text=morse.decode(words, correct),
        unit_s=unit,
        bias_s=bias,
        dash_threshold_s=dash_thr,
        letter_gap_s=letter_gap,
        word_gap_s=word_gap,
        unit_source=source,
        notes=notes,
    )

"""Offline pipeline: Recording -> activation -> key-down segments -> Morse -> English.

`decode` runs the whole chain. `calibrate` searches a small grid of
smoothing/hysteresis/timing settings against a known message and returns a
config tuned to one person + cap + movement, ready for `decode` or `live`.
"""
from __future__ import annotations

import copy
import difflib
import itertools
from dataclasses import asdict, dataclass

import numpy as np

from . import morse
from .config import PipelineConfig
from .detect import Segment, Thresholds, detect
from .io import Recording
from .signal import Activation, activation, channel_separability
from .timing import Transcript, transcribe


@dataclass
class Result:
    recording: Recording
    config: PipelineConfig
    activation: Activation
    segments: list[Segment]
    thresholds: Thresholds
    transcript: Transcript
    warnings: list[str]

    @property
    def text(self) -> str:
        return self.transcript.text

    @property
    def morse(self) -> str:
        return self.transcript.morse

    def report(self) -> dict:
        r = self.recording
        active = sum(s.duration for s in self.segments) / max(r.duration, 1e-9)
        return {
            "text": self.transcript.text,
            "morse": self.transcript.morse,
            "source": {
                "file": r.source,
                "sfreq": r.sfreq,
                "duration_s": round(r.duration, 3),
                "channels_used": self.activation.channels,
            },
            "quality": {
                "separability": round(self.thresholds.separability, 3),
                "n_key_downs": len(self.segments),
                "fraction_time_active": round(active, 3),
                "warnings": self.warnings + self.transcript.notes,
            },
            "thresholds": {k: round(v, 5) for k, v in asdict(self.thresholds).items()},
            "timing": {
                "unit_s": round(self.transcript.unit_s, 4),
                "unit_source": self.transcript.unit_source,
                "bias_s": round(self.transcript.bias_s, 4),
                "dash_threshold_s": round(self.transcript.dash_threshold_s, 4),
                "letter_gap_s": round(self.transcript.letter_gap_s, 4),
                "word_gap_s": round(self.transcript.word_gap_s, 4),
            },
            "letters": [asdict(l) for l in self.transcript.letters],
            "elements": self.transcript.to_dict()["elements"],
            "config": self.config.to_dict(),
        }


# Otsu separability of the activation trace. Gaussian noise alone scores ~0.64;
# simulated movement scored 0.78 (motor ERD) to 0.93 (jaw clench, eye closure).
SEPARABILITY_MIN = 0.72


def _quality_warnings(th: Thresholds, segs: list[Segment], duration: float) -> list[str]:
    w = []
    if th.separability < SEPARABILITY_MIN:
        w.append(
            f"Weak on/off contrast (separability {th.separability:.2f}; pure noise scores "
            f"~0.65, clear movement > {SEPARABILITY_MIN}). The text is probably noise: check "
            "impedances, the preset/channels, or that the movement was actually performed."
        )
    if not segs:
        w.append("No key-down activity detected.")
    elif sum(s.duration for s in segs) / max(duration, 1e-9) > 0.7:
        w.append("Key-down for >70% of the recording; the activation polarity or band may be wrong.")
    return w


def decode(rec: Recording, cfg: PipelineConfig, correct: bool = True,
           fixed_thresholds: bool = False, act: Activation | None = None) -> Result:
    """Run the full chain on one recording.

    Thresholds are re-fit per recording (Otsu) unless fixed_thresholds=True,
    because absolute EEG power shifts between sessions with gain/impedance.
    """
    dcfg = copy.deepcopy(cfg.detect)
    if not fixed_thresholds:
        dcfg.lo = dcfg.hi = None
    act = act if act is not None else activation(rec, cfg.feature)
    segs, th = detect(act.t, act.values, act.rate, dcfg)
    tr = transcribe(segs, cfg.timing, correct)
    return Result(rec, cfg, act, segs, th, tr, _quality_warnings(th, segs, rec.duration))


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


@dataclass
class Calibration:
    config: PipelineConfig
    result: Result
    expected_text: str
    expected_morse: str
    text_similarity: float
    morse_similarity: float
    tried: int

    def summary(self) -> str:
        f, d, t = self.config.feature, self.config.detect, self.config.timing
        return "\n".join([
            f"expected : {self.expected_text}",
            f"decoded  : {self.result.text}",
            f"morse exp: {self.expected_morse}",
            f"morse got: {self.result.morse}",
            f"text match {self.text_similarity:.0%}, morse match {self.morse_similarity:.0%} "
            f"(best of {self.tried} settings)",
            f"channels : {', '.join(f.channels)}",
            f"chosen   : smooth {f.smooth_s:g}s, hysteresis {d.hysteresis:g}, unit {t.default_unit_s:.3f}s, "
            f"dash>{t.dash_ratio:g}u, letter gap>{t.letter_gap_ratio:g}u, word gap>{t.word_gap_ratio:g}u",
        ])


def quiet_level(act: Activation, segs: list[Segment], margin_s: float = 1.0) -> float:
    """Mean activation in stretches at least margin_s away from any key-down.

    This matches what live mode measures during its opening rest period, so the
    two can be compared to correct for gain/impedance changes between sessions.
    """
    mask = (act.t >= act.t[0] + 1.0) & (act.t <= act.t[-1] - 1.0)
    for s in segs:
        mask &= (act.t < s.t_on - margin_s) | (act.t > s.t_off + margin_s)
    vals = act.values[mask] if mask.any() else act.values
    return float(np.mean(vals))


def calibrate(rec: Recording, cfg: PipelineConfig, expected_text: str,
              smooth_factors=(0.5, 0.75, 1.0, 1.5),
              hysteresis=(0.1, 0.25, 0.4),
              dash_ratios=(2.0,),
              letter_gap_ratios=(2.0,),
              word_gap_ratios=(5.0,), min_gain: float = 0.1) -> Calibration:
    """Tune settings so `rec` decodes to `expected_text` as closely as possible.

    By default only channels, smoothing and hysteresis are searched. Timing
    ratios stay at the Morse midpoints (bias-corrected in `timing`): tuning them
    on one short phrase fits its noise and hurt other recordings in testing.
    """
    expected_text = " ".join(expected_text.upper().split())
    exp_morse = morse.to_string(morse.encode(expected_text))
    defaults = (1.0, cfg.detect.hysteresis, cfg.timing.dash_ratio,
                cfg.timing.letter_gap_ratio, cfg.timing.word_gap_ratio)
    # Candidate channel sets: the preset's channels, the 3 best, the single best.
    ranked = [name for name, _ in channel_separability(rec, cfg.feature)]
    subsets: list[list[str]] = []
    for s in (ranked, ranked[:3], ranked[:1]):
        if s and s not in subsets:
            subsets.append(s)
    entries: dict[tuple, tuple] = {}
    tried = 0
    for (rank, chans), (si, sf) in itertools.product(enumerate(subsets), enumerate(smooth_factors)):
        c1 = copy.deepcopy(cfg)
        c1.feature.channels = list(chans)
        c1.feature.smooth_s = round(cfg.feature.smooth_s * sf, 4)
        act = activation(rec, c1.feature)
        for hi_, h in enumerate(hysteresis):
            c1.detect.hysteresis = h
            c1.detect.lo = c1.detect.hi = None
            segs, th = detect(act.t, act.values, act.rate, c1.detect)
            for ti, (dr, lg, wg) in enumerate(itertools.product(dash_ratios, letter_gap_ratios,
                                                                word_gap_ratios)):
                if wg <= lg:
                    continue
                tried += 1
                c1.timing.dash_ratio, c1.timing.letter_gap_ratio, c1.timing.word_gap_ratio = dr, lg, wg
                tr = transcribe(segs, c1.timing, correct=False)
                ts, ms = _similarity(tr.text, expected_text), _similarity(tr.morse, exp_morse)
                dist = float(np.sum(np.abs(np.log(np.array((sf, h, dr, lg, wg)) / np.array(defaults)))))
                entries[(rank, si, hi_, ti)] = (copy.deepcopy(c1), act, segs, th, tr, ts, ms, dist)

    def robust(k: tuple) -> float:
        """Mean text match over this setting and its smoothing/hysteresis neighbours.

        One phrase is little data; a setting that only works at a single grid
        point is luck, a setting whose neighbours also work is a real optimum.
        """
        r, si, hi_, ti = k
        near = [entries[n][5] for n in ((r, si + a, hi_ + b, ti) for a in (-1, 0, 1) for b in (-1, 0, 1)
                                        if abs(a) + abs(b) <= 1) if n in entries]
        return float(np.mean(near))

    scored = {k: (round(robust(k), 6), round(e[5], 6), round(e[6], 6), -(e[7] + 0.5 * k[0]))
              for k, e in entries.items()}
    best_k = max(scored, key=scored.get)
    base_k = next((k for k, e in entries.items() if k[0] == 0 and e[7] == 0), None)
    # Only leave the preset for a clear, stable improvement.
    if base_k is not None and scored[best_k][0] - scored[base_k][0] < min_gain:
        best_k = base_k
    best = entries[best_k][:7]
    c_best, act, segs, th, tr, ts, ms = best
    # Save the unit as the starting/fallback value (recordings with both dots and
    # dashes still estimate their own), plus absolute thresholds for live mode.
    c_best.timing.unit_s = None
    c_best.timing.default_unit_s = round(tr.unit_s, 4)
    c_best.timing.bias_s = round(tr.bias_s, 4)
    c_best.detect.lo, c_best.detect.hi = float(th.lo), float(th.hi)
    c_best.detect.rest_level = quiet_level(act, segs)
    result = decode(rec, c_best, correct=True, act=act)
    return Calibration(c_best, result, expected_text, exp_morse, ts, ms, tried)

"""Recording file -> decoded, corrected, punctuated text, as one JSON-ready dict.

Used by the upload server (`server.py`) and testable without HTTP. The chain:
load -> artifact-aware decode (eye EMG removed, pops patched) -> Morse ->
Morse-aware word correction -> sentence casing and punctuation.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import io as eio
from .clean_decode import CleanResult, decode_clean
from .config import PipelineConfig, preset
from .grammar import Polished, polish
from .language import Corrected, correct_transcript
from .pipeline import SEPARABILITY_MIN, segment_breaks

log = logging.getLogger(__name__)

MODELS_DIR_ENV = "EEG_MORSE_MODELS"
DEFAULT_MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
DEFAULT_MODEL = "clench"
# "clench" means the team's trained clench model when present, else the preset.
TRAINED_CLENCH = "team4_clench"
MAX_TRACE_POINTS = 4000
MAX_EXPECTED_CHARS = 500
UNRELIABLE_WARNING = (
    "No clear Morse signal: movement and rest are not clearly separated (separability {sep:.2f}; "
    "noise is ~0.65, clean clenches > 0.72). No sentence was produced. Morse needs distinct "
    "short and long clenches with relaxed pauses between them.")


def models_dir() -> Path:
    return Path(os.environ.get(MODELS_DIR_ENV, DEFAULT_MODELS_DIR))


def available_models() -> list[str]:
    d = models_dir()
    trained = sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []
    return [DEFAULT_MODEL] + [m for m in trained if m != DEFAULT_MODEL]


def load_model(name: str | None) -> tuple[str, PipelineConfig]:
    name = (name or DEFAULT_MODEL).strip()
    if name not in available_models():
        raise ValueError(f"Unknown model {name!r}. Choose one of: {', '.join(available_models())}.")
    if name == DEFAULT_MODEL:
        trained = models_dir() / f"{TRAINED_CLENCH}.json"
        if trained.is_file():
            return TRAINED_CLENCH, PipelineConfig.load(trained)
        return DEFAULT_MODEL, preset("clench")
    return name, PipelineConfig.load(models_dir() / f"{name}.json")


def _r(x: float, nd: int = 3) -> float:
    return round(float(x), nd)


def _trace(cr: CleanResult) -> dict:
    act, th = cr.result.activation, cr.result.thresholds
    step = max(1, int(np.ceil(act.values.size / MAX_TRACE_POINTS)))
    return {"t": [_r(v) for v in act.t[::step]],
            "activation": [_r(v, 4) for v in act.values[::step]],
            "lo": _r(th.lo, 4), "hi": _r(th.hi, 4)}


def _artifacts(cr: CleanResult) -> list[dict]:
    events = [*cr.eye_events, *cr.pops]
    return [{"t_on": _r(e.t_on), "t_off": _r(e.t_off), "kind": e.kind,
             "channel": e.channel, "action": "removed"} for e in sorted(events, key=lambda e: e.t_on)]


def normalize(text: str) -> str:
    """Uppercase letters/digits/spaces only, for scoring against an expected phrase."""
    kept = "".join(c for c in text.upper() if c.isalnum() or c.isspace())
    return " ".join(kept.split())


def char_error_rate(got: str, want: str) -> float:
    prev = list(range(len(want) + 1))
    for i, a in enumerate(got, 1):
        cur = [i]
        for j, b in enumerate(want, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = cur
    return prev[-1] / max(len(want), 1)


def _score(final_upper: str, expected: str | None) -> dict | None:
    if not expected or not expected.strip():
        return None
    want, got = normalize(expected[:MAX_EXPECTED_CHARS]), normalize(final_upper)
    return {"expected": want, "cer": _r(char_error_rate(got, want), 4), "exact": got == want}


@dataclass(frozen=True)
class DecodeRequest:
    path: Path
    display_name: str
    model: str | None = None
    expected: str | None = None
    sfreq: float | None = None
    notes: tuple[str, ...] = ()  # session notes from the team (what was said), shown as-is


class NoUsableEEG(ValueError):
    """The file loaded but holds no usable EEG (e.g. the cap was not connected)."""


MIN_SFREQ = 100.0  # the clench band reaches 95 Hz; below this there is nothing to measure
MIN_USABLE_CHANNELS = 3
# A channel whose spread exceeds this (in the file's unit, usually uV) is saturated or
# disconnected; real scalp EEG plus jaw EMG stays far below it.
MAX_PLAUSIBLE_UV = 5000.0


def validated(rec: eio.Recording) -> tuple[eio.Recording, list[str]]:
    """Reject unusable recordings; drop channels holding NaN/Inf (one bad sample would
    otherwise spread through the filters into the whole channel)."""
    if not np.isfinite(rec.sfreq) or rec.sfreq < MIN_SFREQ:
        raise ValueError(f"sampling rate {rec.sfreq:g} Hz is too low (need at least {MIN_SFREQ:g} Hz).")
    eeg = [i for i, t in enumerate(rec.ch_types) if t == "eeg"]
    usable = [i for i in eeg if np.isfinite(rec.data[i]).all()
              and 0 < float(np.std(rec.data[i])) < MAX_PLAUSIBLE_UV]
    if len(usable) < MIN_USABLE_CHANNELS:
        raise NoUsableEEG(
            f"no usable EEG: only {len(usable)} of {len(eeg)} channels carry signal (the rest are flat "
            "or saturated). The cap was probably not connected during this recording.")
    finite = np.isfinite(rec.data).all(axis=1)
    if finite.all():
        return rec, []
    if not finite.any():
        raise ValueError("every channel contains NaN/Inf samples.")
    bad = [c for c, ok in zip(rec.ch_names, finite) if not ok]
    data = np.where(finite[:, None], rec.data, 0.0)
    clean = eio.Recording(data, rec.sfreq, rec.ch_names, rec.ch_types, rec.source, rec.events,
                          rec.annotations, rec.segments, dict(rec.impedances),
                          sorted(set(rec.bad_channels) | set(bad), key=rec.ch_names.index),
                          list(rec.noisy_channels))
    return clean, [f"Ignored channels with NaN/Inf samples: {', '.join(bad)}"]


def decode_file(req: DecodeRequest) -> dict:
    """Decode one staged recording into the API's `DecodeResult` shape."""
    model_name, cfg = load_model(req.model)
    raw_rec = eio.load(req.path, sfreq=req.sfreq)
    try:
        rec, input_warnings = validated(raw_rec)
    except NoUsableEEG as e:
        return no_signal_result(raw_rec, req, model_name, str(e))
    cr = decode_clean(rec, cfg)
    res, tr = cr.result, cr.result.transcript
    reliable = res.thresholds.separability >= SEPARABILITY_MIN and bool(res.segments)
    if reliable:
        fixed = correct_transcript(tr, segment_breaks(rec))
        final = polish(fixed.words, fixed.sentence_starts)
    else:
        # Noise decodes to random letters; correcting them would invent plausible words.
        fixed = Corrected(res.text.split(), [], res.text.split())
        final = Polished(())
        input_warnings = [UNRELIABLE_WARNING.format(sep=res.thresholds.separability)] + input_warnings
    # Decoded text is a participant's message: keep it out of INFO logs.
    log.info("decoded %s (%.0f s) with %s: %d characters", Path(req.display_name).suffix,
             rec.duration, model_name, len(final.text))
    log.debug("decoded text: %r -> %r", res.text, final.text)
    return {
        "file": req.display_name,
        "duration_s": _r(rec.duration, 2),
        "sfreq": float(rec.sfreq),
        "n_channels": len(rec.ch_names),
        "channels_used": list(res.activation.channels),
        "bad_channels": list(rec.bad_channels),
        "model": model_name,
        "reliable": reliable,
        "session_notes": list(req.notes),
        "text": final.text,
        "raw_text": res.text,
        "corrected_text": fixed.upper_text,
        "morse": res.morse,
        "sentence_types": final.kinds,
        "corrections": [{"from": f.original, "to": f.corrected, "cost": _r(f.cost, 2)}
                        for f in fixed.fixes],
        "letters": [{"code": l.code, "char": l.char, "status": l.status,
                     "t_start": _r(l.t_start), "t_end": _r(l.t_end)} for l in tr.letters],
        "elements": [{"t_on": _r(e.t_on), "t_off": _r(e.t_off), "symbol": e.symbol,
                      "boundary": e.boundary} for e in tr.elements],
        "artifacts": _artifacts(cr),
        "trace": _trace(cr),
        "quality": {"separability": _r(res.thresholds.separability),
                    "n_key_downs": len(res.segments),
                    "n_artifacts": len(cr.eye_events) + len(cr.pops),
                    "artifact_aware": cr.artifact_aware,
                    "warnings": input_warnings + res.warnings + tr.notes},
        "timing": {"unit_s": _r(tr.unit_s, 4), "dash_threshold_s": _r(tr.dash_threshold_s, 4),
                   "letter_gap_s": _r(tr.letter_gap_s, 4), "word_gap_s": _r(tr.word_gap_s, 4)},
        "score": _score(fixed.upper_text, req.expected),
    }


def no_signal_result(rec: eio.Recording, req: DecodeRequest, model_name: str, reason: str) -> dict:
    """Result for a file without usable EEG: nothing decoded, the reason as the first warning."""
    return {
        "file": req.display_name, "duration_s": _r(rec.duration, 2), "sfreq": float(rec.sfreq),
        "n_channels": len(rec.ch_names), "channels_used": [], "bad_channels": list(rec.ch_names),
        "model": model_name, "reliable": False, "session_notes": list(req.notes),
        "text": "", "raw_text": "", "corrected_text": "", "morse": "", "sentence_types": [],
        "corrections": [], "letters": [], "elements": [], "artifacts": [],
        "trace": {"t": [], "activation": [], "lo": None, "hi": None},
        "quality": {"separability": 0.0, "n_key_downs": 0, "n_artifacts": 0, "artifact_aware": False,
                    "warnings": [reason[:1].upper() + reason[1:]]},
        "timing": {"unit_s": 0.0, "dash_threshold_s": 0.0, "letter_gap_s": 0.0, "word_gap_s": 0.0},
        "score": None,
    }

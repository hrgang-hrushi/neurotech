"""The go/no-go rule, and the record that says which model may type.

A verdict belongs to one exact model file. Recalibrating makes a new file, so an old pass
can't carry over. Attempts are stored apart from verdicts, so repeated tries stay visible
even after recalibrating: running a check until it passes is exactly how a weak decoder
would slip through.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from .config import ARTIFACT_DIR


@dataclass(frozen=True)
class GoRule:
    left_right: float = 0.85
    three_class: float = 0.70
    false_per_min: float = 0.5
    symbols: int = 17
    cues: int = 20
    rest_s: float = 120.0


@dataclass(frozen=True)
class Choice:
    model_path: Path
    movement: str
    banner: str
    sha: str
    threshold: float


class Refused(RuntimeError):
    """No model has earned the right to type."""


def session_path(movement: str, artifact_dir: Path | None = None) -> Path:
    return (artifact_dir or ARTIFACT_DIR) / f"session-{movement}.joblib"


def verdict_path(model_path: Path) -> Path:
    return model_path.with_suffix(".verdict.json")


def model_sha1(path: Path) -> str:
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()[:10]


def _number(value, low: float = 0.0, high: float = math.inf) -> float | None:
    """A real number in range, or None. NaN fails every comparison, so it would pass a bar."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or not low <= value <= high:
        return None
    return float(value)


def judge(offline: dict | None, live: dict | None, movement: str,
          rule: GoRule = GoRule()) -> tuple[bool, list[str]]:
    """Apply the rule to raw scores. Returns (go, the reasons it isn't).

    Every number is checked before it is compared, so a missing, broken or edited value fails.
    """
    reasons = []
    if movement not in ("imagined", "real"):
        reasons.append(f"movement is {movement!r}, so this model can't be trusted to type")
    if offline is None:
        reasons.append("no held-out scores")
    else:
        left_right = _number(offline.get("left_right"), 0, 1)
        three_class = _number(offline.get("three_class"), 0, 1)
        if left_right is None or left_right < rule.left_right:
            reasons.append(f"left vs right {offline.get('left_right')} is below {rule.left_right}")
        if three_class is None or three_class < rule.three_class:
            reasons.append(f"rest, left, right {offline.get('three_class')} is below "
                           f"{rule.three_class}")
    if live is None:
        reasons.append("no live check yet")
    else:
        clean = _number(live.get("clean_s")) or 0.0
        false_rate = _number(live.get("false_per_min"))
        cues, correct = _number(live.get("cues")), _number(live.get("correct"))
        if live.get("source") != "eeg":
            reasons.append(f"the live check ran on {live.get('source')}, not live EEG")
        if clean < rule.rest_s:
            reasons.append(f"only {clean:.0f} s of clean rest, needs {rule.rest_s:.0f} s")
        elif false_rate is None or false_rate > rule.false_per_min:
            reasons.append(f"{live.get('false_per_min')} false activations a minute, limit is "
                           f"{rule.false_per_min}")
        if cues != rule.cues or correct is None or correct > cues or correct < rule.symbols:
            reasons.append(f"{live.get('correct')} of {live.get('cues')} live symbols correct, "
                           f"needs {rule.symbols} of {rule.cues}")
    return not reasons, reasons


def _write(model_path: Path, record: dict) -> dict:
    record["go"], record["reasons"] = judge(record["offline"], record["live"], record["movement"])
    verdict_path(model_path).write_text(json.dumps(record, indent=1))
    return record


def save_offline(model_path: Path, movement: str, decoder: str, scores: dict) -> dict:
    """Record held-out scores for a new model. Any earlier live result no longer applies."""
    return _write(model_path, {
        "sha": model_sha1(model_path), "movement": movement,
        "offline": {"decoder": decoder, "left_right": scores.get("left_right"),
                    "three_class": scores.get("balanced_raw"), "windows": scores.get("n")},
        "live": None})


def load_verdict(model_path: Path) -> dict | None:
    """The model's verdict, or None if it's missing, broken, or for a different file."""
    try:
        record = json.loads(verdict_path(model_path).read_text())
        complete = all(key in record for key in ("offline", "live", "movement", "reasons"))
        return record if complete and record["sha"] == model_sha1(model_path) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def attempts_path(artifact_dir: Path) -> Path:
    return artifact_dir / "check-attempts.json"


def read_attempts(movement: str, artifact_dir: Path) -> int:
    try:
        return int(json.loads(attempts_path(artifact_dir).read_text()).get(movement, 0))
    except (OSError, ValueError):
        return 0


def begin_attempt(model_path: Path) -> int:
    """Count a live check before it starts, so stopping a bad run doesn't erase it."""
    record = load_verdict(model_path)
    if record is None:
        raise Refused(f"{model_path} has no matching verdict. Run: eegmove calibrate")
    folder = Path(model_path).parent
    try:
        counts = json.loads(attempts_path(folder).read_text())
    except (OSError, ValueError):
        counts = {}
    counts[record["movement"]] = counts.get(record["movement"], 0) + 1
    attempts_path(folder).write_text(json.dumps(counts))
    return counts[record["movement"]]


def save_live(model_path: Path, live: dict) -> dict:
    """Add a finished live check to a calibrated model's verdict."""
    record = load_verdict(model_path)
    if record is None:
        raise Refused(f"{model_path} has no matching verdict. Run: eegmove calibrate")
    record["live"] = live
    return _write(model_path, record)


def choose_model(artifact_dir: Path | None = None) -> Choice:
    """Imagined movement if it passed, else real movement, clearly labelled, else refuse."""
    folder = artifact_dir or ARTIFACT_DIR
    reasons = []
    banners = {"imagined": "IMAGINED MOVEMENT",
               "real": "REAL MOVEMENT FALLBACK: imagined movement did not pass"}
    for movement, banner in banners.items():
        path = session_path(movement, folder)
        record = load_verdict(path) if path.exists() else None
        if record is None:
            reasons.append(f"{movement}: no verdict for {path.name}")
            continue
        go, why = judge(record["offline"], record["live"], record["movement"])  # today's rule
        if go and record["movement"] == movement:
            return Choice(path, movement, banner, record["sha"], record["live"]["threshold"])
        reasons.append(f"{movement}: " + "; ".join(why or ["wrong movement in this file"]))
    raise Refused("No model may type.\n  " + "\n  ".join(reasons))

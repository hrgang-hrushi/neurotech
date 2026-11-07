"""The go/no-go rule, and the record that says which model may type.

A verdict belongs to one exact model file. Recalibrating makes a new file, so an old pass
can't carry over. Attempts are stored apart from verdicts, so repeated tries stay visible
even after recalibrating: running a check until it passes is exactly how a weak decoder
would slip through.
"""

from __future__ import annotations

import hashlib
import json
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


def judge(offline: dict | None, live: dict | None, movement: str,
          rule: GoRule = GoRule()) -> tuple[bool, list[str]]:
    """Apply the rule to raw scores. Returns (go, the reasons it isn't)."""
    reasons = []
    if movement not in ("imagined", "real"):
        reasons.append(f"movement is {movement!r}, so this model can't be trusted to type")
    if offline is None:
        reasons.append("no held-out scores")
    else:
        left_right, three_class = offline.get("left_right"), offline.get("three_class")
        if left_right is None or left_right < rule.left_right:
            reasons.append(f"left vs right {left_right} is below {rule.left_right}")
        if three_class is None or three_class < rule.three_class:
            reasons.append(f"rest, left, right {three_class} is below {rule.three_class}")
    if live is None:
        reasons.append("no live check yet")
    else:
        if live.get("source") != "eeg":
            reasons.append(f"the live check ran on {live.get('source')}, not live EEG")
        if live.get("clean_s", 0) < rule.rest_s:
            reasons.append(f"only {live.get('clean_s', 0):.0f} s of clean rest, needs "
                           f"{rule.rest_s:.0f} s")
        elif live["false_per_min"] > rule.false_per_min:
            reasons.append(f"{live['false_per_min']:.2f} false activations a minute, limit is "
                           f"{rule.false_per_min}")
        if live.get("cues", 0) < rule.cues or live.get("correct", 0) < rule.symbols:
            reasons.append(f"{live.get('correct', 0)} of {live.get('cues', 0)} live symbols "
                           f"correct, needs {rule.symbols} of {rule.cues}")
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
        return record if record["sha"] == model_sha1(model_path) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def attempts_path(artifact_dir: Path) -> Path:
    return artifact_dir / "check-attempts.json"


def read_attempts(movement: str, artifact_dir: Path) -> int:
    try:
        return int(json.loads(attempts_path(artifact_dir).read_text()).get(movement, 0))
    except (OSError, ValueError):
        return 0


def save_live(model_path: Path, live: dict) -> dict:
    """Add a live check to a calibrated model's verdict, and count the attempt."""
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
        elif record["go"] and record["movement"] == movement:
            return Choice(path, movement, banner, record["sha"], record["live"]["threshold"])
        else:
            reasons.append(f"{movement}: " + "; ".join(record["reasons"] or ["not approved"]))
    raise Refused("No model may type.\n  " + "\n  ".join(reasons))

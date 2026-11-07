"""`eegmove check`: measure a calibrated model live, and record whether it may type.

Held-out scores come from one sitting with long, cued trials. This is the real evidence: two
minutes of rest, then 20 cued symbols, through the exact model file the demo would run. Cues
are the same neutral text for both hands, printed in the terminal.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from pathlib import Path

import pylsl

from .live import MORSE_DEBOUNCE, LiveSession
from .record import prompts_for
from .verdict import GoRule, begin_attempt, save_live

CUE_S = 4.0
SLOT_S = (8.5, 9.5)  # jittered so the next cue can't be anticipated
LATE_S = 1.0
REST_DEADLINE_S = 180.0


@dataclass(frozen=True)
class CheckCue:
    label: str
    slot_s: float


def build_check_cues(n: int = 20, seed: int = 4) -> list[CheckCue]:
    rng = random.Random(seed)
    labels = ["left", "right"] * (n // 2)
    rng.shuffle(labels)
    return [CheckCue(label, rng.uniform(*SLOT_S)) for label in labels]


def summarize_rest(messages: list[dict], rest_s: float = 120.0) -> dict:
    """Count events over exactly `rest_s` of clean windows. Rejected windows count for nothing."""
    clean_s, events = 0.0, 0
    for message in messages:
        if clean_s >= rest_s:
            break
        if message["ok"]:
            clean_s += message["step_s"]
            events += message["event"] is not None
    return {"clean_s": clean_s, "false_activations": events,
            "false_per_min": events / (clean_s / 60) if clean_s else None}


def confident_rest_share(messages: list[dict]) -> float | None:
    """How much of clean rest the decoder was sure of. Letters only finish on these steps."""
    clean = [m for m in messages if m["ok"]]
    return sum(bool(m.get("rest")) for m in clean) / len(clean) if clean else None


def score_cues(onsets: list[tuple[str, float, float]], messages: list[dict]) -> dict:
    """Score (label, onset, slot end) slots by when the data happened, not when it arrived.

    A slot is correct only if it holds exactly one event and that event matches, so a rebound
    symbol after the cue counts as wrong. A message more than a second behind fails its slot,
    because the demo wouldn't feel like typing at that delay.
    """
    correct = 0
    for label, start, stop in onsets:
        slot = [m for m in messages if m.get("lsl_time") is not None and start <= m["lsl_time"] < stop]
        late = any(m.get("latency_ms", 0) > LATE_S * 1000 for m in slot)
        correct += not late and [m["event"] for m in slot if m["event"]] == [label]
    return {"correct": int(correct), "cues": len(onsets)}


def collect_rest(session, rest_s: float, deadline_s: float = REST_DEADLINE_S,
                 now=time.monotonic) -> list[dict]:
    """Decode until there is enough clean rest, or the deadline passes."""
    messages: list[dict] = []
    stop = now() + deadline_s
    for message in session.decode():
        if now() >= stop:
            break
        if message is not None:
            messages.append(message)
            if summarize_rest(messages, rest_s)["clean_s"] >= rest_s:
                break
    return messages


def collect_until(session, stop: float, messages: list[dict], clock) -> None:
    for message in session.decode():
        if message is not None:
            messages.append(message)
        if clock() >= stop:
            return


def run_check(model_path: Path, stream: str | None = None, baseline_s: float = 60.0,
              rest_s: float = 120.0, n_cues: int = 20, threshold: float = 0.6,
              seed: int | None = None, session=None, deadline_s: float = REST_DEADLINE_S,
              now=time.monotonic, clock=pylsl.local_clock, say=print) -> dict:
    attempt = begin_attempt(model_path)
    seed = random.SystemRandom().randrange(2**31) if seed is None else seed  # new order each try
    session = session or LiveSession(model_path, stream=stream, threshold=threshold)
    prompts = prompts_for(session.movement if session.movement != "unknown" else "real")
    say(f"Attempt {attempt} for {session.movement} movement.")
    say(f"Baseline: sit still and relax for {baseline_s:.0f}s ...")
    session.collect_baseline(baseline_s)
    say(f"Rest check: stay relaxed for {rest_s:.0f}s of clean signal ...")
    session.flush()
    rest_messages = collect_rest(session, rest_s, deadline_s, now)
    rest = summarize_rest(rest_messages, rest_s)
    sure = confident_rest_share(rest_messages)
    say(f"  {rest['clean_s']:.0f} s clean, {rest['false_activations']} false activations")
    if sure is not None:
        say(f"  Confident rest on {sure:.0%} of it. Letters finish slowly if this is low.")

    result, messages = {"correct": 0, "cues": 0}, []
    if rest["clean_s"] >= rest_s:
        say(f"Symbol check: {n_cues} cues. Follow each one, then relax until the next.")
        session.flush()
        onsets = []
        for index, cue in enumerate(build_check_cues(n_cues, seed), 1):
            big, small = prompts[cue.label]
            say(f"  [{index:2d}/{n_cues}] {big}: {small}")
            start = clock()
            collect_until(session, start + CUE_S, messages, clock)
            say("          +")
            collect_until(session, start + cue.slot_s, messages, clock)
            onsets.append((cue.label, start, start + cue.slot_s))
        result = score_cues(onsets, messages)
        say(f"  {result['correct']} of {result['cues']} correct")
    else:
        say("  Not enough clean rest, so the symbol check was skipped.")

    strength = session.signal_strength()
    if strength:
        say(f"Signal strength at rest over {strength['region']}: {strength['baseline_db']:.1f} dB "
            f"at baseline, {strength['current_db']} dB now (information only, not part of the rule)")
    warnings = sorted({m["warning"] for m in rest_messages + messages if m.get("warning")})
    for warning in warnings:
        say(f"WARNING: {warning}")
    live = {**rest, **result, "source": session.source, "threshold": session.threshold,
            "debounce": MORSE_DEBOUNCE, "signal_strength": strength, "seed": seed,
            "attempt": attempt, "warnings": warnings, "confident_rest_share": sure}
    record = save_live(model_path, live)
    say("GO: this model may type." if record["go"] else "NO-GO:")
    for reason in record["reasons"]:
        say(f"  - {reason}")
    return record


__all__ = ["CheckCue", "GoRule", "build_check_cues", "collect_rest", "run_check", "score_cues",
           "summarize_rest"]

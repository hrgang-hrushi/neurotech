"""Artifact-aware offline decode for clench-style (EMG power) configs.

Same chain as `pipeline.decode`, with extra steps from `artifacts`:
  - eye events and electrode pops are found from the raw EEG first;
  - eye (frontopolar) EMG is regressed out of every candidate channel and
    popping electrodes are patched, before thresholds are fit;
  - clench channels are re-chosen per recording among the model's and the
    preset's channels by how cleanly they separate rest from clench.
Non-EMG configs (blink, motor) fall back to the plain decoder.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field

from . import artifacts as art
from .config import PRESETS, PipelineConfig
from .detect import detect, otsu
from .io import Recording
from .pipeline import Result, _quality_warnings, decode, ensure_bad_channels, segment_breaks
from .signal import settled_mask
from .timing import transcribe

# Keep channels whose separability is within this of the best, at most MAX_CHANNELS.
ETA_SLACK = 0.03
MAX_CHANNELS = 6


@dataclass(frozen=True)
class ChannelScore:
    name: str
    separability: float
    eye_gain: float


@dataclass(frozen=True)
class CleanResult:
    result: Result
    eye_events: list[art.Artifact] = field(default_factory=list)
    pops: list[art.Artifact] = field(default_factory=list)
    channel_scores: list[ChannelScore] = field(default_factory=list)
    artifact_aware: bool = False


def is_clench_like(cfg: PipelineConfig) -> bool:
    f = cfg.feature
    return f.measure == "power" and f.direction == "increase" and f.band[0] >= 20.0


def _score(ce: art.CleanEnvelopes, settle_s: float, edge_s: float) -> list[ChannelScore]:
    bp = ce.bp
    usable = settled_mask(bp.t, bp.slices, bp.rate, settle_s, edge_s)
    scores = [ChannelScore(n, float(otsu(e[usable])[3]), ce.gain.get(n, 0.0))
              for n, e in zip(bp.names, ce.env)]
    return sorted(scores, key=lambda s: -s.separability)


def _choose(scores: list[ChannelScore]) -> list[str]:
    best = scores[0].separability
    return [s.name for s in scores if s.separability >= best - ETA_SLACK][:MAX_CHANNELS]


def decode_clean(rec: Recording, cfg: PipelineConfig, correct: bool = True) -> CleanResult:
    """Decode with eye EMG and electrode pops removed (clench-like configs only)."""
    ensure_bad_channels(rec)
    if not is_clench_like(cfg):
        return CleanResult(decode(rec, cfg, correct))
    wanted = list(dict.fromkeys(cfg.feature.channels + PRESETS["clench"]["feature"]["channels"]))
    cands = art.candidate_channels(rec, wanted)
    if not cands:
        return CleanResult(decode(rec, cfg, correct))
    eye = art.detect_eye_events(rec)
    pops = art.detect_pops(rec)
    c = copy.deepcopy(cfg)
    c.feature.channels = cands
    ce = art.clean_envelopes(rec, c.feature, eye, pops)
    scores = _score(ce, c.detect.settle_s, c.detect.edge_s)
    chosen = _choose(scores)
    c.feature.channels = chosen
    act = art.to_activation(ce, [ce.bp.names.index(n) for n in chosen], rec.sfreq)

    c.detect.lo = c.detect.hi = None
    segs, th = detect(act.t, act.values, act.rate, c.detect, act.seg_slices)
    tr = transcribe(segs, c.timing, correct, breaks=segment_breaks(rec))
    warns = _quality_warnings(th, segs, rec.duration)
    if rec.bad_channels:
        warns.append(f"Excluded bad channels (impedance/amplitude): {', '.join(rec.bad_channels)}")
    if not ce.frontopolar:
        warns.append("No frontopolar channel (Fp1/Fp2): blink muscle activity could not be removed.")
    return CleanResult(Result(rec, c, act, segs, th, tr, warns), eye, pops, scores, True)

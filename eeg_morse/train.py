"""Train a detector on a recording with labeled events (placed in eego).

"Training" here means tuning the detector to one person, cap and movement:
which channels, which reference, how much smoothing, how much hysteresis,
and (when short and long versions were labeled) where the short/long
boundary lies, i.e. the dot/dash threshold.

Scoring uses the labels you placed in eego:
  hit          a labeled event that overlaps a detection (within `tol_s`)
  false alarm  a detection in a segment where that movement was never labeled
               (e.g. a "clench" detected during the blink block)
Detections in labeled segments that match no label are reported as
"unlabeled", not penalised: people blink more often than they get labeled.
"""
from __future__ import annotations

import copy
import itertools
from dataclasses import asdict, dataclass, field

import numpy as np

from .config import PipelineConfig
from .detect import Segment, Thresholds, detect
from .io import Annotation, Recording
from .pipeline import ensure_bad_channels
from .signal import Activation, activation, channel_envelopes, settled_mask


def select(rec: Recording, patterns: list[str]) -> list[Annotation]:
    """Annotations whose label contains any pattern (case-insensitive)."""
    pats = [p.lower() for p in patterns]
    return [a for a in rec.annotations if any(p in a.label.lower() for p in pats)]


@dataclass
class EventMatch:
    label: str
    onset: float
    duration: float
    det_on: float | None
    det_off: float | None

    @property
    def hit(self) -> bool:
        return self.det_on is not None

    @property
    def det_duration(self) -> float | None:
        return None if self.det_on is None else self.det_off - self.det_on


def match(segs: list[Segment], anns: list[Annotation], tol_s: float) -> tuple[list[EventMatch], list[int]]:
    """One-to-one matching, largest overlap first (hand-placed labels are often
    offset, so pairing in time order mis-pairs neighbours).

    Returns (matches in label order, unmatched detection indices).
    """
    anns = sorted(anns, key=lambda x: x.onset)
    pairs = []
    for j, a in enumerate(anns):
        lo, hi = a.onset - tol_s, a.onset + max(a.duration, 0.1) + tol_s
        for i, s in enumerate(segs):
            ov = min(hi, s.t_off) - max(lo, s.t_on)
            if ov > 0:
                # rank by overlap with the label itself, then with the tolerance window
                core = min(a.onset + max(a.duration, 0.1), s.t_off) - max(a.onset, s.t_on)
                pairs.append((max(core, 0.0), ov, j, i))
    pairs.sort(reverse=True)
    det_of: dict[int, int] = {}
    used: set[int] = set()
    for _core, _ov, j, i in pairs:
        if j not in det_of and i not in used:
            det_of[j] = i
            used.add(i)
    out = []
    for j, a in enumerate(anns):
        i = det_of.get(j)
        out.append(EventMatch(a.label, a.onset, a.duration,
                              None if i is None else segs[i].t_on,
                              None if i is None else segs[i].t_off))
    return out, [i for i in range(len(segs)) if i not in used]


@dataclass
class Score:
    hits: int
    n_labels: int
    false_alarms: int
    unlabeled: int
    minutes_without_labels: float

    @property
    def recall(self) -> float:
        return self.hits / self.n_labels if self.n_labels else 0.0

    @property
    def precision(self) -> float:
        return self.hits / (self.hits + self.false_alarms) if self.hits + self.false_alarms else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def score(rec: Recording, segs: list[Segment], anns: list[Annotation], tol_s: float):
    matches, unmatched = match(segs, anns, tol_s)
    labeled_segs = {rec.segment_of(a.onset) for a in anns}
    fa = sum(1 for i in unmatched if rec.segment_of(segs[i].t_on) not in labeled_segs)
    unl = len(unmatched) - fa
    free = sum(b - a for k, (a, b) in enumerate(rec.segments) if k not in labeled_segs) / rec.sfreq
    return Score(sum(m.hit for m in matches), len(anns), fa, unl, free / 60), matches, unmatched


def channel_ranking(rec: Recording, cfg: PipelineConfig, anns: list[Annotation],
                    channels: list[str] | None = None) -> list[tuple[str, float]]:
    """Effect size (d') of each channel's activation inside labeled events vs
    the settled parts of segments without such events. Best first."""
    f = copy.deepcopy(cfg.feature)
    f.channels = channels or [c for c, t in zip(rec.ch_names, rec.ch_types) if t == "eeg"]
    env, t, slices, names, _, rate = channel_envelopes(rec, f)
    usable = settled_mask(t, slices, rate, cfg.detect.settle_s, cfg.detect.edge_s)
    inside = np.zeros(t.size, dtype=bool)
    for a in anns:
        inside |= (t >= a.onset) & (t <= a.onset + max(a.duration, 0.2))
    labeled = {rec.segment_of(a.onset) for a in anns}
    seg_of_t = np.full(t.size, -1)
    for k, (a, b) in enumerate(slices):
        seg_of_t[a:b] = k
    # map envelope slices to recording segments (same order, short ones skipped)
    rec_seg = [rec.segment_of(float(t[a])) for a, _ in slices]
    outside = usable & ~inside & np.isin(seg_of_t, [i for i, s in enumerate(rec_seg) if s not in labeled])
    if not outside.any():
        outside = usable & ~inside
    out = []
    for n, e in zip(names, env):
        x, y = e[inside & usable], e[outside]
        if x.size < 5 or y.size < 5:
            continue
        d = (x.mean() - y.mean()) / np.sqrt((x.var() + y.var()) / 2 + 1e-12)
        out.append((n, float(d)))
    return sorted(out, key=lambda kv: -kv[1])


@dataclass
class ShortLong:
    threshold_s: float
    accuracy: float
    short_durations: list[float]
    long_durations: list[float]


def learn_short_long(rec: Recording, segs: list[Segment], matches: list[EventMatch],
                     short_pat: str, long_pat: str) -> ShortLong | None:
    """Duration boundary between short and long events (= dot/dash threshold).

    Uses matched detections plus unlabeled detections in segments where only
    one of the two kinds was labeled (people do more than get labeled).
    """
    seg_kind: dict[int, set[str]] = {}
    for m in matches:
        kind = "short" if short_pat.lower() in m.label.lower() else (
            "long" if long_pat.lower() in m.label.lower() else None)
        if kind:
            seg_kind.setdefault(rec.segment_of(m.onset), set()).add(kind)
    short, long_ = [], []
    for s in segs:
        kinds = seg_kind.get(rec.segment_of(s.t_on), set())
        if len(kinds) == 1:
            (short if "short" in kinds else long_).append(s.duration)
    if not short or not long_:
        return None
    cands = sorted(set(short + long_))
    best = (-1.0, 0.0)
    for i in range(len(cands) - 1):
        thr = float(np.sqrt(cands[i] * cands[i + 1]))
        acc = (sum(d <= thr for d in short) + sum(d > thr for d in long_)) / (len(short) + len(long_))
        # prefer the widest margin among equally accurate cut points
        margin = np.log(cands[i + 1] / cands[i])
        if (acc, margin) > best:
            best, thr_best = (acc, margin), thr
    return ShortLong(thr_best, best[0], sorted(short), sorted(long_))


@dataclass
class TrainResult:
    config: PipelineConfig
    activation: Activation
    segments: list[Segment]
    thresholds: Thresholds
    score: Score
    matches: list[EventMatch]
    channel_ranking: list[tuple[str, float]]
    short_long: ShortLong | None
    tried: int
    targets: list[str]
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        s, f, d = self.score, self.config.feature, self.config.detect
        lines = [
            f"targets  : {', '.join(self.targets)}",
            f"detected : {s.hits}/{s.n_labels} labeled events (recall {s.recall:.0%}), "
            f"{s.false_alarms} false alarm(s) in {s.minutes_without_labels:.1f} min without that "
            f"movement, {s.unlabeled} unlabeled detection(s) in labeled blocks",
            f"settings : channels {', '.join(f.channels)} | reference {f.reference} | "
            f"band {f.band[0]:g}-{f.band[1]:g} Hz | smooth {f.smooth_s:g}s | hysteresis {d.hysteresis:g}"
            + (f" | baseline {f.baseline_s:g}s/p{f.baseline_pct:g}" if f.measure == "amplitude" else ""),
            f"contrast : separability {self.thresholds.separability:.2f} (noise ~0.65)",
            "channels : " + ", ".join(f"{n} {v:.1f}" for n, v in self.channel_ranking[:8])
            + "  (effect size inside labeled events)",
        ]
        if self.short_long:
            sl = self.short_long
            lines.append(
                f"short/long boundary {sl.threshold_s:.2f}s ({sl.accuracy:.0%} correct): short "
                f"{np.median(sl.short_durations):.2f}s median (n={len(sl.short_durations)}), long "
                f"{np.median(sl.long_durations):.2f}s median (n={len(sl.long_durations)})")
        lines.append("events   :")
        for m in self.matches:
            det = (f"detected {m.det_on:7.2f}-{m.det_off:7.2f}s ({m.det_duration:.2f}s)"
                   if m.hit else "MISSED")
            lines.append(f"  {m.onset:7.2f}s +{m.duration:4.2f}s  {m.label:24s} {det}")
        lines += [f"note     : {n}" for n in self.notes]
        return "\n".join(lines)

    def report(self) -> dict:
        s = self.score
        return {
            "targets": self.targets,
            "recall": s.recall, "precision": s.precision, "f1": s.f1,
            "hits": s.hits, "labels": s.n_labels, "false_alarms": s.false_alarms,
            "unlabeled_detections": s.unlabeled,
            "separability": self.thresholds.separability,
            "channel_ranking": self.channel_ranking,
            "short_long": asdict(self.short_long) if self.short_long else None,
            "events": [dict(asdict(m), hit=m.hit) for m in self.matches],
            "detections": [(x.t_on, x.t_off) for x in self.segments],
            "config": self.config.to_dict(),
            "settings_tried": self.tried,
            "notes": self.notes,
        }


def train(rec: Recording, cfg: PipelineConfig, targets: list[str], short: str | None = None,
          long: str | None = None, tol_s: float = 1.0, search_all_channels: bool = True) -> TrainResult:
    ensure_bad_channels(rec)
    anns = select(rec, targets)
    if not anns:
        raise ValueError(f"no labeled events match {targets}; labels in this file: "
                         f"{sorted(rec.labels())}")
    good = [c for c, t in zip(rec.ch_names, rec.ch_types)
            if t == "eeg" and c not in rec.bad_channels]
    ranking = channel_ranking(rec, cfg, anns, good if search_all_channels else None)
    preset_ch = [c for c in good if c.lower() in {x.lower() for x in cfg.feature.channels}]
    ranked = [n for n, d in ranking if d > 0]
    subsets: list[list[str]] = []
    for sub in (preset_ch, ranked[:6], ranked[:3], ranked[:2], ranked[:1]):
        if sub and sub not in subsets:
            subsets.append(sub)
    refs = ["car", "none"]
    smooth = [round(cfg.feature.smooth_s * k, 4) for k in (0.5, 1.0, 1.5, 2.0)]
    hyst = [0.1, 0.25, 0.4]
    if cfg.feature.measure == "amplitude":
        base = list(itertools.product((10.0, 20.0, 40.0), (10.0, 25.0)))
    else:
        base = [(cfg.feature.baseline_s, cfg.feature.baseline_pct)]

    best_key, best, tried = None, None, 0
    for (k, chans), ref, sm, (bs, bp) in itertools.product(enumerate(subsets), refs, smooth, base):
        c = copy.deepcopy(cfg)
        c.feature.channels, c.feature.reference, c.feature.smooth_s = list(chans), ref, sm
        c.feature.baseline_s, c.feature.baseline_pct = bs, bp
        try:
            act = activation(rec, c.feature)
        except ValueError:
            continue
        for h in hyst:
            c.detect.hysteresis = h
            c.detect.lo = c.detect.hi = None
            segs, th = detect(act.t, act.values, act.rate, c.detect, act.seg_slices)
            sc, matches, _ = score(rec, segs, anns, tol_s)
            tried += 1
            dist = (abs(np.log(sm / cfg.feature.smooth_s)) + abs(np.log(h / cfg.detect.hysteresis))
                    + 0.3 * k + 0.3 * (ref != cfg.feature.reference))
            # Unlabeled detections inside labeled blocks are not penalised: people
            # blink (and clench) more often than anyone labels.
            key = (round(sc.f1, 4), round(th.separability, 2), -dist)
            if best_key is None or key > best_key:
                best_key = key
                best = (copy.deepcopy(c), act, segs, th, sc, matches)

    c, act, segs, th, sc, matches = best
    notes = []
    sl = None
    if short and long:
        sl = learn_short_long(rec, segs, matches, short, long)
        if sl is not None:
            # dot/dash threshold = learned boundary; unit fixed from it
            c.timing.unit_s = round(sl.threshold_s / c.timing.dash_ratio, 4)
            c.timing.bias_s = 0.0
            notes.append("Gap thresholds (letter/word) are derived from the unit but not trained: "
                         "record a known phrase (e.g. PARIS) to tune them with `calibrate`.")
    c.detect.lo, c.detect.hi = float(th.lo), float(th.hi)
    c.detect.rest_level = float(th.rest_level)
    missed = [m for m in matches if not m.hit]
    if missed:
        notes.append("Missed labels: " + ", ".join(f"{m.label} at {m.onset:.1f}s" for m in missed)
                     + ". Check those in eego: a label without a visible event is likely misplaced.")
    if rec.bad_channels:
        notes.append(f"Excluded bad channels: {', '.join(rec.bad_channels)} "
                     "(impedance > 1000 kOhm or flat).")
    c.preset = f"trained:{cfg.preset}"
    return TrainResult(c, act, segs, th, sc, matches, ranking, sl, tried, targets, notes)

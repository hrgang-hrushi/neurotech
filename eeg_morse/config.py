"""Configuration objects and presets for the EEG -> Morse pipeline.

Every stage is driven by three small dataclasses so a calibration run can be
saved to JSON and reused for offline decoding or live (LSL) decoding.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class FeatureConfig:
    """How raw EEG becomes a 1-D "key down" activation signal."""

    channels: list[str]
    band: tuple[float, float]
    # "decrease": movement *suppresses* band power (mu/beta ERD over motor cortex)
    # "increase": movement *adds* band power (EMG from jaw clench, eye blinks)
    direction: str = "decrease"
    reference: str = "car"  # "car" (common average of EEG channels) or "none"
    line_freq: float | None = 60.0  # mains notch; 60 Hz in the US, 50 Hz in EU/Asia
    smooth_s: float = 0.4  # power-envelope moving-average window
    env_rate: float = 50.0  # Hz, envelope is decimated to this rate for detection
    # "power": log band power (oscillations, EMG). "amplitude": signed, smoothed
    # voltage (slow deflections such as eye closure, where power can't tell an
    # undershoot from the deflection itself).
    measure: str = "power"
    # amplitude only: slow baseline = rolling percentile over this window,
    # subtracted instead of high-pass filtering (a high-pass turns every held
    # deflection into an undershoot whose size depends on sending speed).
    baseline_s: float = 10.0
    baseline_pct: float = 25.0

    def __post_init__(self) -> None:
        if self.direction not in ("decrease", "increase"):
            raise ValueError("direction must be 'decrease' or 'increase'")
        if self.measure not in ("power", "amplitude"):
            raise ValueError("measure must be 'power' or 'amplitude'")
        if self.reference not in ("car", "none"):
            raise ValueError("reference must be 'car' or 'none'")
        self.band = (float(self.band[0]), float(self.band[1]))
        self.channels = list(self.channels)


@dataclass
class DetectConfig:
    """How the activation signal becomes key-down / key-up intervals."""

    hysteresis: float = 0.25  # 0 = single threshold, larger = stickier on/off
    min_on_s: float = 0.12  # drop "key down" blips shorter than this
    min_off_s: float = 0.12  # bridge "key up" dropouts shorter than this
    edge_s: float = 0.5  # ignore key-downs touching the recording's first/last edge_s
    # Optional fixed thresholds in activation units (set by `calibrate`).
    lo: float | None = None
    hi: float | None = None
    rest_level: float | None = None  # mean activation while at rest (for drift offset)


@dataclass
class TimingConfig:
    """How key-down/up durations become dots, dashes and gaps.

    Standard Morse: dot = 1 unit, dash = 3, gap inside a letter = 1,
    gap between letters = 3, gap between words = 7.
    """

    unit_s: float | None = None  # None -> estimate from the recording
    default_unit_s: float = 1.0  # fallback when estimation is ambiguous
    bias_s: float = 0.0  # key-down lengthening by the detector (estimated with the unit)
    min_dot_ratio: float = 0.4  # key-downs shorter than this * unit are noise, not dots
    dash_ratio: float = 2.0  # on-duration > dash_ratio * unit -> dash
    letter_gap_ratio: float = 2.0  # gap > ratio * unit -> new letter
    word_gap_ratio: float = 5.0  # gap > ratio * unit -> new word


@dataclass
class PipelineConfig:
    feature: FeatureConfig
    detect: DetectConfig = field(default_factory=DetectConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    preset: str = "custom"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PipelineConfig":
        return cls(
            feature=FeatureConfig(**d["feature"]),
            detect=DetectConfig(**d.get("detect", {})),
            timing=TimingConfig(**d.get("timing", {})),
            preset=d.get("preset", "custom"),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "PipelineConfig":
        return cls.from_dict(json.loads(Path(path).read_text()))


# Channel labels follow the 10-10 names used on ANT Neuro waveguard caps
# (eego 32/64). Missing channels are skipped with a warning, so the same preset
# works on 32- and 64-channel caps.
PRESETS: dict[str, dict] = {
    # Real or imagined hand movement: mu (8-13 Hz) + beta (13-30 Hz) power drops
    # over sensorimotor cortex (event-related desynchronisation, ERD). Slow and
    # smeared, so it needs long Morse units (~1 s dots).
    "motor": dict(
        feature=dict(
            channels=["C3", "C4", "Cz", "FC1", "FC2", "CP1", "CP2", "C1", "C2"],
            band=(8.0, 30.0),
            direction="decrease",
            reference="car",
            smooth_s=0.5,
        ),
        detect=dict(min_on_s=0.25, min_off_s=0.25),
        timing=dict(default_unit_s=1.0),
    ),
    # Jaw clench: broadband muscle (EMG) power on temporal electrodes. Strong and
    # fast; the most reliable "switch" on a scalp cap.
    "clench": dict(
        feature=dict(
            channels=["T7", "T8", "FT7", "FT8", "TP7", "TP8", "M1", "M2"],
            band=(30.0, 95.0),
            direction="increase",
            reference="car",
            smooth_s=0.1,
        ),
        detect=dict(min_on_s=0.08, min_off_s=0.08),
        timing=dict(default_unit_s=0.3),
    ),
    # Deliberate eye closures/blinks: large slow deflections on frontal channels.
    "blink": dict(
        feature=dict(
            channels=["Fp1", "Fp2", "Fpz"],
            band=(0.0, 8.0),  # low edge 0 = low-pass only; drift handled by baseline_s
            direction="increase",
            reference="none",
            smooth_s=0.15,
            measure="amplitude",
        ),
        detect=dict(min_on_s=0.1, min_off_s=0.1),
        timing=dict(default_unit_s=0.4),
    ),
}


def preset(name: str, **overrides) -> PipelineConfig:
    """Build a config from a named preset, with optional nested overrides.

    overrides keys: feature, detect, timing -> dicts merged into the preset.
    """
    if name not in PRESETS:
        raise KeyError(f"unknown preset {name!r}; choose from {sorted(PRESETS)}")
    base = PRESETS[name]
    parts = {}
    for key in ("feature", "detect", "timing"):
        merged = dict(base.get(key, {}))
        merged.update({k: v for k, v in overrides.get(key, {}).items() if v is not None})
        parts[key] = merged
    return PipelineConfig(
        feature=FeatureConfig(**parts["feature"]),
        detect=DetectConfig(**parts["detect"]),
        timing=TimingConfig(**parts["timing"]),
        preset=name,
    )

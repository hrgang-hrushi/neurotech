"""Settings that offline training and the live loop must agree on."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
ARTIFACT_DIR = ROOT / "artifacts"

# PLACEHOLDER until rotation 1. No document names the real 24-channel layout.
# These are 10-20 sites that also exist in PhysioNet. Cz is left out because the
# EE-511 manual lists Cz as REF for cap CA-505. Once we have a recording, rerun
#   eegmove pretrain --montage-from <recording>
ASSUMED_MONTAGE: tuple[str, ...] = (
    "Fp1", "Fpz", "Fp2", "F7", "F3", "Fz", "F4", "F8",
    "FC5", "FC1", "FC2", "FC6",
    "T7", "C3", "C4", "T8",
    "CP5", "CP1", "CP2", "CP6",
    "P3", "Pz", "P4", "POz",
)

DEFAULT_CLASSES: tuple[str, ...] = ("rest", "left", "right")


@dataclass(frozen=True)
class SignalConfig:
    sfreq: float = 160.0  # model rate; PhysioNet's native rate
    band: tuple[float, float] = (8.0, 30.0)  # mu and beta, where movement ERD lives
    mains: float = 60.0
    window_s: float = 2.0

    @property
    def n_times(self) -> int:
        return int(round(self.window_s * self.sfreq))

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_label(label: str) -> str:
    """Reduce 'EEG C3-Ref', 'C3-CPz' and 'c3' to the same key."""
    text = label.strip()
    text = re.sub(r"^EEG\s+", "", text, flags=re.IGNORECASE)
    return text.split("-")[0].strip().casefold()


def mirror_pairs(channels: list[str] | tuple[str, ...]) -> list[int] | None:
    """Index map that flips the head left-to-right, or None if a partner is missing.

    In 10-20 naming odd numbers are left and even are right, so C3 pairs with C4.
    Midline sites ending in 'z' map to themselves.
    """
    keys = [normalize_label(c) for c in channels]
    lookup = {k: i for i, k in enumerate(keys)}
    out: list[int] = []
    for i, key in enumerate(keys):
        match = re.fullmatch(r"([a-z]+)(\d+)", key)
        if match is None:
            out.append(i)
            continue
        number = int(match.group(2))
        partner = f"{match.group(1)}{number + 1 if number % 2 else number - 1}"
        if partner not in lookup:
            return None
        out.append(lookup[partner])
    return out

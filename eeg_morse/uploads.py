"""Validate and stage uploaded recording files for decoding.

An eego recording is a `.cnt` plus `.evt` (events) and `.seg` (pause/resume
segments) that the loader finds by stem, so all three must land in the same
directory under the same stem. Everything here treats names as untrusted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable

RECORDING_EXT = {".cnt", ".edf", ".bdf", ".fif", ".xdf", ".npz", ".csv"}
SIDECAR_EXT = {".evt", ".seg"}  # only meaningful next to a .cnt
# Session notes: what was said/done during the recording, one line per item,
# written by the team. Shown as notes, never treated as decoded output.
NOTES_EXT = ".txt"
MAX_NOTES_BYTES = 10_000
MAX_NOTES_LINES = 20
MAX_NOTE_CHARS = 200
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_FILES = 4
MAX_STEM_CHARS = 100
MAX_SUFFIX_CHARS = 10
CHUNK = 1024 * 1024
_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


class UploadError(ValueError):
    """A problem with the uploaded files that the user can fix (HTTP 400/413)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def safe_name(name: str | None) -> str:
    """Basename only, no path parts, no control or shell characters."""
    base = Path((name or "").replace("\\", "/")).name.strip()
    base = _SAFE.sub("_", base).lstrip(".")
    if not base or base in {".", ".."}:
        raise UploadError("A file has no usable name.")
    stem, suffix = Path(base).stem, Path(base).suffix
    return stem[:MAX_STEM_CHARS] + suffix[:MAX_SUFFIX_CHARS]  # keep the extension


@dataclass(frozen=True)
class Incoming:
    name: str
    stream: BinaryIO


def plan(names: list[str]) -> str:
    """Check the set of names and return the primary recording's name."""
    if not names:
        raise UploadError("No files received. Drop a recording (.cnt with its .evt/.seg, .edf, .npz ...).")
    if len(names) > MAX_FILES:
        raise UploadError(f"Upload one recording at a time (at most {MAX_FILES} files: "
                          ".cnt + .evt + .seg + notes .txt).")
    exts = [Path(n).suffix.lower() for n in names]
    unknown = sorted({n for n, e in zip(names, exts) if e not in RECORDING_EXT | SIDECAR_EXT | {NOTES_EXT}})
    if unknown:
        raise UploadError(f"Unsupported file type: {', '.join(unknown)}. "
                          f"Use {', '.join(sorted(RECORDING_EXT))} (+ .evt/.seg next to a .cnt).")
    primary = [n for n, e in zip(names, exts) if e in RECORDING_EXT]
    if len(primary) != 1:
        raise UploadError("Upload exactly one recording file per request "
                          f"(got {len(primary)}: {', '.join(primary) or 'none'}).")
    main = primary[0]
    stem, main_ext = Path(main).stem.lower(), Path(main).suffix.lower()
    for n, e in zip(names, exts):
        if e == NOTES_EXT and Path(n).stem.lower() != stem:
            raise UploadError(f"{n} does not match {main}: session notes must share the recording's name.")
        if e in SIDECAR_EXT:
            if main_ext != ".cnt":
                raise UploadError(f"{n} only belongs next to an eego .cnt file.")
            if Path(n).stem.lower() != stem:
                raise UploadError(f"{n} does not match {main}: .evt/.seg must share the .cnt's name.")
    if len(set(n.lower() for n in names)) != len(names):
        raise UploadError("The same file was uploaded twice.")
    return main


def stage(files: Iterable[Incoming], dest: Path, max_bytes: int = MAX_TOTAL_BYTES) -> Path:
    """Write the files into `dest` (stems aligned to the .cnt) and return the recording path."""
    items = [(safe_name(f.name), f.stream) for f in files]
    main = plan([n for n, _ in items])
    stem = Path(main).stem
    total = 0
    for name, stream in items:
        target = dest / (name if name == main else stem + Path(name).suffix.lower())
        with target.open("wb") as out:
            while chunk := stream.read(CHUNK):
                total += len(chunk)
                if total > max_bytes:
                    raise UploadError(f"Upload is larger than {max_bytes // (1024 * 1024)} MB.", 413)
                out.write(chunk)
        if target.stat().st_size == 0:
            raise UploadError(f"{name} is empty.")
    if Path(main).suffix.lower() == ".npz":
        check_npz(dest / main)
    notes = dest / (stem + NOTES_EXT)
    if notes.exists() and notes.stat().st_size > MAX_NOTES_BYTES:
        raise UploadError(f"Session notes are larger than {MAX_NOTES_BYTES // 1000} kB.")
    return dest / main


# .npz is a zip: a few MB can declare gigabytes of arrays (decompression bomb).
MAX_NPZ_UNPACKED_BYTES = 2 * 1024 * 1024 * 1024
MAX_NPZ_RATIO = 200


def check_npz(path: Path) -> None:
    """Reject .npz archives whose declared unpacked size or compression ratio is absurd."""
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as e:
        raise UploadError(f"{path.name} is not a valid .npz file.") from e
    unpacked = sum(i.file_size for i in infos)
    packed = max(1, sum(i.compress_size for i in infos))
    if unpacked > MAX_NPZ_UNPACKED_BYTES or unpacked / packed > MAX_NPZ_RATIO:
        raise UploadError(f"{path.name} unpacks to {unpacked // (1024 * 1024)} MB; too large to decode.", 413)


def read_notes(recording: Path) -> list[str]:
    """Session notes next to a staged recording: non-empty lines, trimmed and capped."""
    path = recording.with_suffix(NOTES_EXT)
    if not path.exists():
        return []
    lines = (line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines())
    return [line[:MAX_NOTE_CHARS] for line in lines if line][:MAX_NOTES_LINES]

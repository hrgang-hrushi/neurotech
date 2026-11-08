"""Cue a participant and capture labelled EEG for the rotation-1 dataset.

Reading LSL ourselves while showing the cues gives exact labels, and the data arrives in
the same format the live demo will see. That matters here because eego's GUI annotations
are documented as not meant for precise timing, and the EE-511 has only 2 trigger bits.

If LSL isn't available during the rotation, use --no-lsl. It shows the same cues and
writes a cue log. Press an eego annotation key the moment the screen says GO; the
calibrate step uses the first annotation in the export as time zero for that log.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from pathlib import Path

import numpy as np
import pylsl

from .streaming import EegInlet

# Every cue shares one background. A class-colored screen changes what the participant sees
# in exact step with the label, so a decoder could score well on that with no motor signal.
CUE_BG = "#20242c"
REAL_PROMPTS = {
    "rest": ("REST", "stay relaxed, don't move"),
    "left": ("LEFT HAND", "open and close, about once a second"),
    "right": ("RIGHT HAND", "open and close, about once a second"),
    "feet": ("BOTH FEET", "tap your toes, about once a second"),
    "both": ("BOTH HANDS", "open and close, about once a second"),
}
IMAGINED_PROMPTS = {
    "rest": ("REST", "stay relaxed, don't imagine anything"),
    "left": ("LEFT HAND", "imagine opening and closing it, keep it still"),
    "right": ("RIGHT HAND", "imagine opening and closing it, keep it still"),
    "feet": ("BOTH FEET", "imagine tapping your toes, keep them still"),
    "both": ("BOTH HANDS", "imagine opening and closing them, keep them still"),
}
SNAPSHOT_EVERY_S = 30.0
BASELINE_S = 60.0
CUE_S = 4.0
GAP_S = (2.0, 3.0)  # jittered so the participant can't anticipate the next cue
BLOCK_BREAK_S = 15.0


def build_schedule(classes: list[str], per_class: int, blocks: int, seed: int,
                   baseline_s: float = BASELINE_S) -> list[dict]:
    """Balanced shuffled cues with onsets measured from the end of the countdown."""
    rng = random.Random(seed)
    cues = [{"onset_s": 0.0, "duration_s": baseline_s, "label": "baseline"}]
    clock = baseline_s + 2.0
    per_block = [per_class // blocks + (1 if b < per_class % blocks else 0) for b in range(blocks)]
    for block, count in enumerate(per_block):
        order = classes * count
        rng.shuffle(order)
        for label in order:
            cues.append({"onset_s": round(clock, 3), "duration_s": CUE_S, "label": label})
            clock += CUE_S + rng.uniform(*GAP_S)
        if block < blocks - 1:
            cues.append({"onset_s": round(clock, 3), "duration_s": BLOCK_BREAK_S, "label": "break"})
            clock += BLOCK_BREAK_S
    return cues


def prompts_for(mode: str) -> dict[str, tuple[str, str]]:
    """The cue wording for a recording mode."""
    prompts = {"imagined": IMAGINED_PROMPTS, "real": REAL_PROMPTS}
    if mode not in prompts:
        raise ValueError(f"Unknown recording mode {mode!r}. Use imagined or real.")
    return prompts[mode]


def recording_path(out: Path, use_lsl: bool) -> Path:
    return out.with_suffix(".npz" if use_lsl else ".json")


def snapshot_path(out: Path) -> Path:
    # with_name, not with_suffix: a second suffix would replace ".snapshot".
    return out.with_name(f"{out.stem}.snapshot.npz")


def write_recording(path: Path, eeg: np.ndarray, stamps: np.ndarray, sfreq: float,
                    channels: list[str], cues: list[dict], lsl_t0: float | None,
                    movement: str, units: list[str | None] | None = None) -> Path:
    """Write a recording atomically, so a crash mid-write can't leave a broken file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Cue times are relative to the capture's first sample, so a loader can index by them.
    offset = (lsl_t0 or stamps[0]) - stamps[0]
    temporary = path.with_name(f"{path.name}.tmp")
    data = {
        "eeg": eeg,
        "timestamps": stamps,
        "sfreq": sfreq,
        "channels": np.array(channels),
        "cue_onset_s": np.array([c["onset_s"] + offset for c in cues]),
        "cue_duration_s": np.array([c["duration_s"] for c in cues]),
        "cue_label": np.array([c["label"] for c in cues]),
        "mode": np.array(movement),
    }
    if units is not None:
        data["units"] = np.array([unit or "" for unit in units])
    with open(temporary, "wb") as file:
        np.savez(file, **data)
    os.replace(temporary, path)
    return path


class Capture(threading.Thread):
    """Pull every raw sample on a background thread until stopped.

    Snapshots are written here, not on the Tk thread, because a large write would delay cues.
    """

    def __init__(self, stream: str | None, inlet=None, snapshot: Path | None = None,
                 snapshot_every_s: float = SNAPSHOT_EVERY_S):
        super().__init__(daemon=True)
        self.inlet = inlet or EegInlet(channels=None, name=stream)
        self.chunks, self.stamps = [], []
        self.running = True
        self.snapshot, self.snapshot_every_s = snapshot, snapshot_every_s
        self.session: tuple[list[dict], float, str] | None = None
        self.last_snapshot = 0.0
        self.error: Exception | None = None
        self.snapshot_error: Exception | None = None

    def set_session(self, cues: list[dict], lsl_t0: float, movement: str) -> None:
        """Start snapshots. Before GO there are no cue times to label the data with."""
        self.session = (cues, lsl_t0, movement)
        self.last_snapshot = time.monotonic()

    def drain(self) -> tuple[np.ndarray, np.ndarray] | None:
        """A copy of everything so far. Safe to call while the thread is still appending."""
        count = min(len(self.chunks), len(self.stamps))
        if count == 0:
            return None
        return np.concatenate(self.chunks[:count]), np.concatenate(self.stamps[:count])

    def write_snapshot(self) -> None:
        drained = self.drain()
        if drained is None or self.session is None or self.snapshot is None:
            return
        cues, lsl_t0, movement = self.session
        write_recording(self.snapshot, drained[0], drained[1], self.inlet.sfreq,
                        self.inlet.channels, cues, lsl_t0, movement,
                        units=getattr(self.inlet, "units", None))

    def run(self) -> None:
        try:
            while self.running:
                samples, stamps = self.inlet.pull(timeout=0.2)
                if len(stamps):
                    self.chunks.append(samples)
                    self.stamps.append(stamps)
                due = time.monotonic() - self.last_snapshot >= self.snapshot_every_s
                if self.session is not None and due:
                    self.last_snapshot = time.monotonic()
                    self._try_snapshot()
        except Exception as error:  # a dead thread must not look like a quiet stream
            self.error = error
            print(f"WARNING: capture stopped, stop the session: {error}")

    def _try_snapshot(self) -> None:
        """A full disk must not stop sampling: keep recording, and tell the operator once."""
        try:
            self.write_snapshot()
        except Exception as error:
            if self.snapshot_error is None:
                print(f"WARNING: crash snapshot failed, recording continues: {error}")
            self.snapshot_error = error


def run_session(out: Path, classes: list[str], per_class: int, blocks: int, seed: int,
                use_lsl: bool, stream: str | None, baseline_s: float = BASELINE_S,
                fullscreen: bool = True, autostart: bool = False,
                movement: str = "imagined") -> None:
    import tkinter as tk

    prompts = prompts_for(movement)
    target = recording_path(out, use_lsl)
    if target.exists():
        raise FileExistsError(f"{target} already exists, so recording would destroy it. "
                              "Move it, or pass a different --out.")
    if use_lsl and snapshot_path(out).exists():
        raise FileExistsError(f"{snapshot_path(out)} is left from a run that didn't finish. It "
                              "holds real data, so move it before recording again.")
    cues = build_schedule(classes, per_class, blocks, seed, baseline_s)
    minutes = (cues[-1]["onset_s"] + CUE_S) / 60
    print(f"{len(cues)} cues, about {minutes:.1f} minutes including the baseline.")

    capture = Capture(stream, snapshot=snapshot_path(out)) if use_lsl else None
    if capture:
        capture.start()

    root = tk.Tk()
    root.title("eegmove cues")
    if fullscreen:
        root.attributes("-fullscreen", True)
    else:
        root.geometry("640x360+40+40")
    title = tk.Label(root, font=("Helvetica", 96, "bold"), fg="white", bg=CUE_BG)
    detail = tk.Label(root, font=("Helvetica", 36), fg="white", bg=CUE_BG)
    title.pack(expand=True, fill="both")
    detail.pack(expand=True, fill="both")

    def show(big: str, small: str) -> None:
        root.configure(bg=CUE_BG)
        title.configure(text=big, bg=CUE_BG)
        detail.configure(text=small, bg=CUE_BG)

    state = {"t0": None, "lsl_t0": None, "index": 0, "saved": False}

    def save_once() -> None:
        if state["saved"]:
            return
        state["saved"] = True
        try:
            save(out, cues[:state["index"]], capture, state["lsl_t0"], use_lsl, movement)
        except Exception as error:  # the session is over: report it, and keep the snapshot
            print(f"ERROR while saving: {error}")

    def finish(_event=None) -> None:
        if not state["saved"]:
            show("DONE", "saving ...")
            root.update()
        save_once()
        root.destroy()

    def next_cue() -> None:
        index = state["index"]
        if index >= len(cues):
            # The last cue has only just appeared, so let it play out before saving.
            root.after(int((cues[-1]["duration_s"] + 0.5) * 1000), finish)
            return
        cue = cues[index]
        delay = (state["t0"] + cue["onset_s"] - time.perf_counter()) * 1000
        root.after(max(0, int(delay)), lambda: present(cue))

    def present(cue: dict) -> None:
        state["index"] += 1
        label = cue["label"]
        if label == "baseline":
            hint = "eyes open, look at the screen, stay still"
            show("RELAX", hint if use_lsl else "operator: press the eego annotation key NOW")
        elif label == "break":
            show("BREAK", "move around, blink, get comfortable")
        else:
            show(*prompts[label])
            root.after(int(cue["duration_s"] * 1000), lambda: show("+", ""))
        next_cue()

    def countdown(left: int) -> None:
        if left > 0:
            show(str(left), "starting ...")
            root.after(1000, lambda: countdown(left - 1))
            return
        state["t0"] = time.perf_counter()
        state["lsl_t0"] = pylsl.local_clock()
        if capture:
            capture.set_session(cues, state["lsl_t0"], movement)
        if not use_lsl:
            print("GO: press the eego annotation key now.")
        next_cue()

    def begin(_event=None) -> None:
        root.unbind("<space>")
        countdown(3)

    root.bind("<space>", begin)
    if autostart:
        root.after(500, begin)
    root.bind("<Escape>", finish)
    # Without these, the close button and Cmd-Q leave mainloop with no file and no error.
    root.protocol("WM_DELETE_WINDOW", finish)
    try:
        root.createcommand("tk::mac::Quit", finish)
    except tk.TclError:
        pass
    show("READY", "operator: press SPACE to start, ESC to stop early")
    try:
        root.mainloop()
    finally:
        save_once()  # reached by Ctrl-C, which skips every handler above


def save(out: Path, cues: list[dict], capture: Capture | None, lsl_t0: float | None,
         use_lsl: bool, movement: str = "imagined") -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if capture is not None:
        capture.running = False
        capture.join(timeout=2)
    if lsl_t0 is None:
        print("Stopped before GO, so there are no cues to save.")
        return
    if use_lsl and capture is not None:
        drained = capture.drain()
        if drained is None:
            raise RuntimeError("No samples arrived, so there is nothing to save.")
        eeg, stamps = drained
        expected = (stamps[-1] - stamps[0]) * capture.inlet.sfreq + 1
        if len(eeg) < 0.99 * expected:
            print(f"WARNING: got {len(eeg)} of about {expected:.0f} samples, so the network "
                  "dropped data. Labels stay correct, but check the eego backup.")
        if capture.error:
            print(f"WARNING: capture stopped early: {capture.error}")
        path = recording_path(out, True)
        write_recording(path, eeg, stamps, capture.inlet.sfreq, capture.inlet.channels, cues,
                        lsl_t0, movement, units=getattr(capture.inlet, "units", None))
        snapshot_path(out).unlink(missing_ok=True)
        print(f"Saved {path}: {len(eeg)} samples, {eeg.shape[1]} channels")
    else:
        path = recording_path(out, False)
        path.write_text(json.dumps({"mode": movement, "cues": cues}, indent=1))
        print(f"Saved cue log {path}. Pair it with the eego export in `eegmove calibrate`.")

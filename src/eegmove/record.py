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
import random
import threading
import time
from pathlib import Path

import numpy as np
import pylsl

from .streaming import EegInlet

PROMPTS = {
    "rest": ("REST", "stay relaxed, don't move", "#30343f"),
    "left": ("LEFT HAND", "open and close, about once a second", "#1f6feb"),
    "right": ("RIGHT HAND", "open and close, about once a second", "#c0392b"),
    "feet": ("BOTH FEET", "tap your toes, about once a second", "#1e8449"),
    "both": ("BOTH HANDS", "open and close, about once a second", "#8e44ad"),
}
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


class Capture(threading.Thread):
    """Pull every raw sample on a background thread until stopped."""

    def __init__(self, stream: str | None):
        super().__init__(daemon=True)
        self.inlet = EegInlet(channels=None, name=stream)
        self.chunks, self.stamps = [], []
        self.running = True

    def run(self) -> None:
        while self.running:
            samples, stamps = self.inlet.pull(timeout=0.2)
            if len(stamps):
                self.chunks.append(samples)
                self.stamps.append(stamps)


def run_session(out: Path, classes: list[str], per_class: int, blocks: int, seed: int,
                use_lsl: bool, stream: str | None, baseline_s: float = BASELINE_S,
                fullscreen: bool = True, autostart: bool = False) -> None:
    import tkinter as tk

    cues = build_schedule(classes, per_class, blocks, seed, baseline_s)
    minutes = (cues[-1]["onset_s"] + CUE_S) / 60
    print(f"{len(cues)} cues, about {minutes:.1f} minutes including the baseline.")

    capture = Capture(stream) if use_lsl else None
    if capture:
        capture.start()

    root = tk.Tk()
    root.title("eegmove cues")
    if fullscreen:
        root.attributes("-fullscreen", True)
    else:
        root.geometry("640x360+40+40")
    title = tk.Label(root, font=("Helvetica", 96, "bold"), fg="white", bg="black")
    detail = tk.Label(root, font=("Helvetica", 36), fg="white", bg="black")
    title.pack(expand=True, fill="both")
    detail.pack(expand=True, fill="both")

    def show(big: str, small: str, color: str) -> None:
        root.configure(bg=color)
        title.configure(text=big, bg=color)
        detail.configure(text=small, bg=color)

    state = {"t0": None, "lsl_t0": None, "index": 0}

    def finish() -> None:
        show("DONE", "saving ...", "black")
        root.update()
        save(out, cues, capture, state["lsl_t0"], use_lsl)
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
            show("RELAX", hint if use_lsl else "operator: press the eego annotation key NOW", "#30343f")
        elif label == "break":
            show("BREAK", "move around, blink, get comfortable", "black")
        else:
            big, small, color = PROMPTS[label]
            show(big, small, color)
            root.after(int(cue["duration_s"] * 1000), lambda: show("+", "", "black"))
        next_cue()

    def countdown(left: int) -> None:
        if left > 0:
            show(str(left), "starting ...", "black")
            root.after(1000, lambda: countdown(left - 1))
            return
        state["t0"] = time.perf_counter()
        state["lsl_t0"] = pylsl.local_clock()
        if not use_lsl:
            print("GO: press the eego annotation key now.")
        next_cue()

    def begin(_event=None) -> None:
        root.unbind("<space>")
        countdown(3)

    root.bind("<space>", begin)
    if autostart:
        root.after(500, begin)
    root.bind("<Escape>", lambda _event: finish())
    show("READY", "operator: press SPACE to start, ESC to stop early", "black")
    root.mainloop()


def save(out: Path, cues: list[dict], capture: Capture | None, lsl_t0: float | None,
         use_lsl: bool) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if use_lsl and capture is not None:
        capture.running = False
        capture.join(timeout=2)
        if not capture.chunks:
            raise RuntimeError("No samples arrived, so there is nothing to save.")
        eeg = np.concatenate(capture.chunks)
        stamps = np.concatenate(capture.stamps)
        expected = (stamps[-1] - stamps[0]) * capture.inlet.sfreq + 1
        if len(eeg) < 0.99 * expected:
            print(f"WARNING: got {len(eeg)} of about {expected:.0f} samples, so the network "
                  "dropped data. Labels stay correct, but check the eego backup.")
        # Cue times are relative to the capture's first sample, so a loader can index by them.
        offset = (lsl_t0 or stamps[0]) - stamps[0]
        np.savez(out.with_suffix(".npz"), eeg=eeg, timestamps=stamps,
                 sfreq=capture.inlet.sfreq, channels=np.array(capture.inlet.channels),
                 cue_onset_s=np.array([c["onset_s"] + offset for c in cues]),
                 cue_duration_s=np.array([c["duration_s"] for c in cues]),
                 cue_label=np.array([c["label"] for c in cues]))
        print(f"Saved {out.with_suffix('.npz')}: {len(eeg)} samples, {eeg.shape[1]} channels")
    else:
        path = out.with_suffix(".json")
        path.write_text(json.dumps({"cues": cues}, indent=1))
        print(f"Saved cue log {path}. Pair it with the eego export in `eegmove calibrate`.")

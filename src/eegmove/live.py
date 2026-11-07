"""The real-time loop: LSL in, smoothed decisions out as JSON over UDP.

Any app, in any language, can listen on the UDP port, so the decoder and the app can be
built separately. Each message looks like:
    {"t": 12.5, "probs": {"rest": 0.7, ...}, "state": "rest", "event": null, "latency_ms": 41.2}
`state` is the current smoothed guess. `event` is non-null once per deliberate movement.
"""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path

import joblib
import numpy as np
import pylsl

from .models import SessionModel
from .preprocess import StreamPreprocessor, apply_whitening, whitening_matrix
from .streaming import EegInlet


class RingBuffer:
    def __init__(self, n_channels: int, n_times: int):
        self.data = np.zeros((n_times, n_channels))
        self.filled = 0

    def push(self, samples: np.ndarray) -> None:
        samples = samples[-len(self.data):]
        n = len(samples)
        if n:
            self.data = np.roll(self.data, -n, axis=0)
            self.data[-n:] = samples
            self.filled = min(len(self.data), self.filled + n)

    @property
    def ready(self) -> bool:
        return self.filled == len(self.data)

    def window(self) -> np.ndarray:
        return self.data.T.copy()


class Debouncer:
    """Turn noisy per-window probabilities into stable decisions.

    Probabilities are smoothed, a class must stay on top for `dwell` updates, and a
    refractory period then stops one movement firing twice. This trades a little latency
    for an app that doesn't flicker, which matters more in a live demo.

    A new symbol can only fire from idle, so a rebound straight after a movement can't fire
    as the opposite symbol. `rest_dwell` is how long rest must hold to re-arm, and a low
    confidence dip pauses that count. `release_after` frees a state that nothing confirms,
    so one uncertain stretch can't block every later symbol.
    """

    def __init__(self, classes: list[str], alpha: float = 0.4, threshold: float = 0.6,
                 dwell: int = 3, refractory: int = 6, idle: str = "rest",
                 rest_dwell: int | None = None, release_after: int | None = None):
        self.classes, self.alpha, self.threshold = classes, alpha, threshold
        self.dwell, self.refractory, self.idle = dwell, refractory, idle
        self.rest_dwell = dwell if rest_dwell is None else rest_dwell
        self.release_after = release_after
        self.smooth = np.full(len(classes), 1 / len(classes))
        self.candidate, self.streak, self.cooldown, self.unconfirmed = None, 0, 0, 0
        self.state = idle if idle in classes else classes[0]
        self.rest_top = False  # rest leads the smoothed probabilities, however narrowly

    def update(self, probs: np.ndarray) -> tuple[str, str | None]:
        self.smooth = self.alpha * probs + (1 - self.alpha) * self.smooth
        top = self.classes[int(self.smooth.argmax())]
        confident = self.smooth.max() >= self.threshold
        self.rest_top = top == self.idle
        self.cooldown = max(0, self.cooldown - 1)
        if confident:
            self.streak = self.streak + 1 if top == self.candidate else 1
            self.candidate = top
        elif self.candidate != self.idle:
            self.candidate, self.streak = None, 0

        event = None
        if self.candidate == self.idle:
            if self.streak >= self.rest_dwell:
                self.state = self.idle
        elif self.candidate is not None and self.streak >= self.dwell:
            if self.state == self.idle and self.cooldown == 0:
                self.state = event = self.candidate
                self.cooldown = self.refractory

        if self.state == self.idle:
            self.unconfirmed = 0
        else:
            self.unconfirmed = 0 if confident and top == self.state else self.unconfirmed + 1
            if self.release_after is not None and self.unconfirmed >= self.release_after:
                self.state, self.candidate, self.streak = self.idle, None, 0
                self.unconfirmed = 0
        return self.state, event

    def hold(self) -> None:
        """Skip an update because its window was rejected: nothing may fire from it."""
        self.candidate, self.streak, self.rest_top = None, 0, False


def run_live(model_path: Path, host: str = "127.0.0.1", port: int = 9999, stream: str | None = None,
             baseline_s: float = 60.0, step_s: float = 0.25, duration_s: float | None = None,
             threshold: float = 0.6, quiet: bool = False) -> list[dict]:
    model: SessionModel = joblib.load(model_path)
    cfg = model.cfg
    inlet = EegInlet(model.channels, name=stream)
    pre = StreamPreprocessor(inlet.sfreq, len(model.channels), cfg)
    ring = RingBuffer(len(model.channels), cfg.n_times)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    debounce = Debouncer(model.classes, threshold=threshold)

    # Sessions drift: the cap goes back on slightly differently and impedances change. A
    # short resting baseline refreshes the alignment with no labels at all.
    whitening = model.whitening
    if baseline_s > 0:
        print(f"Baseline: sit still and relax for {baseline_s:.0f}s ...")
        collected = []
        stop = time.time() + baseline_s
        while time.time() < stop:
            samples, _ = inlet.pull()
            ring.push(pre.process(samples))
            if ring.ready and (not collected or ring_step(collected, ring)):
                collected.append(ring.window())
        if len(collected) >= 5:
            whitening = whitening_matrix(np.asarray(collected))
            print(f"Baseline done: alignment refreshed from {len(collected)} windows.")
        else:
            print("WARNING: baseline too short, keeping the alignment from calibration.")

    print(f"Decoding. Sending JSON to udp://{host}:{port}. Ctrl-C stops.")
    step = max(1, int(round(step_s * cfg.sfreq)))
    pending, log = 0, []
    start = time.time()
    try:
        while duration_s is None or time.time() - start < duration_s:
            samples, stamps = inlet.pull(timeout=0.05)
            filtered = pre.process(samples)
            ring.push(filtered)
            pending += len(filtered)
            if not ring.ready or pending < step:
                continue
            pending = 0
            probs = model.predict_proba(apply_whitening(ring.window()[None], whitening))[0]
            state, event = debounce.update(probs)
            latency = (pylsl.local_clock() - stamps[-1]) * 1000 if len(stamps) else float("nan")
            message = {"t": round(time.time() - start, 3),
                       "lsl_time": float(stamps[-1]) if len(stamps) else None,
                       "probs": {c: round(float(p), 3) for c, p in zip(model.classes, probs)},
                       "state": state, "event": event, "latency_ms": round(latency, 1)}
            sock.sendto(json.dumps(message).encode(), (host, port))
            log.append(message)
            if not quiet:
                bars = " ".join(f"{c}:{p:4.2f}" for c, p in zip(model.classes, probs))
                print(f"{bars} | {state:>6}{' EVENT ' + event if event else ''} | "
                      f"{latency:5.0f} ms")
    except KeyboardInterrupt:
        pass
    return log


def ring_step(collected: list[np.ndarray], ring: RingBuffer) -> bool:
    """During baseline, keep one window per half-overlap rather than one per pull."""
    size = collected[-1].shape[1]
    return not np.array_equal(collected[-1][:, size // 2:], ring.window()[:, :size - size // 2])

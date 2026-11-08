"""The real-time loop: LSL in, smoothed decisions out as JSON over UDP.

Any app, in any language, can listen on the UDP port, so the decoder and the app can be
built separately. Each message looks like:
    {"t": 12.5, "probs": {"rest": 0.7, ...}, "state": "rest", "event": null, "latency_ms": 41.2}
`state` is the current smoothed guess. `event` is non-null once per deliberate movement.

Later fields: `run` and `seq` identify and order messages, `ok` is false on a rejected window
(with `reason`), `rest` is true only on confident rest, `source` says live EEG or replay,
`movement` and `model` name what is decoding, and `snr_db` and `warning` report signal strength.
"""

from __future__ import annotations

import json
import socket
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import joblib
import numpy as np
import pylsl

from .models import SessionModel
from .preprocess import StreamPreprocessor, apply_whitening, whitening_matrix
from .quality import SnrMonitor, WindowGate
from .streaming import EegInlet
from .verdict import model_sha1

# At 0.25 s steps: 3 s between symbols, 2 s of rest to re-arm (one window length, so the
# last movement has left the window), and 4 s to free a state nothing confirms.
MORSE_DEBOUNCE = {"refractory": 12, "rest_dwell": 8, "release_after": 16}
MIN_BASELINE_WINDOWS = 5


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
        self.rest_sure = False  # rest is the confident top class, not merely where state fell

    def update(self, probs: np.ndarray) -> tuple[str, str | None]:
        self.smooth = self.alpha * probs + (1 - self.alpha) * self.smooth
        top = self.classes[int(self.smooth.argmax())]
        confident = self.smooth.max() >= self.threshold
        self.rest_sure = confident and top == self.idle
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
            # A confident symbol still confirms a decoder at work, even the opposite one, so
            # a rebound waits for rest. Only real doubt counts toward freeing the state.
            self.unconfirmed = 0 if confident and top != self.idle else self.unconfirmed + 1
            if self.release_after is not None and self.unconfirmed >= self.release_after:
                self.state, self.candidate, self.streak = self.idle, None, 0
                self.unconfirmed = 0
        return self.state, event

    def hold(self) -> None:
        """Skip an update because its window was rejected: nothing may fire from it."""
        self.candidate, self.streak, self.rest_sure = None, 0, False


class WindowDecider:
    """One window in, one decision out. No LSL or sockets, so it can be tested on its own."""

    def __init__(self, model: SessionModel, whitening: np.ndarray, gate: WindowGate | None,
                 debounce: Debouncer, monitor: SnrMonitor | None):
        self.model, self.whitening, self.gate = model, whitening, gate
        self.debounce, self.monitor = debounce, monitor

    def _quality(self, window: np.ndarray, clean: bool) -> tuple[bool, str | None]:
        if self.gate is None:
            return False, "no_baseline"  # nothing to judge the signal against, so fail closed
        if not clean:
            return False, "nonfinite"
        return self.gate.check(window)

    def step(self, window: np.ndarray, clean: bool = True) -> dict:
        ok, reason = self._quality(window, clean)
        if not ok:
            self.debounce.hold()
            return {"ok": False, "reason": reason, "probs": None, "state": self.debounce.state,
                    "event": None, "rest": False, "snr_db": None, "warning": None}
        probs = self.model.predict_proba(apply_whitening(window[None], self.whitening))[0]
        state, event = self.debounce.update(probs)
        snr, warning = self.monitor.update(window, state) if self.monitor else (None, None)
        return {"ok": True, "reason": None,
                "probs": {c: round(float(p), 3) for c, p in zip(self.model.classes, probs)},
                "state": state, "event": event,
                "rest": state == self.debounce.idle and self.debounce.rest_sure,
                "snr_db": None if snr is None else round(snr, 2), "warning": warning}


class LiveSession:
    """A running decoder: stream, filters, baseline, and one message per step."""

    def __init__(self, model_path: Path, stream: str | None = None, threshold: float = 0.6,
                 step_s: float = 0.25, inlet=None, source: str | None = None):
        self.model: SessionModel = joblib.load(model_path)
        self.sha = model_sha1(model_path)
        self.cfg = self.model.cfg
        self.threshold, self.step_s = threshold, step_s
        self.inlet = inlet or EegInlet(self.model.channels, name=stream)
        if getattr(self.inlet, "is_replay", False) and source == "live":
            raise ValueError(f"{self.inlet.name!r} is a replay outlet. Omit --source or use --source replay.")
        inlet_source = getattr(self.inlet, "source", None) or ("replay" if getattr(self.inlet, "is_replay", False) else "live")
        self.source = source or inlet_source
        self.movement = self.model.movement
        self.pre = StreamPreprocessor(self.inlet.sfreq, len(self.model.channels), self.cfg)
        self.ring = RingBuffer(len(self.model.channels), self.cfg.n_times)
        self.run_id = uuid.uuid4().hex[:8]
        self.seq = -1
        self.dirty = 0  # model-rate samples until bad raw data has left the window
        self.pending = 0
        self.monitor: SnrMonitor | None = None
        debounce = Debouncer(self.model.classes, threshold=threshold, **MORSE_DEBOUNCE)
        self.decider = WindowDecider(self.model, self.model.whitening, None, debounce, None)

    def flush(self) -> None:
        flush = getattr(self.inlet, "flush", None)
        if flush:
            flush()

    def _take(self, timeout: float) -> tuple[np.ndarray, np.ndarray]:
        samples, stamps = self.inlet.pull(timeout=timeout)
        bad = len(samples) > 0 and not np.isfinite(samples).all()
        filtered = self.pre.process(samples)
        self.ring.push(filtered)
        self.pending += len(filtered)
        self.dirty = self.cfg.n_times if bad else max(0, self.dirty - len(filtered))
        return filtered, stamps

    def collect_baseline(self, seconds: float) -> bool:
        """Refresh alignment from rest, and set the reference the signal is judged against.

        Sessions drift: the cap goes back on slightly differently and impedances change, and
        this needs no labels. It returns False if there was no usable signal, and then every
        window is rejected rather than decoded blind.
        """
        windows, fresh = [], 0
        stride = self.cfg.n_times // 2
        stop = time.monotonic() + seconds
        while time.monotonic() < stop:
            filtered, _ = self._take(timeout=0.1)
            fresh += len(filtered)
            if self.ring.ready and fresh >= stride and self.dirty == 0:
                windows.append(self.ring.window())
                fresh = 0
        if len(windows) < MIN_BASELINE_WINDOWS:
            print(f"WARNING: only {len(windows)} baseline windows, so nothing will be decoded.")
            return False
        rest = np.asarray(windows)
        try:
            whitening = whitening_matrix(rest)
        except ValueError as error:
            print(f"WARNING: {error}")
            return False
        self.monitor = SnrMonitor(rest, self.model.channels, self.cfg.sfreq)
        self.decider.whitening = whitening
        self.decider.gate = WindowGate(rest)
        self.decider.monitor = self.monitor
        print(f"Baseline done: alignment refreshed from {len(windows)} windows.")
        return True

    def signal_strength(self) -> dict | None:
        if self.monitor is None:
            return None
        current = float(np.median(self.monitor.recent)) if self.monitor.recent else None
        return {"baseline_db": round(self.monitor.baseline_db, 2),
                "current_db": None if current is None else round(current, 2),
                "region": self.monitor.region}

    def decode(self) -> Iterator[dict | None]:
        """Yield a message per step, or None while waiting, so callers can keep time."""
        step = max(1, int(round(self.step_s * self.cfg.sfreq)))
        start = time.time()
        while True:
            _, stamps = self._take(timeout=0.05)
            if not self.ring.ready or self.pending < step:
                yield None
                continue
            self.pending %= step
            message = self.decider.step(self.ring.window(), clean=self.dirty == 0)
            self.seq += 1
            latency = (pylsl.local_clock() - stamps[-1]) * 1000 if len(stamps) else float("nan")
            yield {"run": self.run_id, "seq": self.seq, "step_s": self.step_s,
                   "t": round(time.time() - start, 3),
                   "lsl_time": float(stamps[-1]) if len(stamps) else None,
                   "source": self.source, "movement": self.movement, "model": self.sha,
                   "threshold": self.threshold, "latency_ms": round(latency, 1), **message}


def run_live(model_path: Path, host: str = "127.0.0.1", port: int = 9999, stream: str | None = None,
             baseline_s: float = 60.0, step_s: float = 0.25, duration_s: float | None = None,
             threshold: float = 0.6, quiet: bool = False, source: str | None = None) -> list[dict]:
    session = LiveSession(model_path, stream=stream, threshold=threshold, step_s=step_s, source=source)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"Model: {session.movement} movement, {session.sha}")
    print(f"Baseline: sit still and relax for {baseline_s:.0f}s ...")
    session.collect_baseline(baseline_s)

    print(f"Decoding. Sending JSON to udp://{host}:{port}. Ctrl-C stops.")
    log, shown = [], None
    start = time.time()
    try:
        for message in session.decode():
            if duration_s is not None and time.time() - start >= duration_s:
                break
            if message is None:
                continue
            sock.sendto(json.dumps(message).encode(), (host, port))
            log.append(message)
            if message["warning"] != shown:  # printed even when quiet, because it matters
                shown = message["warning"]
                if shown:
                    print(f"WARNING: {shown}")
            if not quiet:
                if message["ok"]:
                    bars = " ".join(f"{c}:{p:4.2f}" for c, p in message["probs"].items())
                else:
                    bars = f"rejected: {message['reason']}"
                event = f" EVENT {message['event']}" if message["event"] else ""
                print(f"{bars} | {message['state']:>6}{event} | {message['latency_ms']:5.0f} ms")
    except KeyboardInterrupt:
        pass
    return log

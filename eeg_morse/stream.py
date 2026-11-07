"""Live decoding from eego over Lab Streaming Layer (LSL).

In the eego software, tick "Enable LSL EEG streaming". This module finds that
stream, runs a causal version of the offline pipeline on each chunk and emits
dots, dashes, letters and spaces as they happen. Decoded letters can be sent
back as an LSL marker stream; with eego's network events enabled they are
written into the .cnt next to the EEG.

A session starts with a few seconds of rest to learn the baseline. With a
config from `calibrate`, decoding starts right away from its thresholds and
unit. Without one, the decoder waits until a warm-up shows clear on/off states
("locked"). In both cases thresholds are re-fit every few seconds on the last
90 s, and the unit is re-estimated from recent dots and dashes (unless --unit
fixes it), so slow drift in gain or sending speed is followed.
"""
from __future__ import annotations

import sys
import time
from collections import deque
from dataclasses import dataclass

import numpy as np
from scipy import signal as sps

from . import morse
from .config import PipelineConfig
from .detect import otsu
from .io import Recording, guess_type
from .signal import _TINY, design_filter, pick_indices
from .timing import estimate_unit, thresholds_for


@dataclass
class StreamEvent:
    kind: str  # ready | locked | element | letter | space | erase
    t: float  # seconds since stream start
    value: str = ""  # "." / "-", the letter, or ""
    code: str = ""  # letter code for kind == letter
    status: str = ""  # ok / split / nearest / unknown


class StreamingDecoder:
    """Causal EEG -> Morse -> text decoder. Feed it chunks with push()."""

    IDLE, ON, PENDING = 0, 1, 2

    def __init__(self, cfg: PipelineConfig, sfreq: float, ch_names: list[str],
                 ch_types: list[str] | None = None, rest_s: float = 6.0,
                 k_hi: float = 4.0, k_lo: float = 2.0, lock_sd: float = 3.0,
                 correct: bool = True, adapt_window_s: float = 90.0,
                 refit_every_s: float = 2.0, hold_until_locked: bool = True):
        self.cfg, self.sfreq, self.correct = cfg, float(sfreq), correct
        f, d, tm = cfg.feature, cfg.detect, cfg.timing
        ch_types = ch_types or [guess_type(c) for c in ch_names]
        self.idx, self.eeg_idx = pick_indices(ch_names, ch_types, f)
        self.channels = [ch_names[i] for i in self.idx]
        self.car = f.reference == "car" and len(self.eeg_idx) >= 3
        self.sos = design_filter(f.band, sfreq, f.line_freq)
        self.zi: np.ndarray | None = None
        self.w = max(1, int(round(f.smooth_s * sfreq)))
        self.tail = np.zeros((len(self.idx), 0))
        self.step = max(1, int(round(sfreq / f.env_rate)))
        self.n_seen = 0  # raw samples consumed

        self.fixed_unit = tm.unit_s is not None
        self.min_off = d.min_off_s
        self._set_unit(float(tm.unit_s or tm.default_unit_s), float(tm.bias_s))
        self.durations: deque[float] = deque(maxlen=40)

        # Adaptive thresholds: once the recent activation history shows two
        # clear states, re-fit Otsu + hysteresis on it, exactly like offline.
        self.recent: deque[float] = deque(maxlen=int(adapt_window_s * f.env_rate))
        self.refit_every = max(1, int(refit_every_s * f.env_rate))
        self.since_fit = 0
        self.locked = False
        self.rest_sd = np.nan
        self.calibrated = d.lo is not None and d.hi is not None and d.rest_level is not None
        self.hold_until_locked = hold_until_locked
        # decoding starts "armed" unless we will lock mid-message (warm-up mode)
        self.armed = self.calibrated or not hold_until_locked
        self.quiet_from: float | None = None
        self.base_buf: deque[float] | None = (
            deque(maxlen=max(3, int(f.baseline_s * f.env_rate)))
            if f.measure == "amplitude" else None
        )

        self.rest_s, self.settle_s = max(2.0, rest_s), min(1.0, rest_s / 3)
        self.k_hi, self.k_lo, self.lock_sd = k_hi, k_lo, lock_sd
        self.rest_vals: list[float] = []
        self.ready = False
        self.lo = self.hi = np.nan

        self.state = self.IDLE
        self.t_on = self.t_up = 0.0
        self.last_off: float | None = None
        self.code = ""
        self.letter_done = self.word_done = True
        self.words: list[list[str]] = []
        self.word_open = False
        self.history: list[tuple[float, float]] = []  # (t, activation) for plotting/debug

    # ---- public -------------------------------------------------------------
    @property
    def text(self) -> str:
        return " ".join("".join(w) for w in self.words if w)

    @property
    def pending_code(self) -> str:
        return self.code

    def push(self, chunk: np.ndarray) -> list[StreamEvent]:
        """chunk: (n_channels, n_samples) in the stream's channel order."""
        chunk = np.asarray(chunk, dtype=np.float64)
        if chunk.ndim != 2 or chunk.shape[1] == 0:
            return []
        x = chunk[self.idx]
        if self.car:
            x = x - chunk[self.eeg_idx].mean(axis=0, keepdims=True)
        if self.zi is None:
            zi0 = sps.sosfilt_zi(self.sos)
            self.zi = zi0[:, None, :] * x[:, :1][None, :, :]
        xf, self.zi = sps.sosfilt(self.sos, x, axis=1, zi=self.zi)
        q = xf if self.cfg.feature.measure == "amplitude" else xf**2
        ma = self._moving_average(q)
        # decimate on the global sample grid
        first = (-self.n_seen) % self.step
        keep = np.arange(first, ma.shape[1], self.step)
        times = (self.n_seen + keep) / self.sfreq
        self.n_seen += chunk.shape[1]
        if keep.size == 0:
            return []
        env = ma[:, keep]
        if self.cfg.feature.measure == "power":
            env = np.log10(np.maximum(env, _TINY))
        act = env.mean(axis=0)
        if self.cfg.feature.direction == "decrease":
            act = -act
        events: list[StreamEvent] = []
        for t, a in zip(times, act):
            events.extend(self._step(float(t), float(a)))
        return events

    def flush(self) -> list[StreamEvent]:
        """End of stream: close any open key-down and the last letter."""
        t = self.n_seen / self.sfreq
        events: list[StreamEvent] = []
        if self.state == self.ON:
            self.t_up = t
            self.state = self.PENDING
        if self.state == self.PENDING:
            events += self._finish_element()
        events += self._emit_letter(t)
        return events

    # ---- internals ----------------------------------------------------------
    def _set_unit(self, unit: float, bias: float) -> None:
        tm, d = self.cfg.timing, self.cfg.detect
        self.unit, self.bias = unit, bias
        self.min_on = max(d.min_on_s, tm.min_dot_ratio * unit)
        self.dash_thr, self.letter_gap, self.word_gap = thresholds_for(unit, bias, tm)

    def _refit(self, t: float) -> list[StreamEvent]:
        if len(self.recent) < 10 * self.cfg.feature.env_rate:
            return []
        thr, mu0, mu1, eta = otsu(np.fromiter(self.recent, float))
        # Otsu on pure noise still splits it (eta ~0.64, ~1.6 SD apart); demand more.
        if eta < 0.70 or (mu1 - mu0) < self.lock_sd * self.rest_sd:
            return []  # not enough real activity yet
        h = float(np.clip(self.cfg.detect.hysteresis, 0.0, 0.95))
        self.hi, self.lo = thr + h * (mu1 - thr), thr - h * (thr - mu0)
        if not self.locked:
            self.locked = True
            return [StreamEvent("locked", t, f"thresholds fit to your signal (separability {eta:.2f})")]
        return []

    def _moving_average(self, q: np.ndarray) -> np.ndarray:
        buf = np.concatenate([self.tail, q], axis=1)
        cs = np.concatenate([np.zeros((buf.shape[0], 1)), np.cumsum(buf, axis=1)], axis=1)
        L, m = buf.shape[1], q.shape[1]
        ends = np.arange(L - m + 1, L + 1)
        starts = np.maximum(ends - self.w, 0)
        out = (cs[:, ends] - cs[:, starts]) / (ends - starts)
        self.tail = buf[:, -(self.w - 1):] if self.w > 1 else buf[:, :0]
        return out

    def _calibrate_rest(self, t: float) -> list[StreamEvent]:
        v = np.asarray(self.rest_vals)
        mu, sd = float(v.mean()), float(v.std() + 1e-12)
        self.rest_sd = sd
        d = self.cfg.detect
        if self.calibrated:
            off = mu - d.rest_level  # session gain/impedance offset vs calibration
            self.lo, self.hi = d.lo + off, d.hi + off
            how = "calibrated thresholds, offset to today's rest level"
        else:
            self.lo, self.hi = mu + self.k_lo * sd, mu + self.k_hi * sd
            how = f"rest mean + {self.k_lo:g}/{self.k_hi:g} SD"
        self.ready = True
        if self.calibrated:
            self.locked = True
            return [StreamEvent("ready", t, how), StreamEvent("locked", t, "using calibration")]
        if self.hold_until_locked:
            how += "; send a few warm-up dashes until it locks"
        return [StreamEvent("ready", t, how)]

    def _step(self, t: float, a: float) -> list[StreamEvent]:
        if self.base_buf is not None:  # amplitude: subtract rolling-percentile baseline
            self.base_buf.append(a)
            a -= float(np.percentile(np.fromiter(self.base_buf, float),
                                     self.cfg.feature.baseline_pct))
        self.history.append((t, a))
        if not self.ready:
            if t >= self.settle_s:
                self.rest_vals.append(a)
            return self._calibrate_rest(t) if t >= self.rest_s else []
        ev: list[StreamEvent] = []
        self.recent.append(a)
        self.since_fit += 1
        if self.since_fit >= self.refit_every:
            self.since_fit = 0
            ev += self._refit(t)
        if not self.locked and self.hold_until_locked:
            return ev  # warm-up: learn thresholds, decode nothing yet
        lo, hi = self.lo, self.hi  # drift is absorbed by the windowed Otsu refit
        if not self.armed:
            # Just locked: a letter may be half-sent. Wait for a letter-gap of
            # quiet so decoding starts on a letter boundary, not mid-letter.
            if a <= lo:
                self.quiet_from = t if self.quiet_from is None else self.quiet_from
                self.armed = t - self.quiet_from >= self.letter_gap
            else:
                self.quiet_from = None
            return ev
        if self.state == self.IDLE:
            ev += self._check_gaps(t)
            if a > hi:
                self.state, self.t_on = self.ON, t
        elif self.state == self.ON:
            if a <= lo:
                self.state, self.t_up = self.PENDING, t
        elif self.state == self.PENDING:
            if a > hi:
                self.state = self.ON  # dropout shorter than min_off: same key-down
            elif t - self.t_up >= self.min_off:
                ev += self._finish_element()
                ev += self._check_gaps(t)
        return ev

    def _finish_element(self) -> list[StreamEvent]:
        self.state = self.IDLE
        dur = self.t_up - self.t_on
        if dur < self.min_on:
            return []  # blip
        if not self.fixed_unit:
            self.durations.append(dur)
            if len(self.durations) >= 6:
                unit, bias, src = estimate_unit(list(self.durations), self.cfg.timing)
                if src == "estimated":
                    self._set_unit(unit, bias)
        sym = "-" if dur > self.dash_thr else "."
        if self.last_off is not None:
            gap = self.t_on - self.last_off
            ev = []
            if gap > self.letter_gap and not self.letter_done:
                ev += self._emit_letter(self.t_on)
            if gap > self.word_gap and not self.word_done:
                ev += self._emit_space(self.t_on)
        else:
            ev = []
        self.code += sym
        self.last_off = self.t_up
        self.letter_done = self.word_done = False
        return ev + [StreamEvent("element", self.t_up, sym)]

    def _check_gaps(self, t: float) -> list[StreamEvent]:
        if self.last_off is None:
            return []
        ev = []
        gap = t - self.last_off
        if gap > self.letter_gap and not self.letter_done:
            ev += self._emit_letter(t)
        if gap > self.word_gap and not self.word_done:
            ev += self._emit_space(t)
        return ev

    def _emit_letter(self, t: float) -> list[StreamEvent]:
        self.letter_done = True
        if not self.code:
            return []
        code, self.code = self.code, ""
        if set(code) == {"."} and len(code) >= len(morse.ERROR_CODE):
            # ITU "error": cancel the word being sent, or the previous one if none
            if self.word_open and self.words and self.words[-1]:
                self.words[-1] = []
            else:
                while self.words and not self.words[-1]:
                    self.words.pop()
                if self.words:
                    self.words.pop()
                self.word_open = False
            return [StreamEvent("erase", t, "", code)]
        ch, status = morse.decode_code(code, self.correct)
        if not self.word_open:
            self.words.append([])
            self.word_open = True
        self.words[-1].append(ch)
        return [StreamEvent("letter", t, ch, code, status)]

    def _emit_space(self, t: float) -> list[StreamEvent]:
        self.word_done = True
        if self.word_open:
            self.word_open = False
            return [StreamEvent("space", t)]
        return []


# ---- sources ---------------------------------------------------------------
class ReplayInlet:
    """Plays a Recording back like an LSL inlet (for demos without the cap).

    speed=1.0 is real time; speed=None returns data as fast as it is pulled.
    """

    def __init__(self, rec: Recording, speed: float | None = 1.0, chunk_s: float = 0.1):
        self.rec, self.speed = rec, speed
        self.chunk = max(1, int(chunk_s * rec.sfreq))
        self.pos = 0
        self.t_start: float | None = None

    @property
    def done(self) -> bool:
        return self.pos >= self.rec.data.shape[1]

    def pull_chunk(self, timeout: float = 0.0, max_samples: int = 1024):
        n_total = self.rec.data.shape[1]
        if self.speed is None:
            end = min(n_total, self.pos + self.chunk)
        else:
            if self.t_start is None:
                self.t_start = time.monotonic()
            if timeout:
                time.sleep(min(timeout, self.chunk / self.rec.sfreq / self.speed))
            due = int((time.monotonic() - self.t_start) * self.rec.sfreq * self.speed)
            end = min(n_total, due)
        if end <= self.pos:
            return [], []
        block = self.rec.data[:, self.pos:end].T
        ts = list(np.arange(self.pos, end) / self.rec.sfreq)
        self.pos = end
        return block.tolist(), ts


def open_lsl_inlet(name: str | None = None, stype: str = "EEG", timeout: float = 15.0):
    """Find the eego LSL stream. Returns (inlet, sfreq, channel_names)."""
    try:
        import pylsl
    except ImportError as e:  # pragma: no cover - depends on environment
        raise ImportError("Live mode needs pylsl: pip install pylsl") from e
    prop, value = ("name", name) if name else ("type", stype)
    found = pylsl.resolve_byprop(prop, value, timeout=timeout)
    if not found:
        raise RuntimeError(
            f"No LSL stream with {prop}={value!r} found within {timeout:g}s. In eego, enable "
            "'LSL EEG streaming' and make sure both programs are on the same network."
        )
    inlet = pylsl.StreamInlet(found[0], max_buflen=60,
                              processing_flags=pylsl.proc_clocksync | pylsl.proc_dejitter)
    info = inlet.info()
    names, ch = [], info.desc().child("channels").child("channel")
    for _ in range(info.channel_count()):
        names.append(ch.child_value("label") or f"ch{len(names) + 1}")
        ch = ch.next_sibling()
    return inlet, float(info.nominal_srate()), names


def open_marker_outlet(name: str = "MorseDecoded"):  # pragma: no cover - needs pylsl
    import pylsl

    info = pylsl.StreamInfo(name, "Markers", 1, pylsl.IRREGULAR_RATE, "string", "eeg-morse")
    return pylsl.StreamOutlet(info)


class TerminalView:
    """Prints the decode as it happens: one line per letter, symbols inline."""

    def __init__(self, dec: StreamingDecoder, out=sys.stdout):
        self.dec, self.out = dec, out

    def __call__(self, e: StreamEvent) -> None:
        w = self.out.write
        if e.kind == "ready":
            w(f"[{e.t:6.1f}s] baseline learned ({e.value}); start sending.\n")
        elif e.kind == "locked":
            w(f"\n[{e.t:6.1f}s] locked: {e.value}\n")
        elif e.kind == "element":
            w("•" if e.value == "." else "—")
        elif e.kind == "letter":
            flag = "" if e.status == "ok" else f" ({e.status})"
            w(f"  {e.code} -> {e.value}{flag}    text: {self.dec.text}\n")
        elif e.kind == "space":
            w(f"[{e.t:6.1f}s] (word gap)\n")
        elif e.kind == "erase":
            w(f"  {e.code} -> ERASE    text: {self.dec.text}\n")
        self.out.flush()


def run_live(inlet, sfreq: float, ch_names: list[str], cfg: PipelineConfig,
             rest_s: float = 6.0, on_event=None, duration_s: float | None = None,
             marker_outlet=None, poll_s: float = 0.05) -> StreamingDecoder:
    dec = StreamingDecoder(cfg, sfreq, ch_names, rest_s=rest_s)
    on_event = on_event or TerminalView(dec)
    t_end = None if duration_s is None else time.monotonic() + duration_s

    def handle(events):
        for e in events:
            on_event(e)
            if marker_outlet is not None and e.kind in ("letter", "space", "erase"):
                marker_outlet.push_sample([{"letter": e.value, "space": " ",
                                            "erase": "<ERASE>"}[e.kind]])

    try:
        while True:
            samples, _ = inlet.pull_chunk(timeout=poll_s, max_samples=4096)
            if samples:
                handle(dec.push(np.asarray(samples, dtype=np.float64).T))
            if getattr(inlet, "done", False) and not samples:
                break
            if t_end is not None and time.monotonic() >= t_end:
                break
    except KeyboardInterrupt:
        pass
    handle(dec.flush())
    return dec

"""Command line: python -m eeg_morse <command> ...

  info       list channels / sampling rate of a recording (find your cap's labels)
  simulate   make a synthetic eego-like recording of a message (SIMULATED data)
  decode     recording -> dots/dashes -> English (+ plot, + JSON report)
  calibrate  tune settings on a recording of a KNOWN phrase, save a config
  live       decode eego's LSL stream in real time (or replay a file)
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

from . import io as eio
from .config import PRESETS, PipelineConfig, preset


def _config(args) -> PipelineConfig:
    if getattr(args, "config", None):
        cfg = PipelineConfig.load(args.config)
    else:
        cfg = preset(args.preset)
    f, d, t = cfg.feature, cfg.detect, cfg.timing
    if getattr(args, "channels", None):
        f.channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    if getattr(args, "band", None):
        f.band = (float(args.band[0]), float(args.band[1]))
    if getattr(args, "direction", None):
        f.direction = args.direction
    if getattr(args, "measure", None):
        f.measure = args.measure
    if getattr(args, "line_freq", None) is not None:
        f.line_freq = None if args.line_freq == 0 else args.line_freq
    if getattr(args, "smooth", None):
        f.smooth_s = args.smooth
    if getattr(args, "unit", None):
        t.unit_s = args.unit
    return cfg


def _add_feature_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("signal settings (override the preset/config)")
    g.add_argument("--preset", default="motor", choices=sorted(PRESETS),
                   help="motor = hand movement (mu/beta ERD over C3/C4); clench = jaw clench "
                        "(EMG on temporal channels); blink = eye closures (frontal). Default motor.")
    g.add_argument("--config", help="JSON config saved by `calibrate` (overrides --preset)")
    g.add_argument("--channels", help="comma-separated channel labels, e.g. C3,C4,Cz")
    g.add_argument("--band", nargs=2, type=float, metavar=("LO", "HI"), help="frequency band in Hz")
    g.add_argument("--direction", choices=["decrease", "increase"],
                   help="does the movement lower (ERD) or raise the band signal?")
    g.add_argument("--measure", choices=["power", "amplitude"])
    g.add_argument("--line-freq", type=float, help="mains frequency to notch (60 US, 50 EU; 0 = off)")
    g.add_argument("--smooth", type=float, help="envelope smoothing window in seconds")
    g.add_argument("--unit", type=float, help="Morse unit (dot length) in seconds; default: estimate")


def _load(args) -> eio.Recording:
    rec = eio.load(args.file, sfreq=getattr(args, "sfreq", None))
    if getattr(args, "start", None) is not None or getattr(args, "stop", None) is not None:
        rec = rec.crop(args.start, args.stop)
    return rec


def cmd_info(args) -> int:
    print(_load(args).summary())
    return 0


def cmd_simulate(args) -> int:
    from .simulate import simulate

    rec, truth = simulate(args.text, preset=args.preset, sfreq=args.sfreq, unit_s=args.unit,
                          noise=args.noise, seed=args.seed, line_freq=args.line_freq)
    out = Path(args.out)
    if out.suffix.lower() == ".csv":
        import numpy as np
        import pandas as pd

        df = pd.DataFrame(rec.data.T, columns=rec.ch_names)
        df.insert(0, "time", np.arange(rec.data.shape[1]) / rec.sfreq)
        df.to_csv(out, index=False, float_format="%.3f")
    else:
        eio.save_npz(rec, out, truth_on=truth.t_on, truth_off=truth.t_off,
                     truth_symbols=np_str(truth.symbols), message=truth.message)
    print(f"SIMULATED {args.preset} recording of {truth.message!r}: {rec.duration:.1f}s, "
          f"{len(rec.ch_names)} channels @ {rec.sfreq:g} Hz, unit {truth.unit_s:g}s -> {out}")
    return 0


def np_str(xs):
    import numpy as np

    return np.array(list(xs))


def _truth_from_npz(path: str):
    """Ground truth stored by `simulate`, used only to draw it on plots."""
    if not str(path).lower().endswith(".npz"):
        return None
    import numpy as np

    from .simulate import Truth

    z = np.load(path, allow_pickle=False)
    if "truth_on" not in z:
        return None
    return Truth(str(z["message"]), z["truth_on"], z["truth_off"],
                 [str(s) for s in z["truth_symbols"]], 0.0)


def _print_result(res) -> None:
    tr = res.transcript
    print(f"morse : {tr.morse or '(none)'}")
    print(f"text  : {tr.text or '(none)'}")
    print(f"unit {tr.unit_s:.3f}s ({tr.unit_source}), {len(res.segments)} key-downs, "
          f"separability {res.thresholds.separability:.2f}, channels {', '.join(res.activation.channels)}")
    for w in res.warnings + tr.notes:
        print(f"note  : {w}")


def cmd_decode(args) -> int:
    from .pipeline import decode

    rec = _load(args)
    cfg = _config(args)
    res = decode(rec, cfg, correct=not args.no_correct, fixed_thresholds=args.fixed_thresholds)
    _print_result(res)
    if args.json:
        Path(args.json).write_text(json.dumps(res.report(), indent=2))
        print(f"report: {args.json}")
    if args.plot:
        from .plot import plot_result

        truth = _truth_from_npz(args.file) if args.start is None else None
        plot_result(res, args.plot, truth=truth)
        print(f"plot  : {args.plot}")
    return 0


def cmd_calibrate(args) -> int:
    from .pipeline import calibrate

    rec = _load(args)
    cal = calibrate(rec, _config(args), args.expect)
    print(cal.summary())
    cal.config.save(args.out)
    print(f"saved : {args.out}  (use with: decode --config {args.out}  /  live --config {args.out})")
    if cal.text_similarity < 0.8:
        print("note  : the best settings still decode poorly. Check the channel list (`info`), "
              "the preset, impedances, or send more slowly (longer units).")
    if args.plot:
        from .plot import plot_result

        plot_result(cal.result, args.plot, truth=_truth_from_npz(args.file),
                    title=f"Calibration: expected {cal.expected_text!r}, decoded {cal.result.text!r}")
        print(f"plot  : {args.plot}")
    return 0


def cmd_live(args) -> int:
    from .stream import ReplayInlet, TerminalView, open_lsl_inlet, open_marker_outlet, run_live

    cfg = _config(args)
    if args.replay:
        rec = eio.load(args.replay)
        inlet, sfreq, names = ReplayInlet(rec, speed=args.speed or None), rec.sfreq, rec.ch_names
        speed = f"{args.speed:g}x speed" if args.speed else "maximum speed"
        print(f"Replaying {args.replay} at {speed} (no hardware needed)")
    else:
        inlet, sfreq, names = open_lsl_inlet(args.stream_name, timeout=args.timeout)
        print(f"Connected to LSL stream: {len(names)} channels @ {sfreq:g} Hz")
    outlet = open_marker_outlet() if args.markers else None
    print(f"Sit still for {args.rest:g}s while the baseline is measured...")
    dec = run_live(inlet, sfreq, names, cfg, rest_s=args.rest, duration_s=args.duration,
                   marker_outlet=outlet, on_event=None)
    print(f"\nfinal text: {dec.text}")
    if not dec.locked:
        print("note: never locked onto a clear on/off signal. Check channels/preset or calibrate.")
    if args.save:
        Path(args.save).write_text(json.dumps({"text": dec.text, "unit_s": dec.unit,
                                               "thresholds": [dec.lo, dec.hi],
                                               "channels": dec.channels}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eeg_morse", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="list channels and sampling rate")
    p.add_argument("file")
    p.add_argument("--sfreq", type=float, help="sampling rate (CSV without a time column)")
    p.set_defaults(fn=cmd_info)

    p = sub.add_parser("simulate", help="write a SIMULATED eego-like recording")
    p.add_argument("text")
    p.add_argument("--out", required=True, help=".npz (keeps ground truth) or .csv")
    p.add_argument("--preset", default="motor", choices=sorted(PRESETS))
    p.add_argument("--unit", type=float, help="dot length in seconds")
    p.add_argument("--sfreq", type=float, default=500.0)
    p.add_argument("--noise", type=float, default=1.0, help="background noise multiplier")
    p.add_argument("--line-freq", type=float, default=60.0)
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(fn=cmd_simulate)

    for name, fn, helptext in (("decode", cmd_decode, "decode a recording to Morse and English"),
                               ("calibrate", cmd_calibrate, "tune settings on a known phrase")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("file", help=".cnt (eego), .xdf, .edf/.bdf, .npz or .csv")
        p.add_argument("--sfreq", type=float, help="sampling rate (CSV without a time column)")
        p.add_argument("--start", type=float, help="crop: start time in seconds")
        p.add_argument("--stop", type=float, help="crop: stop time in seconds")
        p.add_argument("--plot", help="save a diagnostic PNG here")
        _add_feature_args(p)
        if name == "decode":
            p.add_argument("--json", help="save a full JSON report here")
            p.add_argument("--no-correct", action="store_true",
                           help="show invalid letter codes as '?' instead of repairing them")
            p.add_argument("--fixed-thresholds", action="store_true",
                           help="use the config's saved thresholds instead of re-fitting")
        else:
            p.add_argument("--expect", required=True, help="the phrase that was sent, e.g. PARIS")
            p.add_argument("--out", default="calibration.json", help="where to save the config")
        p.set_defaults(fn=fn)

    p = sub.add_parser("live", help="decode eego's LSL stream in real time")
    _add_feature_args(p)
    p.add_argument("--stream-name", help="LSL stream name (default: first stream of type EEG)")
    p.add_argument("--timeout", type=float, default=15.0, help="seconds to look for the stream")
    p.add_argument("--replay", help="replay a recording instead of connecting to LSL")
    p.add_argument("--speed", type=float, default=1.0, help="replay speed (0 = as fast as possible)")
    p.add_argument("--rest", type=float, default=6.0, help="seconds of rest at the start")
    p.add_argument("--duration", type=float, help="stop after this many seconds")
    p.add_argument("--markers", action="store_true",
                   help="publish decoded letters as an LSL marker stream (eego can record them)")
    p.add_argument("--save", help="save the final text + settings as JSON")
    p.set_defaults(fn=cmd_live)

    args = ap.parse_args(argv)
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        warnings.formatwarning = lambda m, *a, **k: f"note  : {m}\n"
        try:
            return args.fn(args)
        except (ImportError, FileNotFoundError, ValueError, RuntimeError, KeyError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2


if __name__ == "__main__":
    sys.exit(main())

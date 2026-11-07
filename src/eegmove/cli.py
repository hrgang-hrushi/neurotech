"""Command line for the whole workflow. Run `eegmove --help`."""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

from .config import ARTIFACT_DIR, ASSUMED_MONTAGE, DATA_DIR, DEFAULT_CLASSES, SignalConfig


def _subjects(spec: str) -> list[int]:
    from .datasets import ALL_SUBJECTS

    if spec == "all":
        return list(ALL_SUBJECTS)
    start, _, stop = spec.partition("-")
    wanted = range(int(start), int(stop or start) + 1)
    return [s for s in wanted if s in ALL_SUBJECTS]


def _classes(spec: str) -> list[str]:
    return [c.strip() for c in spec.split(",") if c.strip()]


def cmd_doctor(args) -> int:
    """Check the things that can't be fixed once on the ANT network, which may have no internet."""
    ok = True

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= passed
        print(f"[{'PASS' if passed else 'FAIL'}] {name}{': ' + detail if detail else ''}")

    check("Python", sys.version_info[:2] in ((3, 11), (3, 12)), platform.python_version())
    try:
        import pylsl

        check("liblsl loads", True, f"v{pylsl.library_version()}")
        from .streaming import EegInlet, make_outlet

        name = f"doctor-{int(time.time())}"
        outlet = make_outlet(name, ["C3", "C4", "TRIGGER"], 100.0)
        inlet = EegInlet(channels=["C4", "C3"], name=name, timeout=5)
        received = 0
        stop = time.time() + 3
        while time.time() < stop and received < 20:
            outlet.push_sample([1.0, 2.0, 0.0])
            samples, _ = inlet.pull(timeout=0.02)
            received += len(samples)
            if len(samples):
                check("label-based channel order", abs(samples[0][0] - 2.0) < 1e-6)
                received = max(received, 20)
        check("LSL loopback on this machine", received > 0, f"{received} samples")
    except Exception as error:  # a doctor reports failures rather than crashing on them
        check("LSL", False, repr(error))

    for module in ("antio", "mne", "pyriemann", "torch", "tkinter"):
        try:
            __import__(module)
            check(f"import {module}", True)
        except Exception as error:
            check(f"import {module}", False, repr(error))

    import torch

    print(f"[INFO] torch device: {'mps' if torch.backends.mps.is_available() else 'cpu'}")
    checkpoints = sorted(ARTIFACT_DIR.glob("pretrained_*.pt"))
    check("pretrained model on disk", bool(checkpoints), ", ".join(p.name for p in checkpoints))
    count = len(list((DATA_DIR / "mne").rglob("*.edf")))
    check("PhysioNet data cached", count > 0, f"{count} EDF files")
    imagined = len(list((DATA_DIR / "mne").rglob("*R04.edf")))
    check("Imagined PhysioNet runs cached", imagined > 0, f"{imagined} subjects")
    return 0 if ok else 1


def cmd_fetch(args) -> int:
    from mne.datasets import eegbci

    from .datasets import EXECUTED_RUNS, IMAGINED_RUNS

    runs = list(EXECUTED_RUNS) + (list(IMAGINED_RUNS) if args.imagined else [])
    subjects = _subjects(args.subjects)
    for i, subject in enumerate(subjects, 1):
        eegbci.load_data(subject, runs, path=str(DATA_DIR / "mne"), update_path=False,
                         verbose="ERROR")
        print(f"{i}/{len(subjects)} subjects", flush=True)
    return 0


def cmd_pretrain(args) -> int:
    from .datasets import physionet_channels, recording_channels, shared_channels
    from .train import pretrain

    channels = list(ASSUMED_MONTAGE)
    if args.montage_from:
        channels, dropped = shared_channels(recording_channels(Path(args.montage_from)),
                                            physionet_channels())
        print(f"Montage: {len(channels)} channels: {channels}")
        if dropped:
            print(f"Not in PhysioNet, so left out of the model: {dropped}")
    subjects = _subjects(args.subjects)
    heldout = _subjects(args.heldout) if args.heldout else []
    subjects = [s for s in subjects if s not in heldout]
    pretrain(subjects, heldout, channels, _classes(args.classes), SignalConfig(), args.epochs,
             args.imagined)
    return 0


def cmd_replay(args) -> int:
    from .streaming import physionet_replay_signal, replay

    if args.recording:
        import numpy as np

        saved = np.load(args.recording, allow_pickle=False)
        replay(saved["eeg"], [str(c) for c in saved["channels"]], float(saved["sfreq"]),
               loops=args.loops)
        return 0
    signal, labels = physionet_replay_signal(args.subject, args.physionet_run, args.sfreq,
                                             args.units)
    replay(signal, labels, args.sfreq, loops=args.loops)
    return 0


def cmd_record(args) -> int:
    from .record import run_session

    out = Path(args.out) if args.out else DATA_DIR / "recordings" / args.mode
    try:
        run_session(out, _classes(args.classes), args.per_class, args.blocks, args.seed,
                    use_lsl=not args.no_lsl, stream=args.stream, baseline_s=args.baseline,
                    fullscreen=not args.windowed, autostart=args.autostart, movement=args.mode)
    except FileExistsError as error:
        print(f"ERROR: {error}")
        return 2
    return 0


def cmd_calibrate(args) -> int:
    import torch

    from .datasets import recording_channels, recording_movement
    from .train import calibrate, latest_checkpoint
    from .verdict import session_path

    recording = Path(args.recording)
    schedule = Path(args.schedule) if args.schedule else None
    movement = args.mode or recording_movement(recording, schedule)
    if movement == "unknown":
        print("WARNING: this recording has no mode, so it can't earn a GO. Pass --mode.")
    if args.pretrained == "none":
        channels, classes, pretrained = recording_channels(recording), _classes(args.classes), None
    else:
        pretrained = Path(args.pretrained) if args.pretrained else latest_checkpoint()
        print(f"Using pretrained model {pretrained.name}")
        saved = torch.load(pretrained, map_location="cpu", weights_only=False)
        # Classes come from the request: a checkpoint with a different set gets a new head.
        channels, classes = saved["channels"], _classes(args.classes)
    calibrate(recording, pretrained, channels, classes, SignalConfig(), schedule,
              Path(args.out) if args.out else session_path(movement), movement=movement)
    return 0


def cmd_check(args) -> int:
    from .check import run_check

    record = run_check(Path(args.model), stream=args.stream, baseline_s=args.baseline,
                       rest_s=args.rest, n_cues=args.cues, threshold=args.threshold)
    return 0 if record["go"] else 3


def cmd_live(args) -> int:
    from .live import run_live
    from .verdict import Refused, choose_model

    model, threshold = args.model, args.threshold
    if model is None:
        try:
            choice = choose_model()
        except Refused as error:
            print(f"{error}\nTo rehearse anyway, pass --model. `eegmove type` will still refuse it.")
            return 2
        print(choice.banner)
        model, threshold = choice.model_path, threshold or choice.threshold
    run_live(Path(model), host=args.host, port=args.port, stream=args.stream,
             baseline_s=args.baseline, duration_s=args.duration, threshold=threshold or 0.6,
             quiet=args.quiet)
    return 0


def cmd_listen(args) -> int:
    """Print decoder events: the smallest possible example of an app."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    print(f"Listening on udp://{args.host}:{args.port}")
    while True:
        message = json.loads(sock.recv(65536))
        if message["event"]:
            print(f"{message['t']:8.2f}s  EVENT {message['event']}")
    return 0


def cmd_type(args) -> int:
    from .typing_app import run_app

    return run_app(host=args.host, port=args.port, letter_gap_s=args.letter_gap,
                   word_gap_s=args.word_gap, simulate=args.simulate)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eegmove", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    classes = ",".join(DEFAULT_CLASSES)

    p = commands.add_parser("doctor", help="check this laptop is ready for the ANT station")
    p.set_defaults(run=cmd_doctor)

    p = commands.add_parser("fetch", help="download PhysioNet data")
    p.add_argument("--subjects", default="all", help="'all' or a range like 1-20")
    p.add_argument("--imagined", action="store_true", help="also fetch imagined-movement runs")
    p.set_defaults(run=cmd_fetch)

    p = commands.add_parser("pretrain", help="train the shared model on PhysioNet")
    p.add_argument("--subjects", default="all")
    p.add_argument("--heldout", default="", help="subjects kept out for testing, like 90-109")
    p.add_argument("--epochs", type=int, default=40)
    p.add_argument("--classes", default=classes)
    p.add_argument("--imagined", action="store_true", help="also train on imagined movement")
    p.add_argument("--montage-from", help="use the channels from this recording")
    p.set_defaults(run=cmd_pretrain)

    p = commands.add_parser("replay", help="imitate the eego LSL stream with no headset")
    p.add_argument("--recording", help="replay a saved .npz instead of PhysioNet")
    p.add_argument("--subject", type=int, default=1)
    # dest matters: main() calls args.run, so a plain --run would replace the command.
    p.add_argument("--run", dest="physionet_run", type=int, default=3)
    p.add_argument("--sfreq", type=float, default=500.0)
    p.add_argument("--units", choices=["uV", "V"], default="uV")
    p.add_argument("--loops", type=int, default=0, help="0 repeats forever")
    p.set_defaults(run=cmd_replay)

    p = commands.add_parser("record", help="show cues and capture a labelled session")
    p.add_argument("--mode", required=True, choices=["imagined", "real"],
                   help="imagined keeps the hands still; real is the fallback")
    p.add_argument("--out", help="default: data/recordings/<mode>")
    p.add_argument("--classes", default=classes)
    p.add_argument("--per-class", type=int, default=25)
    p.add_argument("--blocks", type=int, default=3)
    p.add_argument("--seed", type=int, default=4)
    p.add_argument("--stream", help="LSL stream name, if several are visible")
    p.add_argument("--no-lsl", action="store_true", help="cues only; label an eego export later")
    p.add_argument("--baseline", type=float, default=60.0, help="seconds of rest before the cues")
    p.add_argument("--windowed", action="store_true", help="don't take over the whole screen")
    p.add_argument("--autostart", action="store_true", help="begin without waiting for SPACE")
    p.set_defaults(run=cmd_record)

    p = commands.add_parser("calibrate", help="fit the decoder to one person's recording")
    p.add_argument("recording")
    p.add_argument("--schedule", help="cue log JSON, needed for eego exports")
    p.add_argument("--pretrained", help="checkpoint path, or 'none' to skip transfer learning")
    p.add_argument("--classes", default=classes)
    p.add_argument("--mode", choices=["imagined", "real"],
                   help="only for recordings made before modes existed")
    p.add_argument("--out", help="default: artifacts/session-<mode>.joblib")
    p.set_defaults(run=cmd_calibrate)

    p = commands.add_parser("check", help="measure a model live and record whether it may type")
    p.add_argument("model")
    p.add_argument("--stream", help="LSL stream name, if several are visible")
    p.add_argument("--baseline", type=float, default=60.0)
    p.add_argument("--rest", type=float, default=120.0)
    p.add_argument("--cues", type=int, default=20)
    p.add_argument("--threshold", type=float, default=0.6)
    p.set_defaults(run=cmd_check)

    p = commands.add_parser("live", help="decode the LSL stream and send JSON over UDP")
    p.add_argument("--model", help="default: the model that passed its check")
    p.add_argument("--stream", help="LSL stream name, if several are visible")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9999)
    p.add_argument("--baseline", type=float, default=60.0, help="seconds of rest before decoding")
    p.add_argument("--duration", type=float)
    p.add_argument("--threshold", type=float, help="default: the one the check passed with")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(run=cmd_live)

    p = commands.add_parser("listen", help="print events from `eegmove live`")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9999)
    p.set_defaults(run=cmd_listen)

    p = commands.add_parser("type", help="the Morse typing screen")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9999)
    p.add_argument("--letter-gap", type=float, default=3.0, help="seconds at rest to end a letter")
    p.add_argument("--word-gap", type=float, default=7.0, help="seconds at rest to end a word")
    p.add_argument("--simulate", action="store_true", help="type with . and - keys, no decoder")
    p.set_defaults(run=cmd_type)

    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())

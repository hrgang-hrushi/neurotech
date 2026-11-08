"""Clench decoding accuracy with realistic artifacts (SIMULATED data only).

Compares the plain decoder with the artifact-aware one (`decode_clean`) and,
when --language is set, the full upload path including word correction and
grammar. Two clench layouts are simulated:

  temporal  clench EMG on T7/T8/M1/M2 (textbook), blinks elsewhere
  real-cap  clench EMG on F3/C3/F7/F4/F9/T7 as on the 7 Nov recording,
            i.e. overlapping the blink EMG sites (the hard case)

Usage: uv run python scripts/benchmark_artifacts.py [--seeds 3] [--language]
"""
from __future__ import annotations

import argparse
import time
import warnings

from eeg_morse import decode
from eeg_morse.clean_decode import decode_clean
from eeg_morse.config import PipelineConfig
from eeg_morse.pipeline import segment_breaks
from eeg_morse.simulate import REAL_CAP_CLENCH_WEIGHT, simulate

warnings.filterwarnings("ignore")

PHRASES = ["HOW ARE YOU", "I NEED WATER", "WHERE IS THE DOCTOR", "CAN YOU HELP ME",
           "THANK YOU", "I AM COLD", "CALL MY MOM", "WHAT TIME IS IT"]
LAYOUTS = {"temporal": None, "real-cap": REAL_CAP_CLENCH_WEIGHT}


def cer(got: str, want: str) -> float:
    """Character error rate via Levenshtein distance over the expected length."""
    prev = list(range(len(want) + 1))
    for i, a in enumerate(got, 1):
        cur = [i]
        for j, b in enumerate(want, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = cur
    return prev[-1] / max(len(want), 1)


def run(args: argparse.Namespace) -> None:
    model = PipelineConfig.load(args.model)
    from eeg_morse.language import correct_transcript

    print(f"model {args.model}, {len(PHRASES)} phrases x {args.seeds} seeds per row\n")
    print(f"{'layout':9} {'artifacts':9} {'decoder':9} {'exact':>7} {'CER':>7}")
    for layout, weight in LAYOUTS.items():
        for strength in args.artifacts:
            rows = {"plain": [0, 0.0], "clean": [0, 0.0]}
            if args.language:
                rows["clean+lm"] = [0, 0.0]
            t0 = time.time()
            for phrase in PHRASES:
                for seed in range(args.seeds):
                    rec, truth = simulate(phrase, preset="clench", seed=seed, unit_s=args.unit,
                                          artifacts=strength, emg_weight=weight, noise=args.noise)
                    outs = {"plain": decode(rec, model).text}
                    cr = decode_clean(rec, model)
                    outs["clean"] = cr.result.text
                    if args.language:
                        fixed = correct_transcript(cr.result.transcript, segment_breaks(rec))
                        outs["clean+lm"] = fixed.upper_text.replace("'", "")
                    for k, txt in outs.items():
                        rows[k][0] += txt == truth.message
                        rows[k][1] += cer(txt, truth.message)
                    if args.verbose and any(v != truth.message for k, v in outs.items() if k != "plain"):
                        print(f"    {truth.message!r} -> {outs}")
            n = len(PHRASES) * args.seeds
            for k, (ex, c) in rows.items():
                print(f"{layout:9} {strength:<9g} {k:9} {ex:>3}/{n:<3} {c / n:7.1%}")
            print(f"{'':29}({time.time() - t0:.0f}s)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", default="models/team4_clench.json")
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--artifacts", type=float, nargs="+", default=[1.0, 1.5])
    p.add_argument("--noise", type=float, default=1.0)
    p.add_argument("--unit", type=float, default=0.3)
    p.add_argument("--language", action="store_true", help="also score word correction")
    p.add_argument("--verbose", action="store_true")
    run(p.parse_args())


if __name__ == "__main__":
    main()

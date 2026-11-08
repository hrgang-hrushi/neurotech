"""Accuracy on SIMULATED recordings: offline and live, per preset.

    python scripts/benchmark_sim.py            # ~3-5 minutes
    python scripts/benchmark_sim.py --quick    # fewer seeds

Numbers from simulated data show the pipeline works as designed. They are not
evidence of real-world accuracy; re-run `decode`/`calibrate` on real eego
recordings for that.
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.simplefilter("ignore")

from eeg_morse.config import preset  # noqa: E402
from eeg_morse.pipeline import calibrate, decode  # noqa: E402
from eeg_morse.simulate import simulate  # noqa: E402
from eeg_morse.stream import StreamingDecoder  # noqa: E402

MSG = "SOS HELP 42"
CAL = "PARIS THE QUICK FOX"


def lev(a: str, b: str) -> int:
    d = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, d[0] = d[:], i
        for j, cb in enumerate(b, 1):
            d[j] = min(prev[j] + 1, d[j - 1] + 1, prev[j - 1] + (ca != cb))
    return d[-1]


def stream(rec, cfg, seed: int) -> str:
    rng = np.random.default_rng(seed)
    dec = StreamingDecoder(cfg, rec.sfreq, rec.ch_names, rest_s=5.0)
    pos = 0
    while pos < rec.data.shape[1]:
        n = int(rng.integers(1, 200))
        dec.push(rec.data[:, pos:pos + n])
        pos += n
    dec.flush()
    return dec.text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    n = 5 if ap.parse_args().quick else 20
    print(f"message {MSG!r}, {n} seeds each; CER = character error rate\n")
    print(f"{'preset':7s} {'unit':>5s} {'noise':>5s} | {'offline exact':>13s} {'CER':>6s} | "
          f"{'live* exact':>11s} {'CER':>6s}")
    for name, units in (("motor", (1.0, 1.5)), ("clench", (0.3, 0.2)), ("blink", (0.4, 0.3))):
        for unit in units:
            for noise in (1.0, 1.5):
                cfg = calibrate(simulate(CAL, preset=name, seed=999, unit_s=unit, noise=noise)[0],
                                preset(name), CAL).config
                off, live = [], []
                for s in range(n):
                    rec, _ = simulate(MSG, preset=name, seed=s, unit_s=unit, noise=noise)
                    off.append(decode(rec, cfg).text)
                    live.append(stream(rec, cfg, s))

                def stats(r):
                    return np.mean([x == MSG for x in r]), np.mean([lev(x, MSG) / len(MSG) for x in r])

                (oe, oc), (le, lc) = stats(off), stats(live)
                print(f"{name:7s} {unit:5.2f} {noise:5.1f} | {oe:13.0%} {oc:6.1%} | {le:11.0%} {lc:6.1%}")
    print("\n* live = causal streaming decoder fed in random chunk sizes, using a config from "
          "`calibrate` on a separate simulated recording of 'PARIS THE QUICK FOX'.")


if __name__ == "__main__":
    main()

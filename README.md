# neurotech

Team 4's entry in the ANT Neuro track at the Neurotech @ NC State BCI Hackathon. It reads live EEG
from a 24-channel ANT Neuro eego headset and lets someone type by imagining hand movements, with
no visible movement needed. Imagining the left hand is a Morse dot, and imagining the right hand is
a dash. If imagined movement doesn't pass its checks, real movement is the labelled fallback.

This is a prototype, tested on healthy volunteers at most. Nothing here shows that it works for
patients.

New here? Start with the [challenge brief](docs/CHALLENGE.md) and the
[rotation playbook](docs/PLAYBOOK.md). **Submission closes Sunday at 11:45 AM.**

```text
eego headset ─ LSL ─> filter ─> align to this person ─> decoder ─> debounce ─ UDP JSON ─> Morse app
                      (same code offline and live)     (pretrained + calibrated)      (only with a GO)
```

## Setup

You need [uv](https://docs.astral.sh/uv/). Do this **before** going to the ANT station, because the
ANT network may have no internet.

```bash
git clone https://github.com/hrgang-hrushi/neurotech.git
cd neurotech
uv sync
uv run eegmove fetch --imagined
uv run eegmove doctor
```

`fetch --imagined` downloads about 4 GB in total. `doctor` checks that the laptop has everything it
needs offline. `pretrain` comes after the first recording, because it needs the real channel labels.

## How it stays accurate on so little data

We only get 30-minute slots with the headset, so this pulls in as much outside knowledge as it can:

- **Pretrained on 100+ people.** A network trained on the PhysioNet EEG Motor Movement dataset,
  restricted to the channels we actually have.
- **Aligned to each new person.** About 60 seconds of rest recentres their signal with no labels at
  all, and that also corrects drift between rotations. It's the core of the scalability story:
  a new user needs minutes of setup instead of a full training session.
- **Mirrored training data.** Flipping the head left-to-right turns a left-hand trial into a
  right-hand one, doubling the data.
- **A safety net.** A Riemannian classifier fits one person in seconds and is hard to beat on small
  data. Calibration scores both decoders on cues they never saw, then keeps the winner or the average.
- **One preprocessing path.** Offline and live code run the same causal filter, so offline scores
  stay meaningful once the system goes live.

## When it's allowed to type

A faint signal can look like a working decoder, so a model has to earn the right to type:

| Check | Pass |
| --- | --- |
| Left vs right on held-out cues | at least 85% |
| Rest, left, right on held-out cues | at least 70% |
| False activations during 2 minutes of live rest | at most 0.5 per minute |
| Correct symbols in 20 live cues | at least 17 of 20 |

If imagined movement fails, the app uses the real-movement model, if that passed, and says so on
screen. If both fail, it refuses to type. A pass belongs to one exact model file, so recalibrating
means checking again. Every attempt is counted and printed.

## Workflow

### Rehearse with no headset

Replay imitates the eego stream, so the whole team can work and test without hardware:

```bash
uv run eegmove replay                   # terminal 1: streams PhysioNet data over LSL
uv run eegmove live --model <a model>   # terminal 2: --model allows rehearsal with no GO
uv run eegmove listen                   # terminal 3: prints movement events
```

Replay can never earn a GO. To try the typing screen with no decoder at all, use the `.` and `-`
keys. The screen says SIMULATED INPUT the whole time:

```bash
uv run eegmove type --simulate
```

### Record and calibrate

The [playbook](docs/PLAYBOOK.md) has the step-by-step version.

```bash
uv run eegmove record --mode imagined --per-class 25
uv run eegmove record --mode real --per-class 12 --baseline 30 --blocks 1
uv run eegmove pretrain --classes rest,left,right --imagined --epochs 15 --heldout 90-109 --montage-from data/recordings/imagined.npz
uv run eegmove calibrate data/recordings/imagined.npz
uv run eegmove calibrate data/recordings/real.npz
uv run eegmove check artifacts/session-imagined.joblib
uv run eegmove live     # terminal 1
uv run eegmove type     # terminal 2
```

If imagined movement gets a NO-GO, run `uv run eegmove check artifacts/session-real.joblib` too.

## Typing

| Input | Meaning |
| --- | --- |
| Left hand | dot |
| Right hand | dash |
| 3 seconds of rest | end of letter |
| 7 seconds of rest | space |
| `----` | delete the last letter |
| `..--` | accept the word shown |

Expect about 6 to 8 seconds per symbol, which is about 3 letters a minute. That is an estimate,
not a measurement, so short words suit a demo best.

## Building the app

`eegmove type` is one app, and any other can listen for JSON on UDP port 9999, in any language:

```json
{"run": "a1b2c3d4", "seq": 17, "step_s": 0.25, "t": 12.5, "lsl_time": 8301.2,
 "source": "eeg", "movement": "imagined", "model": "9f8e7d6c5b", "threshold": 0.6,
 "latency_ms": 41.2, "ok": true, "reason": null, "rest": false,
 "probs": {"rest": 0.1, "left": 0.8, "right": 0.1},
 "state": "left", "event": "left", "snr_db": 3.4, "warning": null}
```

`state` is the current smoothed guess. `event` fires once per deliberate movement, and is usually
what an app should react to. When `ok` is false the window was rejected, `probs` is null, and
`reason` says why. Only one program can hold the port at a time, so `listen` and `type` can't run
together.

```python
import json, socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", 9999))
while True:
    message = json.loads(sock.recv(65536))
    if message["event"]:
        print("Do something for:", message["event"])
```

## Repo layout

| Path | What's in it |
| --- | --- |
| `src/eegmove/preprocess.py` | Shared filtering and per-person alignment |
| `src/eegmove/datasets.py` | PhysioNet and eego recording loaders |
| `src/eegmove/models.py`, `train.py` | Decoders, pretraining, calibration |
| `src/eegmove/streaming.py` | LSL reader and replay stream |
| `src/eegmove/record.py` | Cue screen and data capture |
| `src/eegmove/live.py` | Real-time loop and debouncing |
| `src/eegmove/quality.py` | Rejecting bad windows and tracking signal strength |
| `src/eegmove/verdict.py`, `check.py` | The go/no-go rule and the live check |
| `src/eegmove/morse.py`, `words.py`, `typing_app.py` | Morse typing, word completion, typing screen |

Run the tests with `uv run pytest`.

**This repo is public.** EEG recordings stay out of git (`.gitignore` covers them), and so do
participant details, passwords and invite links.

## Credits

- PhysioNet EEG Motor Movement/Imagery Dataset: Schalk et al., *IEEE TBME* 51(6), 2004; Goldberger
  et al., *Circulation* 101(23), 2000.
- Shallow ConvNet: Schirrmeister et al., *Human Brain Mapping* 38(11), 2017.
- Euclidean alignment: He & Wu, *IEEE TBME* 67(2), 2020.
- Riemannian tangent-space classification: Barachant et al., *IEEE TBME* 59(4), 2012.

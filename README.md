# neurotech

Team 4's entry in the ANT Neuro track at the Neurotech @ NC State BCI Hackathon. It reads live EEG
from a 24-channel ANT Neuro eego headset, works out which movement someone is making, and sends
that to an app in real time.

New here? Start with the [challenge brief](docs/CHALLENGE.md) and the
[rotation playbook](docs/PLAYBOOK.md). **Submission closes Sunday at 11:45 AM.**

```text
eego headset ─ LSL ─> filter ─> align to this person ─> decoder ─> debounce ─ UDP JSON ─> app
                      (same code offline and live)     (pretrained + calibrated)
```

## Setup

You need [uv](https://docs.astral.sh/uv/). Do this **before** going to the ANT station, because the
ANT network may have no internet.

```bash
git clone https://github.com/hrgang-hrushi/neurotech.git
cd neurotech
uv sync
uv run eegmove fetch
uv run eegmove pretrain
uv run eegmove doctor
```

`fetch` downloads about 2 GB. `doctor` checks that the laptop has everything it needs offline.

## How it stays accurate on so little data

We only get one 30-minute slot to record, so this pulls in as much outside knowledge as it can:

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

## Workflow

### Rehearse with no headset

Replay imitates the eego stream, so the whole team can work and test without hardware:

```bash
uv run eegmove replay     # terminal 1: streams PhysioNet data over LSL
uv run eegmove live       # terminal 2: needs a calibrated model
uv run eegmove listen     # terminal 3: prints movement events
```

### Record and calibrate

The [playbook](docs/PLAYBOOK.md) has the step-by-step version.

```bash
uv run eegmove record --out data/recordings/session1
uv run eegmove pretrain --montage-from data/recordings/session1.npz
uv run eegmove calibrate data/recordings/session1.npz
uv run eegmove live
```

## Building the app

The browser communication app is in `web/`. See the
[SignalSpeak runbook](docs/COMMUNICATION_APP.md) for manual rehearsal,
the UDP-to-WebSocket bridge, live EEG, replay, and Morse integration.

The app is a separate program in any language. It listens for JSON on UDP port 9999:

```json
{"t": 12.5, "probs": {"rest": 0.1, "left": 0.8, "right": 0.05, "feet": 0.05},
 "state": "left", "event": "left", "latency_ms": 41.2}
```

`state` is the current smoothed guess. `event` fires once per deliberate movement, and is usually
what an app should react to.

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

Run the tests with `uv run pytest`.

**This repo is public.** EEG recordings stay out of git (`.gitignore` covers them), and so do
participant details, passwords and invite links.

## Credits

- PhysioNet EEG Motor Movement/Imagery Dataset: Schalk et al., *IEEE TBME* 51(6), 2004; Goldberger
  et al., *Circulation* 101(23), 2000.
- Shallow ConvNet: Schirrmeister et al., *Human Brain Mapping* 38(11), 2017.
- Euclidean alignment: He & Wu, *IEEE TBME* 67(2), 2020.
- Riemannian tangent-space classification: Barachant et al., *IEEE TBME* 59(4), 2012.

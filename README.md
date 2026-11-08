# neurotech

Team 4's entry in the ANT Neuro track at the Neurotech @ NC State BCI Hackathon. New here? Start with
the [challenge brief](docs/CHALLENGE.md) and the [rotation playbook](docs/PLAYBOOK.md). **Submission
closes Sunday at 11:45 AM.**

This repo holds two ways to turn eego EEG into Morse code. They install together and share nothing at
run time, so either can be the demo:

| Package | Input | How a symbol is made |
| --- | --- | --- |
| [`eeg_morse`](#eeg_morse-one-movement-timed-like-a-telegraph-key) | One movement: hand, jaw clench or blink | A short movement is a dot, a long one a dash |
| [`eegmove`](#eegmove-two-imagined-hand-movements) | Imagined left or right hand | Left is a dot, right is a dash, and typing only starts after a go/no-go check |

Run every test with `uv run pytest`.

## eeg_morse: one movement, timed like a telegraph key

Turn movement signals recorded with an **ANT Neuro eego** EEG cap into Morse **dots and dashes**, then into **English**, from a recorded `.cnt` file or live while you send.

```
eego cap ──► .cnt file ─┐
         └─► LSL stream ┴─► pick channels ─► filter to movement band ─► activation trace
                                                                          │
   English ◄── Morse table ◄── letters/words ◄── dots/dashes ◄── key-down intervals
```

A short movement is a dot, a long one is a dash, and pauses separate letters and words, exactly like a telegraph key.

### Status: what is real and what is simulated

| Part | State |
| --- | --- |
| Signal processing, detection, timing, Morse decoding | Implemented, unit-tested |
| Offline decoding of files (`decode`) and tuning on a known phrase (`calibrate`) | Implemented, tested on **simulated** recordings |
| Live decoding from eego's LSL stream (`live`) | Implemented; the decoder is tested by replaying simulated data. **Not yet run against a real eego stream** |
| Reading eego `.cnt` files | **Tested on a real eego recording** (24-ch dry cap, 500 Hz, 6 paused/resumed segments, labeled events) via `antio` |
| Training on labeled eego events (`train`) | **Tested on real data**: jaw clench and short/long blinks (results below) |
| Accuracy on real people | One recording of one person so far. Simulator numbers further down are for development only. |

When demoing, label simulated output as simulated.

### Quick start

```bash
pip install -r requirements.txt          # or: pip install -e ".[all]"

# 1. no cap needed: make a simulated recording and decode it
python -m eeg_morse simulate "HELLO WORLD" --preset clench --out hello.npz
python -m eeg_morse decode hello.npz --preset clench --plot hello.png --json hello.json

# 2. replay it as if it were live
python -m eeg_morse live --replay hello.npz --preset clench --speed 1

# 3. real data from eego
python -m eeg_morse info session.cnt                      # channels, segments, impedances, labels, bad channels
python -m eeg_morse train session.cnt --preset clench --labels Clench --out models/clench.json --plot clench.png
python -m eeg_morse train session.cnt --preset blink --labels Blink --short "Short Blink" --long "Long Blink" --out models/blink.json --plot blink.png
python -m eeg_morse calibrate calib.cnt --preset motor --expect PARIS --out me.json --plot calib.png
python -m eeg_morse decode session.cnt --config me.json --plot session.png
python -m eeg_morse live --config me.json --markers       # eego must be streaming over LSL
python -m pytest                                           # 32 tests, ~10 s
```

`decode` prints the Morse and the English, and can save a JSON report and a diagnostic plot (raw band signal → activation with thresholds → dots/dashes → letters, with every letter traceable to the EEG that produced it).

### Using it with eego

**Recorded files.** Record normally in eego; the `.cnt` loads with `antio` (ANT's own reader; MNE ≥ 1.9 is the fallback). Keep the `.evt` and `.seg` files next to the `.cnt`: the loader reads the events you placed in eego (with durations), the impedance checks, and the pause/resume segments. Every stage processes each segment separately (filtering across a pause creates fake spikes), skips the first 2.5 s after each resume while the amplifier settles, treats a pause as a word break, and keeps bad channels (impedance > 1 MΩ, or flat) out of everything.

**Live.** In the eego software tick **Enable LSL EEG streaming**. `live` finds the first LSL stream of type EEG (or `--stream-name`). With `--markers`, decoded letters are published as an LSL marker stream; if eego's network events are enabled (Application options → Network Operation) they are recorded into the `.cnt` next to the EEG.

Live sessions start with **~6 s of rest** to learn the baseline. With a calibration config, decoding starts immediately. Without one, send a short warm-up (e.g. `PARIS`) until the terminal says `locked`; anything sent before then is not decoded.

### Choosing the movement (presets)

| Preset | What the person does | What the cap sees | Suggested dot length |
| --- | --- | --- | --- |
| `motor` (default) | squeeze / move the right hand (or imagine it) | mu/beta (8–30 Hz) power **drops** over C3/Cz/C4 (ERD) | **≥ 1.5 s** |
| `clench` | clench the jaw | broadband muscle (EMG) power on T7/T8 | 0.3 s (0.2 s offline only) |
| `blink` | close the eyes (short = dot, held = dash) | large slow deflection on Fp1/Fp2 | 0.3–0.4 s |

`motor` is the "brain signal" path and the hardest: the ERD is slow (~0.5 s lag) and weak on single trials, so it needs long, steady units. `clench` and `blink` are artifacts rather than cortical signals, but they are very reliable switches and make a good fallback or second channel for a demo. Any preset can be overridden: `--channels C4,FC2,CP2` (left-hand mover), `--band 8 30`, `--direction decrease|increase`, `--unit 1.5`, `--line-freq 50` (outside the Americas).

### Training on a labeled eego recording

Place events in eego while recording (or afterwards) for each movement, e.g. `Clench`, `Short Blink`, `Long Blink`, then:

```bash
python -m eeg_morse train session.cnt --preset clench --labels Clench --out models/clench.json --plot clench.png --report clench.json
```

`train` ranks every good channel by how much it changes inside your labeled events, then searches channel sets, reference, smoothing and hysteresis for the best match to your labels. Scoring: a labeled event overlapping a detection is a hit; a detection in a block where that movement was never labeled is a false alarm; extra detections inside labeled blocks are reported but not penalised (people blink more often than anyone labels). With `--short`/`--long` it also learns the duration boundary between the two, which becomes the dot/dash threshold. The saved config works with `decode` and `live`.

#### Results on the first real recording (7 Nov 2026)

24-channel dry cap, 500 Hz, reference CPz, 169 s in 6 segments. P3 and P4 were excluded automatically (impedance 1.1 and 1.7 MΩ).

| Movement | Labeled | Found | False alarms | Best channels | Contrast (noise ≈ 0.65) | Model |
| --- | --- | --- | --- | --- | --- | --- |
| Jaw clench (held ~2 s) | 4 | **4/4** | 0 | F3, C3, F7, F4, F9, T7 (30–95 Hz muscle power) | 0.85 | `models/team4_clench.json` |
| Blinks + eye closures | 11 | 7/11 labels; **every visible event found (7 blinks, 4 closures)** | 0 | Fp2, Fp1 (0–8 Hz) | 0.91 | `models/team4_blink.json` |

- Short blinks last ~0.28 s and closures ~2.7 s, so the **dot/dash boundary is 0.86 s** (100% separated).
- The 4 "missed" blink labels have no eye event under them: one in a block with no eye movement (82 s), one on a 0.7 s gap between closures (128.9 s), one in the settling time right after a resume (93.7 s), one between two blinks (106.5 s). Hand-placed labels also ran up to ~2 s longer than the closures they mark. For the next session, start each block with ~5 s of rest before the first movement.
- Clench was only recorded held (~2 s), so there is no short/long clench boundary yet. Record short (~0.3 s) and long (~1 s) clenches, then a `PARIS`, to train dot/dash and gap timing.
- `eeg_morse`'s offline path (`decode`, `calibrate`, `train`) filters zero-phase; only `live` is causal. Offline numbers can therefore be slightly optimistic for live use.

Training plots and reports are derived from a real recording, so they are shared within the team rather than committed; regenerate them with `train --plot --report`. The recording itself stays out of git.

### Calibration protocol (recommended for every person and session)

1. Cap on, impedances checked. Start recording, sit still **8–10 s**.
2. Send a known phrase at a steady pace, e.g. `PARIS` (contains dots, dashes, letter gaps). For `motor`, aim for 1.5 s dots, 4.5 s dashes, 1.5 s gaps inside a letter, 4.5 s between letters.
3. Rest a few seconds, stop recording.
4. `python -m eeg_morse calibrate calib.cnt --preset motor --expect PARIS --out me.json --plot calib.png`

Calibration checks that the phrase decodes, picks between all preset channels / the best 3 / the single best (so a left-hand mover gets C4 without asking), tunes smoothing and hysteresis, and saves the unit and thresholds for live mode. It only departs from the preset when that is a clear and stable improvement; in testing, tuning freely on one short phrase overfit and hurt other recordings.

### How it works

1. **Channels and reference**: pick the preset's channels (missing ones are skipped), subtract the common average of all scalp channels.
2. **Filter**: notch mains (60 Hz default), band-pass to the movement band. Offline is zero-phase; live is causal.
3. **Activation**: log band power (or smoothed amplitude for eye closures, with a rolling-percentile baseline instead of a high-pass), averaged over channels, sign-flipped for ERD so "higher = key down".
4. **Key-down detection**: Otsu's method finds the threshold between the rest and active states for each recording; a hysteresis band stops chatter; short dropouts are bridged and blips dropped. Key-downs touching the recording edges are ignored (filter edge effects).
5. **Timing**: dot and dash clusters give the unit *u* and a detector bias *b* (detected key-downs run long by *b*, gaps short by *b*). Dash if longer than 2u + b; new letter if the gap exceeds 2u − b; new word above 5u − b. Key-downs shorter than 0.4u are noise.
6. **Morse → English**: ITU table with digits and punctuation; `SOS` prosign; eight dots = "error" (erases the word). Invalid codes are repaired (two letters sent without a gap are split; one wrong element maps to the nearest letter) and flagged in the report; `--no-correct` shows `?` instead.
7. **Quality check**: Otsu separability of the activation. Pure noise scores ~0.65; the simulator's movements score 0.78–0.93. Below 0.72 the report warns that the text is probably noise.

### Accuracy on simulated data

`python scripts/benchmark_sim.py` (message `SOS HELP 42`, 20 simulated recordings per row, config from `calibrate` on a separate simulated `PARIS THE QUICK FOX`). CER = character error rate.

| Preset | Dot length | Noise | Offline: exact message | Offline CER | Live: exact message | Live CER |
| --- | --- | --- | --- | --- | --- | --- |
| motor | 1.0 s | 1× | 50% | 8.2% | 30% | 20.5% |
| motor | 1.0 s | 1.5× | 20% | 15.5% | 5% | 31.8% |
| motor | **1.5 s** | 1× | **90%** | **0.9%** | 80% | 3.6% |
| motor | 1.5 s | 1.5× | 70% | 4.5% | 55% | 14.5% |
| clench | 0.3 s | 1× | 100% | 0.0% | 95% | 1.4% |
| clench | 0.3 s | 1.5× | 100% | 0.0% | 100% | 0.0% |
| clench | 0.2 s | 1× | 100% | 0.0% | 40% | 9.5% |
| clench | 0.2 s | 1.5× | 100% | 0.0% | 75% | 3.6% |
| blink | 0.4 s | 1× | 100% | 0.0% | 90% | 1.8% |
| blink | 0.4 s | 1.5× | 100% | 0.0% | 90% | 1.8% |
| blink | 0.3 s | 1× | 100% | 0.0% | 100% | 0.0% |
| blink | 0.3 s | 1.5× | 100% | 0.0% | 95% | 0.9% |

Live is the causal decoder fed in random chunk sizes. Takeaways: `motor` needs ~1.5 s dots and is the weakest path, especially live; `clench` and `blink` are near-perfect offline and live at 0.3 s or slower, but live clench degrades at 0.2 s dots (the live timing estimate occasionally splits a letter), so keep live dots at ≥ 0.3 s.

The simulator (`eeg_morse/simulate.py`) models a 32-channel waveguard layout at 500 Hz with pink background noise, posterior alpha, sensorimotor mu/beta with ERD (0.2 s lag, beta rebound), jaw EMG, eye-closure deflections, spontaneous blinks, slow drift, 60 Hz mains and ±12% human timing jitter. Real single-trial ERD is usually noisier than this, so expect real `motor` accuracy to be lower until calibrated per person.

### What would help next

- A real eego `.cnt` of a person sending a known phrase (and a few seconds of rest), for each movement you plan to use.
- The cap layout and sampling rate (`python -m eeg_morse info file.cnt` prints both), and mains frequency if not 60 Hz.
- Which movement the user will make (hand squeeze, imagined movement, jaw clench, eyes) and which hand.

### Layout

```
eeg_morse/
  config.py     dataclasses + presets (motor, clench, blink)
  io.py         loaders: eego .cnt, .xdf, .edf/.bdf, .npz, .csv
  signal.py     channel picking, CAR, filters, activation envelope
  detect.py     Otsu threshold, hysteresis, key-down intervals
  timing.py     unit + bias estimation, dots/dashes, letter/word gaps
  morse.py      Morse table, encoder, tolerant decoder
  pipeline.py   decode() and calibrate()
  train.py      train() on events labeled in eego: matching, scoring, short/long boundary
  stream.py     causal live decoder, LSL inlet/outlet, replay inlet
  simulate.py   synthetic eego-like recordings (SIMULATED data)
  plot.py       diagnostic figure
  __main__.py   CLI: info, simulate, decode, calibrate, train, live
models/         trained eeg_morse configs + plots from real recordings
scripts/benchmark_sim.py
examples/       simulated recordings, plots, reports, a calibration config
```

## eegmove: two imagined hand movements

`eegmove` reads live EEG from a 24-channel ANT Neuro eego headset and lets someone type by imagining
hand movements, with no visible movement needed. Imagining the left hand is a Morse dot, and imagining the right hand is
a dash. If imagined movement doesn't pass its checks, real movement is the labelled fallback.

This is a prototype, tested on healthy volunteers at most. Nothing here shows that it works for
patients.

```text
eego headset ─ LSL ─> filter ─> align to this person ─> decoder ─> debounce ─ UDP JSON ─> Morse app
                      (same code offline and live)     (pretrained + calibrated)      (only with a GO)
```

### Setup

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

### How it stays accurate on so little data

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

### When it's allowed to type

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

### Workflow

#### Rehearse with no headset

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

#### Record and calibrate

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

### Typing

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

### Building the app

The browser communication app is in `web/`. See the
[SignalSpeak runbook](docs/COMMUNICATION_APP.md) for manual rehearsal,
the UDP-to-WebSocket bridge, live EEG, replay, and Morse integration.

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

### Repo layout

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

## About this repo

**This repo is public.** EEG recordings stay out of git (`.gitignore` covers them), and so do
participant details, passwords and invite links.

### Credits

- PhysioNet EEG Motor Movement/Imagery Dataset: Schalk et al., *IEEE TBME* 51(6), 2004; Goldberger
  et al., *Circulation* 101(23), 2000.
- Shallow ConvNet: Schirrmeister et al., *Human Brain Mapping* 38(11), 2017.
- Euclidean alignment: He & Wu, *IEEE TBME* 67(2), 2020.
- Riemannian tangent-space classification: Barachant et al., *IEEE TBME* 59(4), 2012.

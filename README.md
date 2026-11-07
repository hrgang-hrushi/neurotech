# eeg-morse

Turn movement signals recorded with an **ANT Neuro eego** EEG cap into Morse **dots and dashes**, then into **English**, from a recorded `.cnt` file or live while you send.

```
eego cap ──► .cnt file ─┐
         └─► LSL stream ┴─► pick channels ─► filter to movement band ─► activation trace
                                                                          │
   English ◄── Morse table ◄── letters/words ◄── dots/dashes ◄── key-down intervals
```

A short movement is a dot, a long one is a dash, and pauses separate letters and words, exactly like a telegraph key.

## Status: what is real and what is simulated

| Part | State |
| --- | --- |
| Signal processing, detection, timing, Morse decoding | Implemented, unit-tested |
| Offline decoding of files (`decode`) and tuning on a known phrase (`calibrate`) | Implemented, tested on **simulated** recordings |
| Live decoding from eego's LSL stream (`live`) | Implemented; the decoder is tested by replaying simulated data. **Not yet run against a real eego stream** |
| Reading eego `.cnt` files | Uses MNE's ANT reader (`mne.io.read_raw_ant`); **not yet run on a real eego file** |
| Accuracy on real people | **Unknown until we run real recordings.** All numbers below come from the simulator. |

When demoing, label simulated output as simulated.

## Quick start

```bash
pip install -r requirements.txt          # or: pip install -e ".[all]"

# 1. no cap needed: make a simulated recording and decode it
python -m eeg_morse simulate "HELLO WORLD" --preset clench --out hello.npz
python -m eeg_morse decode hello.npz --preset clench --plot hello.png --json hello.json

# 2. replay it as if it were live
python -m eeg_morse live --replay hello.npz --preset clench --speed 1

# 3. real data from eego
python -m eeg_morse info session.cnt                      # see your cap's channel labels
python -m eeg_morse calibrate calib.cnt --preset motor --expect PARIS --out me.json --plot calib.png
python -m eeg_morse decode session.cnt --config me.json --plot session.png
python -m eeg_morse live --config me.json --markers       # eego must be streaming over LSL
python -m pytest                                           # 32 tests, ~10 s
```

`decode` prints the Morse and the English, and can save a JSON report and a diagnostic plot (raw band signal → activation with thresholds → dots/dashes → letters, with every letter traceable to the EEG that produced it).

## Using it with eego

**Recorded files.** Record normally in eego; the `.cnt` loads with `pip install mne antio` (MNE ≥ 1.9). eego annotations come through as events. `.xdf` (LabRecorder), `.edf/.bdf`, `.npz` and `.csv` also load.

**Live.** In the eego software tick **Enable LSL EEG streaming**. `live` finds the first LSL stream of type EEG (or `--stream-name`). With `--markers`, decoded letters are published as an LSL marker stream; if eego's network events are enabled (Application options → Network Operation) they are recorded into the `.cnt` next to the EEG.

Live sessions start with **~6 s of rest** to learn the baseline. With a calibration config, decoding starts immediately. Without one, send a short warm-up (e.g. `PARIS`) until the terminal says `locked`; anything sent before then is not decoded.

## Choosing the movement (presets)

| Preset | What the person does | What the cap sees | Suggested dot length |
| --- | --- | --- | --- |
| `motor` (default) | squeeze / move the right hand (or imagine it) | mu/beta (8–30 Hz) power **drops** over C3/Cz/C4 (ERD) | **≥ 1.5 s** |
| `clench` | clench the jaw | broadband muscle (EMG) power on T7/T8 | 0.3 s (0.2 s offline only) |
| `blink` | close the eyes (short = dot, held = dash) | large slow deflection on Fp1/Fp2 | 0.3–0.4 s |

`motor` is the "brain signal" path and the hardest: the ERD is slow (~0.5 s lag) and weak on single trials, so it needs long, steady units. `clench` and `blink` are artifacts rather than cortical signals, but they are very reliable switches and make a good fallback or second channel for a demo. Any preset can be overridden: `--channels C4,FC2,CP2` (left-hand mover), `--band 8 30`, `--direction decrease|increase`, `--unit 1.5`, `--line-freq 50` (outside the Americas).

## Calibration protocol (recommended for every person and session)

1. Cap on, impedances checked. Start recording, sit still **8–10 s**.
2. Send a known phrase at a steady pace, e.g. `PARIS` (contains dots, dashes, letter gaps). For `motor`, aim for 1.5 s dots, 4.5 s dashes, 1.5 s gaps inside a letter, 4.5 s between letters.
3. Rest a few seconds, stop recording.
4. `python -m eeg_morse calibrate calib.cnt --preset motor --expect PARIS --out me.json --plot calib.png`

Calibration checks that the phrase decodes, picks between all preset channels / the best 3 / the single best (so a left-hand mover gets C4 without asking), tunes smoothing and hysteresis, and saves the unit and thresholds for live mode. It only departs from the preset when that is a clear and stable improvement; in testing, tuning freely on one short phrase overfit and hurt other recordings.

## How it works

1. **Channels and reference**: pick the preset's channels (missing ones are skipped), subtract the common average of all scalp channels.
2. **Filter**: notch mains (60 Hz default), band-pass to the movement band. Offline is zero-phase; live is causal.
3. **Activation**: log band power (or smoothed amplitude for eye closures, with a rolling-percentile baseline instead of a high-pass), averaged over channels, sign-flipped for ERD so "higher = key down".
4. **Key-down detection**: Otsu's method finds the threshold between the rest and active states for each recording; a hysteresis band stops chatter; short dropouts are bridged and blips dropped. Key-downs touching the recording edges are ignored (filter edge effects).
5. **Timing**: dot and dash clusters give the unit *u* and a detector bias *b* (detected key-downs run long by *b*, gaps short by *b*). Dash if longer than 2u + b; new letter if the gap exceeds 2u − b; new word above 5u − b. Key-downs shorter than 0.4u are noise.
6. **Morse → English**: ITU table with digits and punctuation; `SOS` prosign; eight dots = "error" (erases the word). Invalid codes are repaired (two letters sent without a gap are split; one wrong element maps to the nearest letter) and flagged in the report; `--no-correct` shows `?` instead.
7. **Quality check**: Otsu separability of the activation. Pure noise scores ~0.65; the simulator's movements score 0.78–0.93. Below 0.72 the report warns that the text is probably noise.

## Accuracy on simulated data

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

## What would help next

- A real eego `.cnt` of a person sending a known phrase (and a few seconds of rest), for each movement you plan to use.
- The cap layout and sampling rate (`python -m eeg_morse info file.cnt` prints both), and mains frequency if not 60 Hz.
- Which movement the user will make (hand squeeze, imagined movement, jaw clench, eyes) and which hand.

## Layout

```
eeg_morse/
  config.py     dataclasses + presets (motor, clench, blink)
  io.py         loaders: eego .cnt, .xdf, .edf/.bdf, .npz, .csv
  signal.py     channel picking, CAR, filters, activation envelope
  detect.py     Otsu threshold, hysteresis, key-down intervals
  timing.py     unit + bias estimation, dots/dashes, letter/word gaps
  morse.py      Morse table, encoder, tolerant decoder
  pipeline.py   decode() and calibrate()
  stream.py     causal live decoder, LSL inlet/outlet, replay inlet
  simulate.py   synthetic eego-like recordings (SIMULATED data)
  plot.py       diagnostic figure
  __main__.py   CLI: info, simulate, decode, calibrate, live
tests/          32 tests (Morse, timing, detection, offline, live, CLI)
scripts/benchmark_sim.py
examples/       simulated recordings, plots, reports, a calibration config
```

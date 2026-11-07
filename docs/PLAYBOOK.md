# Rotation playbook

Thirty minutes goes fast, and the net takes time to prepare. Decide who does what before walking in.

## Before the first recording

The ANT network may have no internet, so anything missing now can't be fixed at the station.

- [ ] `uv run eegmove doctor` passes on **every laptop going to the station**
- [ ] One person is the participant: someone comfortable sitting still, ideally the same person all weekend
- [ ] Everyone has tried the cue screen and `uv run eegmove type --simulate`
- [ ] One person is the hand watcher, who stays beside the participant during imagined cues
- [ ] Bring a USB drive for the export, and a USB-C adapter if the laptop needs one
- [ ] Ask ANT the open questions in [CHALLENGE.md](CHALLENGE.md#still-unknown-ask-ant)

## The target movements

We record **rest, left hand and right hand**, because Morse needs two symbols and nothing more. Hand
movement produces well-known changes over the motor cortex (C3 and C4), and PhysioNet has both real
and imagined versions of it to pretrain on.

The main dataset is **imagined** movement: the hands stay still. A shorter block of **real** movement
is the fallback. **Ask ANT whether imagined movement counts as the track's core input.**

## The recording sitting (first free rotation)

**Goal: leave with two labelled recordings and the real channel list.** The 1:00 PM rotation has
passed, so use the next free one. The two recordings take about 14 minutes together.

1. ANT fits the net. Watch the impedance and ask for help on any motor-area channels above 50 kΩ.
2. Join the ANT network and start the imagined recording:
   ```bash
   uv run eegmove record --mode imagined --per-class 25
   ```
   This finds the stream, prints the labels, then waits for SPACE. **Photograph the labels.**
3. Have ANT start the eego recording too, as a backup.
4. Sit the participant facing the cue screen and press SPACE. A 60-second rest is followed by the cues,
   about 10 minutes in all.
5. During imagined cues the hands stay completely still. **The hand watcher stops the run if a hand
   moves.** Keep the jaw, neck and shoulders loose, and avoid looking around or blinking on purpose.
   Breaks are for fidgeting.
6. Record the fallback, where the hands really move, about 4 minutes:
   ```bash
   uv run eegmove record --mode real --per-class 12 --baseline 30 --blocks 1
   ```
7. Collect the eego export on the USB drive before leaving. Choose EEProbe `.cnt`.

A crash, or a closed window, keeps what was recorded. An existing recording is never overwritten, so
move it first or pass `--out`. If the app died mid-run, look for `imagined.snapshot.npz`, which loads
like any recording.

**If LSL isn't available during rotation 1**, cue with `--no-lsl` and press an eego annotation key
the moment the screen says RELAX, right after the countdown. Then pair the export with the cue log:

```bash
uv run eegmove record --mode imagined --no-lsl
uv run eegmove calibrate recording.cnt --schedule data/recordings/imagined.json
```

The first annotation in the export marks time zero, so only press that key once before the GO.

## Right after recording

```bash
uv run eegmove pretrain --classes rest,left,right --imagined --epochs 15 --heldout 90-109 --montage-from data/recordings/imagined.npz
uv run eegmove calibrate data/recordings/imagined.npz
uv run eegmove calibrate data/recordings/real.npz
```

Pretraining rebuilds the shared model on our real channels. It takes about 30 to 40 minutes by
estimate, so run it outside a rotation. Calibrating fits the decoder to the participant and prints
scores on cues it never saw, including `left_right`. Those need 85% and 70%, and anything near the
printed `chance` value means no signal yet.

## Live check (needs the headset, about 6 minutes per model)

```bash
uv run eegmove check artifacts/session-imagined.joblib
```

This runs 60 seconds of baseline, then 2 minutes of rest, then 20 cues. It decides whether the model
may type, prints why not if it can't, and counts the attempt. If imagined movement gets a NO-GO, check
the fallback the same way:

```bash
uv run eegmove check artifacts/session-real.joblib
```

Treat repeat attempts with suspicion: a truly 70% decoder passes 17 of 20 about 11% of the time, and a
truly 85% decoder fails about 35% of the time. Report the attempt count honestly.

## Live test rotations

```bash
uv run eegmove live               # terminal 1
uv run eegmove type               # terminal 2
```

The first minute is a rest baseline: stay still. Sessions drift when the net is put back on, and
this realigns the model without any labels, so start `live` before you present. Recalibrating makes
a new model, which needs a new check. `type` refuses a decoder running any model or threshold other
than the approved one, and shows which movement it's using.

If `live` or the typing screen warns about a fading signal, stop and ask ANT to check the impedances.

## If the stream won't connect

1. Join the ANT network and confirm you can reach the ANT laptop.
2. In macOS, open System Settings → Privacy & Security → Local Network and allow your terminal app.
3. Copy `lsl_api.cfg.example` to `lsl_api.cfg`, set the ANT laptop's IP, and run from this folder.
4. Check the firewall isn't blocking Python, under System Settings → Network → Firewall.

## Honesty check before judging

ANT's engineers know what motion artifacts look like. Real movement also moves muscles near
electrodes, so a model can score well by detecting jaw, neck or head motion instead of the brain.
Before claiming brain decoding, check that:

- the filter stays at 8–30 Hz, which excludes most eye and muscle activity
- the score holds up when the participant keeps their jaw and neck relaxed
- the model's weight sits over C3 and C4 rather than the edge channels

For imagined movement, also:

- show a camera view of the still hands, and keep the jaw still with no talking while typing
- say plainly that a camera can't rule out tiny muscle tension, and ask ANT whether a forearm EMG on the
  bipolar inputs could
- never claim it works for patients: this is a healthy volunteer and a prototype
- if the real-movement fallback is running, say so. The screen does too

And if any part of the demo is a replay or `--simulate` rather than a live signal, say so. The app
labels both, and neither can earn a GO.

# Rotation playbook

Thirty minutes goes fast, and the net takes time to prepare. Decide who does what before walking in.

## Before 1:00 PM

The ANT network may have no internet, so anything missing now can't be fixed at the station.

- [ ] `uv run eegmove doctor` passes on **every laptop going to the station**
- [ ] One person is the participant: someone comfortable sitting still, ideally the same person all weekend
- [ ] The target movements are decided (see below) and everyone has tried the cue screen
- [ ] Bring a USB drive for the export, and a USB-C adapter if the laptop needs one
- [ ] Ask ANT the open questions in [CHALLENGE.md](CHALLENGE.md#still-unknown-ask-ant)

## Choosing the target movement

The pretrained model only helps if we record what it was trained on. PhysioNet covers **left hand,
right hand, both hands, both feet and rest**. Those are the defaults because hand movement produces
well-known changes over the motor cortex (C3 and C4).

Other movements are fine, such as reaching or walking, but then the pretrained model has less to
offer and we rely on the per-person calibration alone. Pick the movement around the app, and keep it
to 2–4 classes: each extra class gets fewer trials and makes the demo less reliable.

## Rotation 1 (Sat 1:00 PM): collect data

**Goal: leave with a labelled recording, and the real channel list.**

1. ANT fits the net. Watch the impedance and ask for help on any motor-area channels above 50 kΩ.
2. Join the ANT network and test the stream:
   ```bash
   uv run eegmove record --per-class 25 --blocks 3 --out data/recordings/session1
   ```
   This finds the stream, prints the labels, then waits for SPACE. **Photograph the labels.**
3. Have ANT start the eego recording too, as a backup.
4. Sit the participant facing the cue screen and press SPACE. A 60-second rest is followed by the cues.
   With 4 classes this takes about 12 minutes. For a shorter run use `--per-class 15`.
5. During cues: move only what the screen says. Keep the jaw, neck and shoulders loose, and avoid
   looking around or blinking on purpose. Breaks are for fidgeting.
6. Collect the eego export on the USB drive before leaving. Choose EEProbe `.cnt`.

**If LSL isn't available during rotation 1**, cue with `--no-lsl` and press an eego annotation key
the moment the screen says GO. Then pair the export with the cue log:

```bash
uv run eegmove record --no-lsl --out data/recordings/session1
uv run eegmove calibrate recording.cnt --schedule data/recordings/session1.json
```

The first annotation in the export marks time zero, so only press that key once before the GO.

## Right after rotation 1

```bash
uv run eegmove pretrain --montage-from data/recordings/session1.npz
uv run eegmove calibrate data/recordings/session1.npz
```

The first command rebuilds the pretrained model on our real channels, and the second fits the
decoder to the participant and prints a score for each option on cues it never saw. That score is
the number to trust. Treat anything near the printed `chance` value as no signal yet.

## Live test rotations

```bash
uv run eegmove live               # terminal 1
uv run eegmove listen             # terminal 2, or your app
```

The first minute is a rest baseline: stay still. Sessions drift when the net is put back on, and
this realigns the model without any labels. Each visit, record a few more cues if time allows, then
recalibrate with everything gathered so far.

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

And if any part of the demo is a replay rather than a live signal, say so.

# The challenge

Neurotech @ NC State BCI Hackathon, Nov 7–8 2026, Engineering Building 3.
We are **Team 4, ANT Neuro track (blue)**, hacking in **room 2232**. The ANT station is in **room 2201**.

## What we're building

Build a scalable, movement-based everyday-life application. Everyday movement, tracked through
EEG on ANT Neuro's 24-channel eego system, is the core input, and the app has to respond to that
movement in real time. "Scalable" means designed for real use: more headsets, more users,
different movements, broader deployment.

So there are two parts: a decoder (EEG to movement) and an app that does something useful with it.
This repo's decoder sends events over UDP so the two can be built separately.

Our app is Morse typing from **imagined** hand movement, with real movement as a labelled fallback.
See [the feature doc](features/thought-morse.md).

## Deadlines

| When | What |
| --- | --- |
| Sat 11:00 | Hacking begins |
| Sat 1:00 PM | **Our required first rotation: collect our dataset** |
| **Sun 11:45 AM** | **Submission deadline, no exceptions** |
| Sun 12:00–1:15 PM | Judging, teams called to the track room |
| Sun 1:30–2:30 PM | Closing ceremony |

**To submit:** team number, team name, a **public** GitHub repo link, and a downloaded **.pptx**.
The form link is in "ANT Submission Guide" in the shared Drive folder.

**To present:** 3 minutes, in person, **with a live demo**. Cover the technical application and
the impact of the product.

## Team 4 rotations (room 2201, 30 minutes each)

| Day | Time | Purpose |
| --- | --- | --- |
| Sat | **1:00 PM** | Required: collect the dataset |
| Sat | 2:30 PM | First live test |
| Sat | 3:30 PM | Live test |
| Sat | 5:00 PM | Live test |
| Sat | 6:00 PM | Live test |
| Sat | 7:30 PM | Live test |
| Sun | 9:30 AM | Dress rehearsal |
| Sun | 11:00 AM | Last chance, and only 45 minutes before the deadline |

## Hardware facts (from the Drive manuals)

- Amplifier: probably the **EE-511**, the only 24-channel model listed (24 referential + 4 bipolar).
- Sample rates are multiples of 500 or 512 Hz; **500 Hz** is the default.
- Waveguard net: **saline sponges**, soaked 5–15 minutes. Impedance under 50 kΩ, REF and GND under 20 kΩ.
- For cap CA-505 the manual lists REF at Cz and GND at AFz. Whether that's our cap is unconfirmed.
- Export formats: EEProbe `.cnt` (default), Neuroscan `.cnt`, BrainVision, EDF+, ASCII. No BDF.
- Recordings can contain several segments, with impedance checks between them.
- Eego annotations are documented as not meant for precise timing, and the EE-511 trigger input
  has only 2 bits, which is why we run our own cues (see the [playbook](PLAYBOOK.md)).

## Still unknown (ask ANT)

The eego extensions manual, which covers LSL, isn't in the shared folder. These are open:

- The real 24 channel labels, and which electrode is the reference
- LSL stream name and type, sample rate, units, and any extra trigger or counter channels
- Whether we can read LSL during the **first** rotation, not only the later ones
- Whether a hardware or network marker is available, and which annotation keys are set up
- Whether our laptop can join the ANT network on macOS without extra setup
- **Whether imagined movement counts as the track's core input**, since the brief says everyday movement
- Whether the bipolar inputs could carry a forearm EMG, to show the hands really are still

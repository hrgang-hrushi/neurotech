# neurotech

Team 4 entry for the ANT Neuro track at the Neurotech @ NC State BCI Hackathon (Nov 7–8 2026).
Read [docs/CHALLENGE.md](docs/CHALLENGE.md) for the brief and deadlines, and
[docs/PLAYBOOK.md](docs/PLAYBOOK.md) for rotation steps.

Two packages install side by side from one `pyproject.toml` and share nothing at run time:

- `src/eegmove/`: imagined left/right hand decoder (`uv run eegmove --help`).
- `eeg_morse/`: one movement timed like a telegraph key, such as a jaw clench or blink
  (`uv run eeg-morse --help`, or `python -m eeg_morse`). `train` tunes a detector on events
  labeled in eego. Trained configs live in `models/`.

Rules:

- `uv sync`, then `uv run pytest` runs the tests for both packages.
- `eegmove` preprocessing must stay causal and shared between offline and live code.
  `tests/test_signal.py` enforces this, so don't add zero-phase filtering to `src/eegmove/`.
- `eeg_morse` filters zero-phase offline (`decode`, `calibrate`, `train`) and causally only in
  `live`, so its offline scores can be slightly optimistic for live use. Keep that caveat in the
  README when quoting results.
- `eeg_morse` processes each eego pause/resume segment separately. Don't filter across segments.
- Split `eegmove` validation data by cue (`Windows.trial`), never by window, because windows overlap.
- The repo is public: no EEG recordings (`.cnt`, `.evt`, `.seg` and other exports), training plots
  or reports from real recordings, passwords, participant details or invite links. Trained
  `models/*.json` configs are fine.
- Never overwrite or delete the first real clench/blink results: `models/team4_clench.json`,
  `models/team4_blink.json`, and the README section "Results on the first real recording
  (7 Nov 2026)". Save new training runs to new files (for example `models/team4_clench_v2.json`)
  and add new results as a new section next to the old one.
- `ASSUMED_MONTAGE` in `src/eegmove/config.py` is a placeholder until the real channel labels
  are known.

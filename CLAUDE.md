# neurotech

Team 4 entry for the ANT Neuro track at the Neurotech @ NC State BCI Hackathon (Nov 7–8 2026).
Read [docs/CHALLENGE.md](docs/CHALLENGE.md) for the brief and deadlines, and
[docs/PLAYBOOK.md](docs/PLAYBOOK.md) for rotation steps.

- `uv sync`, then `uv run pytest` and `uv run eegmove --help`.
- Preprocessing must stay causal and shared between offline and live code. `tests/test_signal.py`
  enforces this, so don't add zero-phase filtering anywhere.
- Split validation data by cue (`Windows.trial`), never by window, because windows overlap.
- The repo is public: no EEG recordings, passwords, participant details or invite links.
- `ASSUMED_MONTAGE` is a placeholder until the real channel labels are known.

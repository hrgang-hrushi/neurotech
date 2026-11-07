# Plan: thought-movement Morse typing

Run spec: [docs/specs/thought-morse.md](../specs/thought-morse.md). Mode: deep. Line numbers are from
`d446cb6` on branch `thought-morse`. Revised after the critique agent's review.

## Corrections to the run spec's design notes

The frozen P1 and P2 are unchanged. The exploration found that these post-freeze notes can't stand:

| Note | Finding | Plan |
| --- | --- | --- |
| D2 | Message field `t` is wall clock (`live.py:124`), so a stall looks like a gap | Each accepted message adds exactly `step_s` to the typer's clock |
| D4 | A restarted decoder restarts `seq` and would be ignored forever | Add a per-process `run` id, and reset `seq` tracking when `run` changes |
| D5 | `SessionModel.mode` already means net/riemann/ensemble (`models.py:146`) | New attribute `movement`. The CLI flag stays `--mode` |
| D3 | Digits would make `----` and `..--` prefixes of real codes | Letters A-Z only. Longest sequence is 4 symbols |

## Definitions the spec left open

- **Held-out scores.** Both gate scores are window-level on cues never trained on, taken from the single
  decoder `calibrate` selects. They use raw, unrounded values, because `score()` rounds 0.8496 to 0.85.
  Window level is chosen over cue averaging because live decisions come from windows and it gives the
  lower, safer number.
- **Left vs right.** Windows from left and right cues, compared using only the left and right
  probability columns of the deployed three-class model.
- **Three-class.** Balanced accuracy.
- **False activations.** Events during exactly 120 s of clean rest windows. A window rejected by the
  quality gate doesn't count. Zero decisions can't pass. The phase has a 180 s wall-clock deadline, and
  reaching it records NO-GO with the clean time observed, so a dead stream can't hang the check.
- **Correct symbol.** Cues are shuffled, 10 left and 10 right. Each cue is scored over a slot from its
  onset to the next onset, about 9 s, and the last slot ends 9 s after its onset. It's correct only if
  the slot holds exactly one event and that event matches the cue, so a rebound symbol after the cue
  counts as wrong. Onsets are LSL clock times taken when each cue is printed, and events are placed by
  the `lsl_time` of their data, never by arrival time. The inlet is flushed before each phase, and a
  message more than 1 s behind fails its slot.
- **Letter gap.** 3.0 s at rest after the decoder has re-armed. **Word gap:** 7.0 s. The clock advances
  only on messages where `rest` is true, meaning state is idle and rest is the top smoothed class.
  Being released to idle isn't enough, so an uncertain stretch can't finish a letter. It shows UNCERTAIN.
- **Signal strength.** Advisory only, and never part of the verdict. Mu (8-13 Hz) over floor (24-29 Hz)
  power at the hand sites during rest, compared with the person's own baseline, with a warning at a 3 dB
  drop. If no hand pair exists it says so and uses all channels. `eegmove check` prints it.

## Steps

Run `uv run pytest -q` after every step. Commit after steps 1 and 3, so usable code exists early.

### 0. Prepare

- Commit the run spec, feature spec and this plan, so the spec is tracked before code changes.
- In the background, run `uv run eegmove fetch --imagined`. It needs internet, so it must finish before
  the laptop joins the ANT network.

### 1. Recording, first because the next rotation needs it

`config.py`, `record.py`, `datasets.py`, `cli.py`, `.gitignore`.

- `config.py:25`: `DEFAULT_CLASSES` becomes rest, left, right.
- `prompts_for(mode)`, with **the same background and same text size for every class**, so the held-out
  score can't come from screen color.
- `record --mode imagined|real`, required. Default output is `data/recordings/{mode}.npz`.
- Refuse to overwrite an existing recording.
- `write_recording()` atomic via `os.replace`, shared by `save()` and snapshots.
- `Capture.set_session(cues, lsl_t0)` runs at GO. `Capture` then writes `{stem}.snapshot.npz` every 30 s
  on its own thread. `drain()` copies safely, and thread errors are stored.
- `save_once` is idempotent. Close button, Cmd-Q and Ctrl-C all reach it through `WM_DELETE_WINDOW`,
  `tk::mac::Quit`, and `try/finally` around `mainloop`.
- ESC at READY saves nothing, since cue times don't exist yet.
- The npz stores `mode`. The cue log stores `mode` and only cues actually shown.
- `datasets.py`: `recording_movement(path, schedule=None)` reads the npz key or the JSON cue log, and
  returns `unknown` for old files.
- `datasets.py:195-198`: map cue ends through timestamps too, so a drop inside a cue can't label post-cue
  data.
- `.gitignore`: add `*.npz`, `*.joblib`, `*.pt`, `*.verdict.json`.

### 2. Decoder and scoring fixes

- `live.py:46-76` `Debouncer`. `update()` keeps its return shape, so existing callers and tests still
  work. New options `rest_dwell` and `release_after`, with existing defaults unchanged.
  - A non-idle state is assigned only when it fires, so state can't change silently during cooldown.
  - A new symbol can fire only from idle. Going left to right without a return to rest doesn't fire,
    which blocks the rebound symbol. A symbol that starts after rest and is held past cooldown fires when
    cooldown ends.
  - Returning to idle needs `rest_dwell` updates. Low confidence pauses that streak and doesn't reset it.
  - After `release_after` updates with no confident non-idle top class, state returns to idle.
  - `hold()` zeroes the streak on a rejected window.
  - A new attribute `rest_top` is true when rest is the top smoothed class.
  - `LiveSession` will pass `refractory=12`, `rest_dwell=8`, `release_after=16`.
- `live.py:139-142`: delete the inverted `ring_step` and count new samples instead.
- `train.py:68`: when `--imagined` is set, score held-out subjects on imagined runs only.
- `datasets.py:99-106`: add `imagined_only` to `load_physionet`, and extract `_cache_key`.
- `train.py:82-86`: add raw `left_right`, `balanced_raw` and `accuracy_raw` to `score()`.
- `train.py:119-120`: extract `cue_folds(data, folds)`, which validates every partition and tries up to
  ten seeds, so each training side holds every class. If none works, or a class has fewer than 2 cues, it
  stops with a clear error.
- Thread `use_net: bool = True` through `evaluate_session` and `calibrate`. With `False`, the model is
  Riemann only, and `SessionModel` accepts `net=None`.
- `train.py:101-108`, `_finetune`, and `cli.py:146`: calibrate honours `--classes`. If checkpoint classes
  differ, rebuild the head (it's refit anyway). If a requested class has no windows, stop with a clear
  error.

### 3. Morse, word completion and a simulated typing screen

New: `src/eegmove/morse.py`, `src/eegmove/words.py`, `src/eegmove/wordlist.txt`,
`src/eegmove/typing_app.py`. Command: `eegmove type`.

`MorseTyper` with `feed_raw(bytes)`, `feed(message)`, `view()`. `feed` order:

1. Validate. A bad message counts and warns, and never raises.
2. Reject a model or threshold mismatch loudly, before any state changes.
3. Ignore a retired `run`. A new `run` retires the old one and clears the sequence and `seq` tracking.
4. Drop an old `seq`.
5. If not `ok`, stop without advancing the clock.
6. On an event, append the symbol and zero the clock. A 5th symbol clears the sequence and warns.
7. If `rest` is true, add `step_s`. Otherwise zero the clock.
8. At the letter gap, commit once: a letter, `----` deletes, `..--` accepts, anything else warns.
9. At the word gap, add one space, only if text is non-empty and doesn't already end in a space.

Any source other than `eeg` sets a banner. `wordlist.txt` holds about 250 hand-picked common words in rank
order. It sits beside the code because `.gitignore:12` `data/` excludes `src/eegmove/data/`.
`WordList.complete(prefix)` returns the first match, or None for an empty prefix. Accepting replaces the
current word and adds one space, and does nothing with no suggestion.

`typing_app.py`: Tk on the main thread, non-blocking UDP polled with `root.after(30, poll)`. Shows text,
sequence, suggestion, gap bar, movement label and warnings. `--simulate` binds `.` and `-`, sends
`source: "sim"` messages through the same `feed()`, adds a rest message every 250 ms so letters can
finish, and shows SIMULATED INPUT.

### 4. Quality and signal strength: `src/eegmove/quality.py` (new)

`WindowGate(rest_windows, flat_ratio=0.33, burst_ratio=4.0, peak_ratio=12.0)`. The reference is
per-channel median rest RMS, and each channel is also compared with the all-channel median, so a channel
dead during baseline can't pass. Reasons are `nonfinite`, `flat`, `burst`. It works on filtered windows
before whitening, using only the current window (D7). `hand_sites()`, `band_power()` and `SnrMonitor` as
defined above. No fixed microvolt limits, because stream units are unknown.

`preprocess.py`: replace non-finite input with 0 (`nan=0, posinf=0, neginf=0`), so one NaN can't poison
the filter state. `LiveSession` checks raw chunks first and marks the current window dirty until those
samples have left it, passing `clean=False` to `WindowDecider.step`, which reports `nonfinite`.
`load_recording` drops any cue containing non-finite raw samples and prints how many.

### 5. Live refactor: `live.py`

- `WindowDecider(model, whitening, gate, debounce, monitor).step(window, clean=True) -> dict`: pure, with
  no LSL or sockets, so gate tests can drive it.
- `LiveSession(model_path, stream, threshold, step_s, inlet)` with `collect_baseline()` and `decode()`.
- `run_live` becomes a thin loop. Message keeps existing fields and adds `run`, `seq`, `step_s`, `ok`,
  `reason`, `rest`, `source`, `movement`, `model`, `threshold`, `snr_db`, `warning`.
- A rejected window still sends a message with `ok: false`, `event: null` and held state.
- No usable baseline means every window is `ok: false`, `reason: no_baseline`.
- `streaming.py:58-61`: `EegInlet.source` is `replay` for `-replay` source ids, else `eeg`.
- `models.py:143-146`: class-level `movement = "unknown"` and a new trailing argument, so old pickles load
  and count as unknown.

### 6. Verdict: `src/eegmove/verdict.py` (new)

`GoRule`, `session_path(movement)`, `verdict_path(model_path)`, `model_sha1`, pure
`judge(offline, live, movement, rule)`, `save_offline`, `save_live`, `load_verdict` (None on missing,
corrupt or hash mismatch), `Refused`, `Choice`, `choose_model()`.

- NO-GO if movement is unknown, the live part is missing, or the source isn't `eeg`.
- The verdict stores decoder, threshold, debounce values and stream source.
- Attempts are stored per movement in `artifacts/check-attempts.json`, which recalibrating doesn't clear,
  and are always printed.
- `train.py:133-154` `calibrate`: drop gated windows, then call `save_offline`, which clears any live
  result.
- `cli.py` `cmd_calibrate`: read movement with `recording_movement`, with default output by movement.

### 7. Live check: `src/eegmove/check.py` (new), `eegmove check`

`build_check_cues`, `summarize_rest`, `score_cues`, `run_check`. Decodes in-process through `LiveSession`,
so it needs no UDP port. Prints neutral text cues in the terminal, the same for both hands. Prints the
signal-strength figure. A replay source is NO-GO. Rest has the 180 s deadline, and cues use a matching
overall deadline. Takes about 6 minutes per model.

### 8. Gate the typing app

Without `--simulate`, `run_app` calls `choose_model()`, and on `Refused` prints reasons and exits 2 with no
window. `--simulate` skips model selection and opens no UDP socket, so it can't mix with live input, and it
starts with no models or with two NO-GO verdicts. The real model must pass its own `eegmove check` before it
can be the fallback. `live --model` defaults to `choose_model()` and reads the threshold from the verdict. An explicit path or `--threshold`
still works for rehearsal, but the app refuses a mismatched model hash or threshold.

### 9. Doctor: `cli.py:73-74`

Report whether imagined EDFs are on disk.

### 10. Tests

Every test named in the run spec, plus the additions below, written with the step they cover. Shared
helpers go in `tests/synthetic.py`: a strength-controlled generator with non-stationary noise, a `.npz`
writer, and a fake capture. Interpretation notes:

- SNR tests use Riemann only, fixed seeds, and levels far from the bar, and assert the endpoints.
- `test_left_right_score_decides_not_rest` calls `judge` with three-class above 0.70 and left vs right
  below 0.85, because generated rest-only data also fails the 70% bar and would prove nothing.
- `test_flat_window_makes_no_decision` uses 24 channels, a dead channel, and common average reference.
- `test_small_recording_keeps_every_class_in_folds` targets the real failures: a class with one cue and a
  class with no windows, both refused clearly.
- `test_real_imagined_physionet_runs_through_gate` checks for the EDF on disk and never downloads.
- `test_word_list_ships_with_package` builds a wheel into a temp folder with `uv build --wheel` and
  inspects it. It skips only if the build backend is unavailable offline.
- `test_window_close_saves` covers the close button and `tk::mac::Quit` with fake `tk.Tk` and `tk.Label`.
- `test_symbol_during_cooldown_is_not_lost`: left, then rest, then right held into the cooldown fires when
  cooldown ends.

Additions:

| What could go wrong | Test |
| --- | --- |
| Class-colored cues leak into the score | `test_cue_screens_share_one_background` |
| A confidence dip fires a symbol twice | `test_dip_inside_a_hold_does_not_double_fire` |
| A rebound fires the opposite symbol | `test_switching_symbols_needs_rest` |
| A stuck state blocks all typing | `test_stuck_state_releases` |
| A low-confidence hold ends a letter | `test_low_confidence_hold_does_not_end_a_letter` |
| A decoder restart is ignored forever | `test_new_run_resets_sequence_tracking` |
| A gated rest passes with zero decisions | `test_rest_without_clean_windows_is_no_go` |
| No baseline types anyway | `test_no_baseline_fails_closed` |
| A channel dead during baseline passes | `test_channel_dead_at_baseline_is_rejected` |
| Recalibrating keeps an old GO | `test_recalibrating_clears_the_verdict` |
| Repeat attempts vanish | `test_attempts_survive_recalibrating` |
| A different threshold runs under a GO | `test_threshold_must_match_the_verdict` |
| A replay passes the check | `test_replay_source_is_no_go` |
| A rebound symbol counts as correct | `test_extra_event_in_a_slot_counts_as_wrong` |
| The left vs right score uses the wrong columns | `test_score_left_right_uses_only_those_columns` |
| The second recording destroys the first | `test_existing_recording_is_not_overwritten` |
| A 3-class recording crashes on a 4-class checkpoint | `test_calibrate_handles_a_different_class_set` |
| An old model passes as imagined | `test_old_model_counts_as_unknown` |
| A rejected window ends a letter | `test_rejected_window_does_not_advance_the_gap` |
| A simulated letter never finishes | `test_simulated_rest_finishes_a_letter` |
| Uncertainty finishes a letter | `test_uncertainty_longer_than_both_timers_keeps_the_letter_open` |
| A bad sample stays hidden in overlapping windows | `test_nonfinite_samples_reject_until_they_leave_the_window` |
| A recording cue holds bad samples | `test_cue_with_nonfinite_samples_is_dropped` |
| Buffered data lands in the wrong cue | `test_buffered_samples_are_scored_by_acquisition_time` |
| A dead stream hangs the rest phase | `test_stream_with_no_samples_times_out_as_no_go` |
| Endless rejected windows hang the rest phase | `test_endless_rejected_windows_time_out_as_no_go` |
| Simulation needs a model | `test_simulate_starts_with_no_models` |
| Simulation is blocked by two NO-GO verdicts | `test_simulate_starts_with_two_no_go_verdicts` |
| The fallback runs with no check | `test_fallback_needs_its_own_passing_check` |
| Uneven windows lose a class from a fold | `test_folds_keep_every_class_with_uneven_windows` |
| A late packet from an old run replays an event | `test_old_run_packet_after_restart_is_ignored` |

Commands:

```bash
uv run pytest tests/test_snr.py tests/test_gate.py tests/test_morse.py tests/test_record.py tests/test_decoding.py -q
uv run pytest
```

### 11. Docs

- `README.md:3-5, 11-12, 24-29, 54-56, 64-67, 72-80, 97-102`
- `docs/PLAYBOOK.md:11, 17-19, 23, 32-47, 55-61, 65-72, 83-89`. Replace "move only what the screen says"
  for imagined blocks, name a hand watcher, and name the live-test slot for the sitting, since the 1:00 PM
  rotation has passed.
- `docs/CHALLENGE.md:13-14, 58-64`: confirmed in scope. Add the open ANT question.
- `docs/features/thought-morse.md:3`: status.
- `src/eegmove/live.py:1-7`: message docstring.
- `CLAUDE.md`: no change unless execution shows a need.

### 12. Commit and audit

1. Doc-sync sweep, final commit on `thought-morse`.
2. Test break check on `test_noise_only_recording_gets_no_go`, recorded in the run spec.
3. Claude critique loop, then the Codex audit. Fix findings, and record both in the run spec's Results.
4. Never push without approval.

## Verification

1. Both test commands above. `test_real_imagined_physionet_runs_through_gate` must run, not skip, after
   step 0.
2. `git ls-files` shows no EEG data.
3. `uv run eegmove --help` lists `check` and `type`.

The headset check needs the owner, in this order:

```bash
uv run eegmove record --mode imagined --per-class 25
```

```bash
uv run eegmove record --mode real --per-class 12 --baseline 30 --blocks 1
```

```bash
uv run eegmove pretrain --classes rest,left,right --imagined --epochs 15 --heldout 90-109 --montage-from data/recordings/imagined.npz
```

```bash
uv run eegmove calibrate data/recordings/imagined.npz
```

```bash
uv run eegmove calibrate data/recordings/real.npz
```

```bash
uv run eegmove check artifacts/session-imagined.joblib
```

If imagined fails, run the same check on the fallback:

```bash
uv run eegmove check artifacts/session-real.joblib
```

Then start the demo:

```bash
uv run eegmove live
```

```bash
uv run eegmove type
```

## Risks and mitigations

| Risk | Mitigation | Left open |
| --- | --- | --- |
| Screen differences fake a score | One cue background; neutral terminal cues in `check` | Non-motor effects could remain |
| False GO from small samples | Exact pass counts, attempts visible | 17/20 passes a true 70% decoder about 11% of the time, and fails a true 85% decoder about 35% of the time |
| Same-session scoring is optimistic | Live check is required | No last-block hold-out in this build |
| Real movement contaminates imagined data | Hand watcher, camera, jaw still | Tensing is invisible without EMG. Ask ANT about the bipolar inputs |
| `proc_dejitter` may hide dropped samples | Loader test | Needs the headset |
| Beta rebound fires the opposite symbol | A return to rest is required between symbols | Post-cue windows aren't in training |
| Both models NO-GO | App refuses | `--simulate` is an honest labeled backup, not a live demo |
| Speed below the P1 estimate | Short demo words | About 6-8 s per symbol by estimate, so about 3 letters a minute |
| Imagined pretrain is long | Run outside a rotation | About 30-40 min by estimate |
| `pretrain` needs channel labels from a recording | Record first, pretrain after | Pretraining can't happen before the first sitting |

## Codex plan review

Review file: [2026-11-07_thought-morse-plan-review.md](2026-11-07_thought-morse-plan-review.md).

| Finding | Resolution |
| --- | --- |
| Low confidence can still finish a letter | Clock needs `rest` true, not just idle |
| Non-finite samples are lost before the gate | Live window marked dirty; recording cues dropped |
| Live check has no acquisition-time rule | Scored by LSL time, inlet flushed, late messages fail |
| Clean-rest check can hang | 180 s deadline records NO-GO |
| `--simulate` conflicts with gating | Bypasses selection and opens no UDP socket |
| Fallback can't qualify | Real model gets its own `check` |
| Folds may lack a class | Every partition validated, with retries |
| Late packets from a retired run | Retired runs ignored; model checked before state changes |
| Package test only checks the checkout | Test builds and inspects a wheel |

## Cut after critique

Offline `erd_report`, checkpoint renaming, verdict age display, doctor window and word-list checks, and half
the word list.

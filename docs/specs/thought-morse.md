# Run spec: thought-movement Morse typing

**Stakes:** HIGH — changes what the model is trained on and how its output becomes text.

**Mode:** freeze deep. **Branch:** `thought-morse`. Frozen after commit.

## Owner's statement

### P1

- **What it does (first attempt):** this plan plugs us into an eeg data and sees when we move your hand and corresponds to a dot and a dash
- **What it does (revised):** sees when you think about moving hand whether it perceptibly moves or not is unimportant
- **Most likely way it is wrong:** this goes wrong if this faint signal is lost in noise

### P2

- **What it does (first attempt):** these test prove the accuracy of the model and make sure there is not leakage between classifications im not sure about it beyond this
- **What it does (revised):** these are reliability checks for the model if it's just signal it can refuse if making sure the decoder codes correctly to letters and the app avoids garbage and we also build in a allowed reject if it doesn't pickup anything
- **Most likely way it is wrong:** this fails if the signal to noise ratio is too low we need lots of testing around that

Reading note, not part of the statement: the agent read "just signal" as "just noise" and told the owner before the freeze.

## P1 (frozen)

### Conventions

- Branch off `main`, created before any commit.
- Docs: `docs/specs/`, `docs/features/`, `docs/reports/`.
- Living docs: `README.md`, `docs/CHALLENGE.md`, `docs/PLAYBOOK.md`.
- Tests: `uv run pytest`. No bug log, so the historical bug sweep draws on this session's record.
- Codex scripts: global `~/.claude/review-plan.sh` and `~/.claude/review-audit.sh`.

### Problem

Typing with real hand movement adds nothing over a keyboard for someone with working hands. EEG only
adds value if it responds to a movement attempt that a keyboard or camera can't see.

### Approach

- The decoder responds to the thought of moving a hand, whether or not the hand visibly moves.
- Imagining the left hand means dot, and imagining the right hand means dash.
- Staying at rest for a set time ends the letter.
- The app shows the current sequence and each finished letter, and has a correction action. A built-in
  word list completes common words offline.
- The demo uses a simple camera view of a still hand, so a judge can see that muscle movement isn't
  producing the text.

### Recording plan

One sitting captures rest and imagined left and right (the main dataset), plus a shorter block of real
left and right (the fallback). Pretraining adds PhysioNet's imagined-movement runs, and the cue screen
gets "imagine" wording.

### Fallback rule

Use imagined movement live only if it clearly beats chance on held-out cues and false activations are
low enough to type. Otherwise the demo uses real movement and says so plainly.

### Decisions carried in

- Stress detection is left out.
- The current decoder stays. JEPA stays out of this first build unless the owner says otherwise.
- No claim that this works for patients. It's a prototype.
- Word suggestions are replaced by word completion.
- Must confirm with ANT: does imagined movement count as the track's core input?

## P2 (frozen)

### Code problems this change fixes

- The debouncer drops a new symbol that arrives during its cooldown.
- The held-out pretraining score only tests real movement, even with `--imagined`.
- The cue screen once exited with no saved file, for an unknown reason.
- The timestamp fix for dropped samples has never been run.

Change from P1: the two recordings are separate files from one sitting, about 14 minutes by estimate,
and the fallback gets its own rest cues.

### Go/no-go rule

| Check | Pass |
| --- | --- |
| Left vs right on held-out cues | at least 85% |
| Rest, left, right on held-out cues | at least 70% |
| False activations during 2 minutes of live rest | at most 0.5 per minute |
| Correct symbols in 20 live cues | at least 17 of 20 |

If imagined movement fails, the app uses the real-movement model and labels it on screen. If both fail,
the app refuses to type.

### Failure modes and tests

**Signal-to-noise (`tests/test_snr.py`, the required owner risk)**

| What could go wrong | Test |
| --- | --- |
| The verdict stays GO as the signal fades | `test_go_verdict_flips_as_snr_falls` |
| A weak but real signal passes the bar | `test_weak_signal_below_bar_gets_no_go` |
| The signal-strength number is wrong | `test_snr_estimate_recovers_known_level` |
| The signal fades mid-session with no warning | `test_low_snr_warns_during_live` |
| The gate only works on made-up data | `test_real_imagined_physionet_runs_through_gate` |

The last test uses local PhysioNet imagined runs and skips if that data is missing. The live check also
prints a signal-strength figure over the hand areas of the motor cortex.

**Noise gate (`tests/test_gate.py`)**

| What could go wrong | Test |
| --- | --- |
| A noise-only recording gets approved | `test_noise_only_recording_gets_no_go` |
| A real signal gets rejected | `test_separable_recording_gets_go` |
| Rest looks good but left and right are guesses | `test_left_right_score_decides_not_rest` |
| Scores exactly on a limit behave wrongly | `test_go_rule_boundaries` |
| False activations are miscounted | `test_check_counts_false_activations` |
| The app starts with no verdict | `test_missing_verdict_refuses_to_start` |
| Failed imagined movement isn't labeled | `test_no_go_uses_real_model_and_labels_it` |
| Both models fail but it types anyway | `test_both_no_go_refuses_loudly` |
| Real and imagined models get mixed up | `test_model_mode_survives_save_and_load` |
| A noise burst types a symbol | `test_noise_burst_makes_no_decision` |
| A dead or flat channel types a symbol | `test_flat_window_makes_no_decision` |
| The noise filter blocks good signal | `test_clean_window_passes_quality_gate` |

**Morse typing and word completion (`tests/test_morse.py`)**

| What could go wrong | Test |
| --- | --- |
| A letter is missing or duplicated | `test_morse_table_is_complete_and_unique` |
| A valid sequence doesn't become its letter | `test_sequence_becomes_letter_after_gap` |
| A letter ends too early | `test_letter_waits_for_the_full_gap` |
| An invalid sequence types something | `test_invalid_sequence_types_nothing` |
| A sequence grows forever | `test_overlong_sequence_is_rejected_at_the_limit` |
| Correction fails | `test_four_dashes_delete_last_letter` |
| Correction crashes on empty text | `test_delete_on_empty_text_is_safe` |
| Spaces double up | `test_word_gap_adds_one_space` |
| A stalled stream ends a letter | `test_stalled_stream_does_not_end_the_letter` |
| Repeated or old messages type twice | `test_duplicate_or_old_message_is_ignored` |
| A bad message crashes the app | `test_malformed_message_is_ignored_loudly` |
| Simulated input looks like real EEG | `test_simulated_input_is_labelled` |
| Wrong word order | `test_common_words_rank_first` |
| No match crashes | `test_no_match_suggests_nothing` |
| Accepting with no suggestion breaks text | `test_accept_without_suggestion_is_safe` |
| It needs internet | `test_word_list_ships_with_package` |

**Decoder events (`tests/test_decoding.py`)**

| What could go wrong | Test |
| --- | --- |
| A symbol is lost during cooldown | `test_symbol_during_cooldown_is_not_lost` |
| A held thought repeats | `test_repeat_requires_return_to_rest` |
| A low-confidence guess fires | `test_low_confidence_fires_nothing` |

**Recording and training (`tests/test_record.py`)**

| What could go wrong | Test |
| --- | --- |
| Cue wording says to move | `test_imagined_prompts_say_keep_still` |
| The recording doesn't store its mode | `test_mode_is_saved_in_recording` |
| A crash loses the session | `test_snapshot_survives_a_crash` |
| Closing the window loses the session | `test_window_close_saves` |
| Dropped samples shift labels | `test_dropped_samples_keep_labels_aligned` |
| Imagined runs aren't used | `test_imagined_runs_are_included` |
| The held-out score tests real movement only | `test_heldout_uses_the_same_runs` |
| Cached data mixes imagined and real | `test_cache_separates_imagined_runs` |
| A short fallback recording loses a class | `test_small_recording_keeps_every_class_in_folds` |

### Commands and acceptance

```bash
uv run pytest tests/test_snr.py tests/test_gate.py tests/test_morse.py tests/test_record.py tests/test_decoding.py -q
uv run pytest
```

- **Pass:** every test passes, including the 22 existing ones. The PhysioNet test may skip only when its
  data is missing.
- **Regression:** any existing test fails, a preprocessing test breaks, or EEG data gets tracked in git.
- **Headset check:** one real run of record, calibrate and live check. This is the only step that
  measures real accuracy.

### Docs

- `docs/specs/thought-morse.md` (new)
- `docs/features/thought-morse.md` (new)
- `docs/reports/2026-11-07_thought-morse-plan.md` (new)
- `README.md`
- `docs/PLAYBOOK.md`
- `docs/CHALLENGE.md` and `CLAUDE.md`: conditional, confirm at execution

**Break-check candidate:** `test_noise_only_recording_gets_no_go`.

**Not covered:** tests can't prove that tiny muscle tenses aren't producing the signal, so someone must
watch the hand during recording.

## Technical spec

Design decisions made after the freeze, within its scope. The plan file refines them.

- **D1. Symbols.** The `left` event is a dot and the `right` event is a dash.
- **D2. Timing uses decoder time.** Letter and word gaps count time in decoder messages, not wall-clock
  time, so a stalled stream can't end a letter.
- **D3. Commands inside Morse.** `----` deletes the last letter and `..--` accepts the word completion.
  Neither is a letter in the table.
- **D4. Message order.** Each UDP message gets a rising sequence number, so a repeated or old message
  is ignored.
- **D5. Mode travels with the data.** The recording, the session model and the verdict all store
  `imagined` or `real`. The app displays the mode.
- **D6. Verdict file.** `calibrate` records the held-out scores. A new `eegmove check` adds the live rest
  and cued-symbol results and writes the final verdict. The typing app refuses to start without a
  passing verdict.
- **D7. Causal only.** Signal strength and window quality use the current data window and the resting
  baseline, with no zero-phase filtering.
- **D8. Out of scope.** Artifact subspace reconstruction, JEPA, typing into other apps, and a camera
  feature. The camera in the demo is a separate phone or laptop view.

## Test break check

Break check: `test_noise_only_recording_gets_no_go` vs `src/eegmove/verdict.py:judge` (left vs right bar
lowered by 0.5, so it can never fail on realistic scores) → CAUGHT. Chosen because it guards the owner's
risk directly. The model still reached NO-GO on the three-class score, and the test failed because it
requires left vs right to be a stated reason. No fix rounds were needed.

## Results

- `uv run pytest`: 177 passed, 0 skipped. `test_real_imagined_physionet_runs_through_gate` ran on local
  imagined data.
- Smoke run on a replayed stream, with a real Tk window and real LSL: `record`, `calibrate`, `check`, `live`
  and `type --simulate` all ran. `check` returned NO-GO, as it should on replay.
- A pre-existing bug surfaced in that run: `eegmove replay` crashed on start because `--run` shadowed the
  command. Fixed, with `test_replay_command_runs`.
- Nothing has run on the real headset, so real accuracy is unmeasured.

Claude critique and Codex audit: to be filled in.

# Thought-movement Morse typing

Status: built, not yet tested on the headset. The run spec is [docs/specs/thought-morse.md](../specs/thought-morse.md).

The user imagines moving a hand. EEG detects the imagined movement, and two imagined movements act as
Morse symbols, so a person can type without visible movement.

| Input | Meaning |
| --- | --- |
| Imagined left hand | dot |
| Imagined right hand | dash |
| No symbol for the letter gap | end of letter |
| No symbol for the word gap | space |
| `----` | delete the last letter |
| `..--` | accept the word completion |

## Go/no-go rule

| Check | Pass |
| --- | --- |
| Left vs right on held-out cues | at least 85% |
| Rest, left, right on held-out cues | at least 70% |
| False activations during 2 minutes of live rest | at most 0.5 per minute |
| Correct symbols in 20 live cues | at least 17 of 20 |

If imagined movement fails, the app uses the real-movement model and says so on screen. If both fail,
the app refuses to type.

This is a prototype, and nothing here shows that it works for patients.

## Timing

| Setting | Value |
| --- | --- |
| Decision step | 0.25 s |
| Between symbols, minimum | 3 s |
| Rest needed to re-arm | 2 s |
| Unconfirmed state released after | 4 s |
| Letter gap | 3 s of rest after re-arming |
| Word gap | 7 s of rest after re-arming |

A new symbol needs a return to rest, which blocks a rebound from firing the opposite symbol. An
uncertain stretch never finishes a letter. Expect about 6 to 8 seconds per symbol by estimate.

## Where it lives

`record.py` captures, `quality.py` rejects bad windows, `live.py` decodes, `verdict.py` and `check.py`
decide who may type, and `morse.py`, `words.py` and `typing_app.py` do the typing. Run `eegmove check`
after every calibration, because a pass belongs to one exact model file.

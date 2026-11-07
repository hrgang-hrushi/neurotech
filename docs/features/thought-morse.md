# Thought-movement Morse typing

Status: planned. The run spec is [docs/specs/thought-morse.md](../specs/thought-morse.md).

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

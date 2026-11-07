# SignalSpeak

SignalSpeak turns decoded movement into Morse text or a selected phrase. The message studio shows both the written Morse and its translation. The signal monitor has a separate LSL feed, so you can see whether EEG samples arrive even before the movement model is calibrated.

## Start the workspace

Install the dependencies before joining the ANT router. It may have no internet.

```bash
uv sync --locked
npm --prefix web ci
npm --prefix web run dev
```

Open the Vite URL using localhost or 127.0.0.1. **Manual test** works without a headset or bridge. Use the dot and dash buttons or the `.` and `-` keys. Pauses or the **End letter** and **End word** buttons commit the sequence. **Speak message** reads the current text. **Auto-speak words** reads each completed valid word when enabled. Speech uses the browser and its available device voices.

## Live EEG

Connect to the ANT network and start the headset's EEG LSL outlet. In separate terminals at the repository root, run the following. Replace `EXACT_LSL_NAME` with the stream name.

```bash
npm --prefix web run bridge -- --source live
uv run eegmove monitor --stream 'EXACT_LSL_NAME'
```

Choose **Live EEG** in the app. Look for **EEG receiving** and check the channel count, sampling rate, waveform, and spectrum. Select **Show all** to view every reported electrode in the current chart mode, or select one electrode for numerical axes and inspection. Freeze holds the displayed data while the status still reports whether new samples arrive.

The monitor streams a rolling two second window. It displays measured waveform extrema with timestamps and estimates one sided power spectral density with Welch's method. The plot uses the stream's declared units when available. A spectrum needs at least one second of usable samples. Frequencies up to 100 Hz retain their bin detail. Higher frequencies may be grouped to fit UDP packets.

To control the app with EEG, run the calibrated movement model as well.

```bash
uv run eegmove live --stream 'EXACT_LSL_NAME'
```

The session status reports the movement decoder independently of EEG telemetry. The built-in Morse decoder uses confirmed **left** events for dots and **right** events for dashes. It translates a letter after 2.6 seconds and closes a word after 5.8 seconds without a symbol. The Phrase board needs one confirmed movement to select the highlighted phrase. Pause, adjust scan speed, undo, or speak the selection from the workspace.

## Recorded replay

Start the recorded stream, monitor, and replay bridge in separate terminals. Choose **Recorded replay** in the app.

```bash
uv run eegmove replay --subject 1 --run 3
uv run eegmove monitor --stream eego-replay --source replay
npm --prefix web run bridge -- --source replay
```

The first command uses a PhysioNet recording and may need internet to download it once. Use `eegmove replay --recording path/to/session.npz` for a local recording. If you have a matching calibrated movement model, run `uv run eegmove live --stream eego-replay` alongside the monitor. The built-in replay outlet is rejected by the live monitor. Source selection and bridge labels should always reflect the actual data used.

## Local transport

| Port | Flow |
| --- | --- |
| UDP 9996 | Monitor → bridge. Per-electrode waveforms, PSD, channel labels, units, and source. |
| UDP 9999 | Movement decoder → bridge. Existing `state`, `event`, `probs`, and `latency_ms` JSON. |
| WebSocket 8765 | Bridge → browser. Separate telemetry and classifier status, channel frames, movements, and Morse updates. |

The WebSocket defaults to `ws://127.0.0.1:8765`. Override it with `VITE_SIGNAL_WS_URL` if you change the local bridge port. `eegmove listen` and the bridge both bind UDP 9999. The bridge, monitor, and decoder belong on the same laptop.

Use `npm --prefix web run bridge -- --source live --morse external` for the teammate's decoder. Send the complete `text` and `pending_symbols` to UDP 9998. Optional fields are `written_morse`, `decoder_state`, and `spoken_word` for one completed word. Backspace and Clear forward `decoder_command` JSON to UDP 9997. The external decoder owns those updates.

## Demo sequence

1. Show the source and connection status. Open the waveform and spectrum for one electrode, then show the full channel gallery.
2. Send a dot and dash and show how the message studio turns them into **A**. Speak the result.
3. Use the Phrase board to show the one movement path to an everyday message.

Use **Manual test** for keyboard input and **Recorded replay** for a recording. The headset and movement model must be exercised together before presenting a live movement demo.

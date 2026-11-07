# SignalSpeak communication app

The app in `web/` turns decoded movement events into selectable spoken phrases. It also
shows text supplied by the separate Morse decoder. The core path needs only one
detectable movement. Morse mode is experimental until short/long events are verified
with real data.

## Run locally

Install dependencies before joining the ANT router, which may have no internet:

```bash
cd web
npm ci
```

Manual test needs no headset or backend:

```bash
npm run dev
```

Open the URL Vite prints. Leave the source on **MANUAL TEST**. In Phrase mode,
wait for the scan outline, then press Space outside a control or use **Trigger
one movement**. Click **Speak message** to hear the selection. Phrase tiles are
clickable only in manual mode. In Morse mode, **Load a labeled sample decoder
event** demonstrates the UI contract; it is explicitly manual data.

## Connect to the existing EEG decoder

The Python decoder publishes JSON over UDP port 9999. Browsers cannot read UDP,
so `web/server/bridge.mjs` forwards it to a local WebSocket. Run these in
separate terminals:

From the repository root, use one terminal for each command:

```bash
(cd web && npm run bridge -- --source live)
uv run eegmove live
(cd web && npm run dev)
```

Select **Live EEG** in the app. The bridge listens on UDP 9999 and WebSocket
8765, both bound to `127.0.0.1`. Run the bridge *instead of* `eegmove listen`,
because both would bind UDP 9999. The app displays **LIVE EEG · OFFLINE** until
the bridge actually receives decoder packets. After 3 seconds without packets,
it shows disconnected.

For recorded LSL replay, restart the bridge with `--source replay`, run
`eegmove replay` and `eegmove live`, then select **Replay** in the app. The
source flag is an operator declaration. Always use the correct setting so
recorded input is never presented as live.

If the UI runs on a different laptop, the current loopback bridge cannot be
reached. Move the app to the decoder laptop or deliberately configure a trusted
local network bridge; do not expose raw EEG or the bridge on a public network.

## Integration contract

The existing decoder sends packets such as:

```json
{"t":12.5,"probs":{"rest":0.1,"left":0.8,"right":0.05,"feet":0.05},"state":"left","event":"left","latency_ms":41.2}
```

The bridge converts these to WebSocket messages:

- `status`: whether EEG packets are arriving.
- `prediction`: state, confidence, and latency.
- `movement_start`: emitted once for a non-null decoder event.
- `movement_end`: emitted when the decoder returns to rest.
- `decoder_update`: forwarded from the Morse teammate's UDP port 9998.

All messages include `type`, `source` (`live` or `replay`), and
`timestamp_ms`. A Morse decoder can send JSON to
`udp://127.0.0.1:9998`:

```json
{"pending_symbols":".-","text":"A","decoder_state":"Ready for next symbol","confidence":0.82}
```

`text` is the complete current composition, not only the newest character.
The UI displays it without running a second Morse decoder. In live or replay
mode, Backspace and Clear send `{"type":"decoder_command","action":"backspace"}`
or `{"type":"decoder_command","action":"clear"}` as UDP to port 9997.
The Morse decoder must receive those commands and publish a fresh
`decoder_update`; the UI waits for that authoritative update. Manual mode edits
its sample text locally. If the teammate's format differs, change the mapping
in `server/bridge.mjs`.

The WebSocket URL defaults to `ws://127.0.0.1:8765`. It can be changed with
`VITE_SIGNAL_WS_URL` at build time. The bridge ports can be changed with
`--eeg-port`, `--morse-port`, `--command-port`, and `--ws-port`.

## Presentation route

1. Show the source badge and connected EEG status.
2. Let the phrase outline reach a useful phrase.
3. Make one movement. Show movement, confidence, and selection.
4. Click **Speak message**.
5. If Morse is verified, switch modes and show actual decoded text. If not,
   keep it labeled experimental.

Speech uses the browser's built-in speech synthesis. A browser without it still
shows the selected message. The app stores no EEG samples or participant data.

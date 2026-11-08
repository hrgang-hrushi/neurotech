"""End-to-end integration verifier for Dot Reader BCI pipeline:
EEG Telemetry (UDP 9996) + Movement Decoder (UDP 9999) -> Bridge -> WebSocket (8765) -> Morse -> Text
"""

import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
import websockets

HOST = "127.0.0.1"
WS_PORT = 8765
EEG_PORT = 9999
TELEMETRY_PORT = 9996

MORSE_TABLE = {
    'S': ['left', 'left', 'left'],      # ...
    'O': ['right', 'right', 'right'],   # ---
}

def create_telemetry_packet(channel="C3", index=0, count=3, sample_rate=500.0, unit="μV"):
    # Generate 1 second of synthetic 10 Hz mu rhythm with 1/f noise
    t = [round(-1.0 + i * 0.01, 5) for i in range(100)]
    values = [round(14.0 * (1.0 if channel == "C3" else 0.8) + (i % 5) * 1.5, 3) for i in range(100)]
    freqs = [float(f) for f in range(2, 46, 2)]
    # Peak at 10Hz (mu rhythm)
    psd = [round(25.0 if f == 10 else 2.0 / (f + 1), 4) for f in freqs]
    return {
        "type": "eeg_channel",
        "source": "replay",
        "stream_id": "test-stream-id",
        "stream_name": "eego-replay",
        "channel": channel,
        "channel_index": index,
        "channel_count": count,
        "sample_rate_hz": sample_rate,
        "unit": unit,
        "waveform": {"time_s": t, "values": values},
        "spectrum": {"frequency_hz": freqs, "power_density": psd},
    }

async def run_verification():
    print("=" * 70)
    print("STARTING E2E BCI PIPELINE VERIFICATION")
    print("=" * 70)

    # 1. Start the WebSocket bridge server
    bridge_path = Path(__file__).parent.parent / "web" / "server" / "bridge.mjs"
    print(f"[1/5] Launching WebSocket bridge: node {bridge_path.name} --source replay...")
    proc = subprocess.Popen(
        ["node", str(bridge_path), "--source", "replay",
         "--eeg-port", str(EEG_PORT), "--telemetry-port", str(TELEMETRY_PORT),
         "--ws-port", str(WS_PORT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    udp_sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    received_events = []

    try:
        # Wait for bridge to start listening
        await asyncio.sleep(0.8)
        ws_url = f"ws://{HOST}:{WS_PORT}"
        print(f"[2/5] Connecting WebSocket client to {ws_url}...")

        async with websockets.connect(ws_url) as ws:
            print("      Connected successfully to bridge WebSocket!")
            # Arm the decoder
            await ws.send(json.dumps({"type": "decoder_command", "action": "arm"}))

            async def listen_ws():
                try:
                    async for raw in ws:
                        msg = json.loads(raw)
                        received_events.append(msg)
                except Exception:
                    pass

            listener_task = asyncio.create_task(listen_ws())

            # 3. Send EEG Telemetry packets for C3, Cz, C4
            print(f"[3/5] Sending EEG telemetry frames (C3, Cz, C4) to UDP {TELEMETRY_PORT}...")
            for idx, ch in enumerate(["C3", "Cz", "C4"]):
                pkt = create_telemetry_packet(channel=ch, index=idx, count=3)
                udp_sender.sendto(json.dumps(pkt).encode(), (HOST, TELEMETRY_PORT))

            # Wait for telemetry to reach WebSocket
            await asyncio.sleep(0.5)
            eeg_frames = [e for e in received_events if e.get("type") == "eeg_frame"]
            assert len(eeg_frames) > 0, "No eeg_frame received over WebSocket!"
            assert len(eeg_frames[0].get("channels", [])) >= 1, "EEG channels missing in eeg_frame!"
            print(f"      PASS: Received {len(eeg_frames)} eeg_frame events containing {len(eeg_frames[0]['channels'])} channels.")

            async def rest_heartbeat(duration_s):
                end_time = time.time() + duration_s
                while time.time() < end_time:
                    rest_pred = {
                        "t": round(time.time(), 3),
                        "source": "replay",
                        "probs": {"rest": 0.95, "left": 0.02, "right": 0.03},
                        "state": "rest",
                        "event": None,
                        "latency_ms": 15.0
                    }
                    udp_sender.sendto(json.dumps(rest_pred).encode(), (HOST, EEG_PORT))
                    await asyncio.sleep(0.2)

            # 4. Stream Morse symbols for 'S', 'O', 'S'
            print("[4/5] Streaming neural movement events: 'S' (...) -> 'O' (---) -> 'S' (...)...")
            message_letters = ['S', 'O', 'S']

            for letter in message_letters:
                movements = MORSE_TABLE[letter]
                print(f"      Sending letter '{letter}' -> movements: {movements}")
                for move in movements:
                    # Send movement start event
                    pred = {
                        "t": round(time.time(), 3),
                        "source": "replay",
                        "probs": {"rest": 0.05, "left": 0.90 if move == "left" else 0.05, "right": 0.90 if move == "right" else 0.05},
                        "state": move,
                        "event": move,
                        "latency_ms": 28.4
                    }
                    udp_sender.sendto(json.dumps(pred).encode(), (HOST, EEG_PORT))
                    await asyncio.sleep(0.2)
                    await rest_heartbeat(0.3)

                # Wait for letter timeout (default letterGapMs is 2.6s in bridge)
                print("      Waiting for letter translation window (2.8s) with rest stream...")
                await rest_heartbeat(2.8)

            # Wait for word timeout (default wordGapMs is 5.8s in bridge)
            print("      Waiting for word translation & vocalization window (6.2s) with rest stream...")
            await rest_heartbeat(6.2)

            listener_task.cancel()

            # 5. Verify received Morse and translated text
            print("[5/5] Auditing decoded text and Morse stream...")
            decoder_updates = [e for e in received_events if e.get("type") == "decoder_update"]
            assert len(decoder_updates) > 0, "No decoder_update events received!"

            latest_update = decoder_updates[-1]
            spoken_word = next((e.get("spoken_word") for e in reversed(decoder_updates) if e.get("spoken_word")), None)
            print(f"      Final text: {latest_update.get('text')!r}")
            print(f"      Final written Morse: {latest_update.get('written_morse')!r}")
            print(f"      Spoken word emitted: {spoken_word!r}")

            assert latest_update.get("text") == "SOS", f"Expected 'SOS', got {latest_update.get('text')!r}"
            assert spoken_word == "SOS", f"Expected spoken_word 'SOS', got {spoken_word!r}"

            print("=" * 70)
            print("ALL PIPELINE CHECKS PASSED: EEG -> UDP -> BRIDGE -> WS -> MORSE -> TEXT -> VOCALIZATION")
            print("=" * 70)
            return True

    finally:
        udp_sender.close()
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

if __name__ == "__main__":
    success = asyncio.run(run_verification())
    sys.exit(0 if success else 1)

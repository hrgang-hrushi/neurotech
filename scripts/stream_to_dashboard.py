#!/usr/bin/env python3
"""Stream realistic EEG telemetry and Morse movement events to the Dot Reader Dashboard.

Usage:
  # Stream default demonstration ('HELLO WORLD' with continuous 500Hz EEG telemetry)
  python scripts/stream_to_dashboard.py

  # Stream a custom message
  python scripts/stream_to_dashboard.py --message "SOS HELP"

  # Stream continuous EEG waveforms only (telemetry without Morse events)
  python scripts/stream_to_dashboard.py --eeg-only
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import time

HOST = "127.0.0.1"
TELEMETRY_PORT = 9996
EEG_PORT = 9999

MORSE_TABLE = {
    'A': '.-',    'B': '-...',  'C': '-.-.',  'D': '-..',   'E': '.',
    'F': '..-.',  'G': '--.',   'H': '....',  'I': '..',    'J': '.---',
    'K': '-.-',   'L': '.-..',  'M': '--',    'N': '-.',    'O': '---',
    'P': '.--.',  'Q': '--.-',  'R': '.-.',   'S': '...',   'T': '-',
    'U': '..-',   'V': '...-',  'W': '.--',   'X': '-..-',  'Y': '-.--',
    'Z': '--..',  '1': '.----', '2': '..---', '3': '...--', '4': '....-',
    '5': '.....', '6': '-....', '7': '--...', '8': '---..', '9': '----.',
    '0': '-----', ' ': ' '
}

def generate_telemetry_frame(t_offset: float, active_movement: str | None = None):
    """Generate 240ms of multi-channel EEG with physiological rhythms (Mu/Beta ERD during movement)."""
    channels = ["C3", "Cz", "C4"]
    rate = 500.0
    n_points = 80
    t_vals = [round(-0.16 + (i / n_points) * 0.16, 5) for i in range(n_points)]

    frames = []
    for idx, name in enumerate(channels):
        # Desynchronization (ERD) on contralateral motor cortex
        is_erd = (active_movement == "left" and name == "C4") or (active_movement == "right" and name == "C3")
        amp_mu = 4.0 if is_erd else 18.0
        amp_beta = 3.0 if is_erd else 8.0

        vals = []
        for i in range(n_points):
            t = t_offset + (i / rate)
            # Mu rhythm (10 Hz) + Beta rhythm (22 Hz) + 1/f noise
            mu = amp_mu * math.sin(2 * math.pi * 10.2 * t + (idx * 0.5))
            beta = amp_beta * math.sin(2 * math.pi * 21.8 * t)
            noise = (math.sin(17.3 * t) + math.cos(31.1 * t)) * 2.5
            vals.append(round(mu + beta + noise, 2))

        # Spectrum
        freqs = [float(f) for f in range(2, 46, 2)]
        psd = []
        for f in freqs:
            if 8 <= f <= 13:
                power = 8.0 if is_erd else 34.0
            elif 18 <= f <= 26:
                power = 4.0 if is_erd else 14.0
            else:
                power = max(0.5, 20.0 / (f + 1))
            psd.append(round(power, 3))

        frames.append({
            "type": "eeg_channel",
            "source": "replay",
            "stream_id": "dot-reader-sim",
            "stream_name": "eego-replay",
            "channel": name,
            "channel_index": idx,
            "channel_count": len(channels),
            "sample_rate_hz": rate,
            "unit": "μV",
            "waveform": {"time_s": t_vals, "values": vals},
            "spectrum": {"frequency_hz": freqs, "power_density": psd},
        })
    return frames

def main():
    parser = argparse.ArgumentParser(description="Stream EEG waveforms and Morse events to Dot Reader")
    parser.add_argument("--message", default="HELLO WORLD", help="Text to spell via Morse")
    parser.add_argument("--eeg-only", action="store_true", help="Only stream EEG waveforms, no Morse events")
    parser.add_argument("--loop", action="store_true", default=True, help="Repeat message continuously")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print("=" * 65)
    print("DOT READER BCI TELEMETRY & MORSE STREAMER")
    print(f"Target: Telemetry UDP {TELEMETRY_PORT} · Movement UDP {EEG_PORT}")
    print(f"Message: {args.message!r}")
    print("=" * 65)

    t_start = time.time()
    try:
        while True:
            for char in args.message.upper():
                if char == ' ':
                    # Space: linger at rest for word translation (6.0s)
                    print("  [Word Gap] Sending rest baseline to trigger word completion...")
                    t_end = time.time() + 6.0
                    while time.time() < t_end:
                        t_now = time.time() - t_start
                        for pkt in generate_telemetry_frame(t_now, None):
                            sock.sendto(json.dumps(pkt).encode(), (HOST, TELEMETRY_PORT))
                        sock.sendto(json.dumps({
                            "t": round(t_now, 3), "source": "replay",
                            "probs": {"rest": 0.95, "left": 0.02, "right": 0.03},
                            "state": "rest", "event": None, "latency_ms": 16.0
                        }).encode(), (HOST, EEG_PORT))
                        time.sleep(0.15)
                    continue

                code = MORSE_TABLE.get(char)
                if not code:
                    continue

                print(f"  Encoding '{char}' -> Morse '{code}'")
                for symbol in code:
                    event = "left" if symbol == '.' else "right"
                    print(f"    Symbol '{symbol}' -> Motor event '{event.upper()}' (contending Mu ERD)")

                    # 1. Send active movement event (250ms)
                    t_event_end = time.time() + 0.25
                    while time.time() < t_event_end:
                        t_now = time.time() - t_start
                        for pkt in generate_telemetry_frame(t_now, event):
                            sock.sendto(json.dumps(pkt).encode(), (HOST, TELEMETRY_PORT))
                        sock.sendto(json.dumps({
                            "t": round(t_now, 3), "source": "replay",
                            "probs": {"rest": 0.08, "left": 0.88 if event == "left" else 0.04, "right": 0.88 if event == "right" else 0.04},
                            "state": event, "event": event, "latency_ms": 24.5
                        }).encode(), (HOST, EEG_PORT))
                        time.sleep(0.12)

                    # 2. Inter-symbol gap (400ms rest)
                    t_rest_end = time.time() + 0.4
                    while time.time() < t_rest_end:
                        t_now = time.time() - t_start
                        for pkt in generate_telemetry_frame(t_now, None):
                            sock.sendto(json.dumps(pkt).encode(), (HOST, TELEMETRY_PORT))
                        sock.sendto(json.dumps({
                            "t": round(t_now, 3), "source": "replay",
                            "probs": {"rest": 0.94, "left": 0.03, "right": 0.03},
                            "state": "rest", "event": None, "latency_ms": 14.0
                        }).encode(), (HOST, EEG_PORT))
                        time.sleep(0.12)

                # Letter gap: wait 2.7s for the letter to translate
                print(f"    [Letter Gap] Waiting for '{char}' to translate...")
                t_letter_end = time.time() + 2.7
                while time.time() < t_letter_end:
                    t_now = time.time() - t_start
                    for pkt in generate_telemetry_frame(t_now, None):
                        sock.sendto(json.dumps(pkt).encode(), (HOST, TELEMETRY_PORT))
                    sock.sendto(json.dumps({
                        "t": round(t_now, 3), "source": "replay",
                        "probs": {"rest": 0.96, "left": 0.02, "right": 0.02},
                        "state": "rest", "event": None, "latency_ms": 12.0
                    }).encode(), (HOST, EEG_PORT))
                    time.sleep(0.15)

            # End of message word completion
            print("  [End of Message] Waiting for final word completion & auto-speak...")
            t_msg_end = time.time() + 6.0
            while time.time() < t_msg_end:
                t_now = time.time() - t_start
                for pkt in generate_telemetry_frame(t_now, None):
                    sock.sendto(json.dumps(pkt).encode(), (HOST, TELEMETRY_PORT))
                sock.sendto(json.dumps({
                    "t": round(t_now, 3), "source": "replay",
                    "probs": {"rest": 0.96, "left": 0.02, "right": 0.02},
                    "state": "rest", "event": None, "latency_ms": 12.0
                }).encode(), (HOST, EEG_PORT))
                time.sleep(0.15)

            if not args.loop:
                break
    except KeyboardInterrupt:
        print("\nStream stopped.")
    finally:
        sock.close()

if __name__ == "__main__":
    main()

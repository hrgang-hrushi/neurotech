"""The typing screen. It listens for decoder messages, or simulates them from the keyboard.

Everything runs on Tk's thread: UDP is polled and never read from a second thread.
"""

from __future__ import annotations

import socket

from .morse import MorseTyper, SimulatedKeys
from .words import load_words

BACKGROUND = "#20242c"
POLL_MS = 30


def drain_socket(sock: socket.socket, typer: MorseTyper, limit: int = 256) -> int:
    """Feed whatever has arrived, without waiting. Returns how many messages were read."""
    count = 0
    while count < limit:
        try:
            data = sock.recv(65536)
        except BlockingIOError:
            break
        typer.feed_raw(data)
        count += 1
    return count


def run_window(typer: MorseTyper, sock: socket.socket | None, simulated: SimulatedKeys | None,
               label: str) -> None:
    import tkinter as tk

    root = tk.Tk()
    root.title("eegmove typing")
    root.configure(bg=BACKGROUND)
    root.geometry("1000x560")

    def line(size: int, color: str = "white") -> tk.Label:
        widget = tk.Label(root, font=("Helvetica", size), fg=color, bg=BACKGROUND, wraplength=940)
        widget.pack(pady=6)
        return widget

    banner = line(22, "#f5b83d")
    text = line(44)
    sequence = line(72)
    suggestion = line(24, "#9fb3c8")
    gap = tk.Canvas(root, width=600, height=14, bg="#343a46", highlightthickness=0)
    gap.pack(pady=8)
    bar = gap.create_rectangle(0, 0, 0, 14, fill="#6fb1ff", width=0)
    warning = line(18, "#f5b83d")
    line(14, "#9fb3c8").configure(text=label)

    def render() -> None:
        view = typer.view()
        banner.configure(text=view.banner or "")
        text.configure(text=view.text + "_")
        sequence.configure(text=view.sequence or " ")
        suggestion.configure(text=f"..-- accepts {view.suggestion}" if view.suggestion else " ")
        gap.coords(bar, 0, 0, 600 * view.gap_fraction, 14)
        warning.configure(text=view.warning or ("UNCERTAIN" if view.uncertain else ""))

    def poll() -> None:
        if sock is not None:
            drain_socket(sock, typer)
        render()
        root.after(POLL_MS, poll)

    def tick() -> None:
        typer.feed(simulated.tick())
        root.after(int(simulated.STEP_S * 1000), tick)

    if simulated is not None:
        def pressed(event) -> None:
            message = simulated.key(event.char)
            if message:
                typer.feed(message)

        root.bind("<Key>", pressed)
        tick()
    poll()
    root.mainloop()


def run_app(host: str = "127.0.0.1", port: int = 9999, letter_gap_s: float = 3.0,
            word_gap_s: float = 7.0, simulate: bool = False) -> int:
    words = load_words()
    if simulate:
        # No socket at all, so simulated keys can never mix with live decoder messages.
        typer = MorseTyper(words, letter_gap_s, word_gap_s)
        run_window(typer, None, SimulatedKeys(), "keys: . is a dot, - is a dash")
        return 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    sock.setblocking(False)
    typer = MorseTyper(words, letter_gap_s, word_gap_s)
    run_window(typer, sock, None, "left hand is a dot, right hand is a dash")
    return 0

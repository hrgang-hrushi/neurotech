"""ASGI entry point for hosting (e.g. Vercel: `entrypoint = "eeg_morse.asgi:app"`).

Locally use `uv run eeg-morse serve`, which binds to 127.0.0.1 only.
"""
from .server import create_app

app = create_app()

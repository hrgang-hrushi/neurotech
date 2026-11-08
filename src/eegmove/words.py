"""Word completion from a small list that ships with the package, so it works offline."""

from __future__ import annotations

from importlib.resources import files


class WordList:
    def __init__(self, words: list[str]):
        self.words = [w.strip().upper() for w in words if w.strip()]  # order is rank

    def complete(self, prefix: str) -> str | None:
        """The most common longer word starting with `prefix`, or None."""
        prefix = prefix.upper()
        if not prefix:
            return None
        return next((w for w in self.words if w.startswith(prefix) and w != prefix), None)


def load_words() -> WordList:
    return WordList(files("eegmove").joinpath("wordlist.txt").read_text().split())

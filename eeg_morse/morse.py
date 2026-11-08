"""International (ITU) Morse code: table, encoder, tolerant decoder."""
from __future__ import annotations

from functools import lru_cache

MORSE: dict[str, str] = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "'": ".----.", "!": "-.-.--",
    "/": "-..-.", "(": "-.--.", ")": "-.--.-", "&": ".-...", ":": "---...",
    ";": "-.-.-.", "=": "-...-", "+": ".-.-.", "-": "-....-", "_": "..--.-",
    '"': ".-..-.", "$": "...-..-", "@": ".--.-.",
}
CODE_TO_CHAR: dict[str, str] = {v: k for k, v in MORSE.items()}

# Prosigns (sent without letter gaps)
SOS_CODE = "...---..."
CODE_TO_CHAR[SOS_CODE] = "SOS"
ERROR_CODE = "........"  # ITU "error": cancel the previous word
# English letter frequency (%), used only to break ties when repairing codes.
FREQ = dict(E=12.7, T=9.1, A=8.2, O=7.5, I=7.0, N=6.7, S=6.3, H=6.1, R=6.0, D=4.3,
            L=4.0, C=2.8, U=2.8, M=2.4, W=2.4, F=2.2, G=2.0, Y=2.0, P=1.9, B=1.5,
            V=1.0, K=0.8, J=0.15, X=0.15, Q=0.1, Z=0.07)
_SINGLE = [c for c, ch in CODE_TO_CHAR.items() if len(ch) == 1]
LETTERS_FIRST = sorted(_SINGLE, key=lambda c: (not CODE_TO_CHAR[c].isalpha(),
                                                -FREQ.get(CODE_TO_CHAR[c], 0.0)))


def encode(text: str) -> list[list[str]]:
    """Text -> words -> letter codes. Unknown characters are skipped."""
    words = []
    for w in text.upper().split():
        codes = [MORSE[ch] for ch in w if ch in MORSE]
        if codes:
            words.append(codes)
    return words


def to_string(words: list[list[str]]) -> str:
    """Conventional notation: letters separated by ' ', words by ' / '."""
    return " / ".join(" ".join(w) for w in words)


def from_string(s: str) -> list[list[str]]:
    return [w.split() for w in s.strip().split("/") if w.split()]


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@lru_cache(maxsize=4096)
def repair(code: str) -> tuple[str, str]:
    """Best guess for an invalid code. Returns (text, how).

    1. A missed letter gap merges two letters (".- -..." -> ".--..."): try
       splitting into two valid letters.
    2. Otherwise the nearest valid code by edit distance (one wrong/missing
       element), preferring letters.
    """
    splits = []
    for i in range(1, len(code)):
        a, b = CODE_TO_CHAR.get(code[:i], ""), CODE_TO_CHAR.get(code[i:], "")
        if len(a) == 1 and len(b) == 1 and a.isalpha() and b.isalpha():
            splits.append((FREQ.get(a, 0) * FREQ.get(b, 0), a + b))
    if splits:
        return max(splits)[1], "split"
    best = min(LETTERS_FIRST, key=lambda c: _lev(code, c))  # stable: frequent letters win ties
    if _lev(code, best) <= max(1, len(code) // 4):
        return CODE_TO_CHAR[best], "nearest"
    return "?", "unknown"


def decode_code(code: str, correct: bool = True) -> tuple[str, str]:
    """One letter code -> (text, status) where status is ok/split/nearest/unknown."""
    if code in CODE_TO_CHAR:
        return CODE_TO_CHAR[code], "ok"
    if not correct:
        return "?", "unknown"
    return repair(code)


def decode(words: list[list[str]] | str, correct: bool = True) -> str:
    if isinstance(words, str):
        words = from_string(words)
    out: list[str] = []
    for w in words:
        letters = []
        for code in w:
            if code.startswith(ERROR_CODE) and set(code) == {"."}:
                if letters:
                    letters = []
                elif out:
                    out.pop()
                continue
            letters.append(decode_code(code, correct)[0])
        if letters:
            out.append("".join(letters))
    return " ".join(out)

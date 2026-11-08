"""Morse-aware word correction (eeg_morse.language)."""
import pytest

from eeg_morse import morse
from eeg_morse.language import GapTiming, correct_words, neighbours


def words_of(text: str) -> list[list[str]]:
    return morse.encode(text)


def merged(*codes_lists: list[str]) -> list[str]:
    return [c for codes in codes_lists for c in codes]


def test_correct_english_is_untouched():
    out = correct_words(words_of("HOW ARE YOU"))
    assert out.upper_text == "HOW ARE YOU" and out.fixes == []


def test_dropped_dot_fixed():
    # COLD with D (-..) heard as N (-.)
    w = words_of("I AM COLD")
    w[2][3] = "-."
    assert correct_words(w).upper_text == "I AM COLD"


def test_dot_dash_swap_fixed():
    # WATER with T (-) heard as E (.)
    w = words_of("I NEED WATER")
    w[2][2] = "."
    assert correct_words(w).upper_text == "I NEED WATER"


LETTER_THR, WORD_THR = 0.6, 1.5  # seconds, as `transcribe` would report for a 0.3 s unit


def timing_for(words: list[list[str]], rushed: dict[tuple[int, int], float] | None = None) -> GapTiming:
    """Clean letter gaps (0.9 s) and word gaps (2.1 s); `rushed` overrides (word, letter) gaps."""
    rushed = rushed or {}
    letter_gaps = [[rushed.get((wi, li), 0.9) for li in range(1, len(w))] for wi, w in enumerate(words)]
    word_gaps = [None] + [2.1] * (len(words) - 1)
    return GapTiming(letter_gaps, word_gaps, LETTER_THR, WORD_THR)


def test_missed_word_gap_is_split_when_pause_was_borderline():
    w = words_of("I NEED WATER")
    obs = [merged(w[0], w[1]), w[2]]
    out = correct_words(obs, timing_for(obs, {(0, 1): 1.4}))  # 1.4 s: almost a word gap
    assert out.upper_text == "I NEED WATER"
    assert out.fixes[0].original == "INEED"


def test_clear_letter_gap_is_not_split():
    # HELLO's letter gaps are all clean, so it is never split into "HE" + "LLO"-style words
    obs = words_of("HELLO")
    assert correct_words(obs, timing_for(obs)).upper_text == "HELLO"


def test_missed_word_gap_with_wrong_letter():
    # NEED WATER sent without the word gap and T (-) heard as E (.)
    w = words_of("NEED WATER")
    joined = merged(w[0], w[1])
    joined[6] = "."
    out = correct_words([joined], timing_for([joined], {(0, 4): 1.3}))
    assert out.upper_text == "NEED WATER"


def test_long_pause_never_merges_words():
    w = words_of("HE LP")
    t = timing_for(w)
    paused = GapTiming(t.letter_gaps, [None, float("inf")], LETTER_THR, WORD_THR)
    assert correct_words(w, paused).upper_text == "HE LP"


def test_spurious_word_gap_is_merged():
    w = words_of("CAN YOU HELP ME")
    help_codes = w[2]
    out = correct_words([w[0], w[1], help_codes[:2], help_codes[2:], w[3]])
    assert out.upper_text == "CAN YOU HELP ME"


def test_missed_letter_gap_inside_word():
    # NEED with E and D merged into one code (. -.. -> .-..), i.e. a missed letter gap
    w = words_of("NEED")
    out = correct_words([["-.", ".", ".-.."]])
    assert out.upper_text == "NEED", w


def test_contraction_gets_apostrophe():
    assert correct_words(words_of("IM COLD")).upper_text == "I'M COLD"
    assert correct_words(words_of("I DONT KNOW")).upper_text == "I DON'T KNOW"


def test_ambiguous_contraction_left_alone():
    assert correct_words(words_of("ITS COLD")).upper_text == "ITS COLD"


def test_sos_kept():
    assert correct_words([[morse.SOS_CODE]]).upper_text == "SOS"


def test_gibberish_left_alone():
    garbage = [["--..--", "-.--.-", "...-..-"]]
    out = correct_words(garbage)
    assert out.fixes == []


def test_neighbours_costs():
    n = neighbours(".-", 1.0)
    assert n[".-"] == 0.0
    assert n["--"] == 1.0  # dot -> dash
    assert n[".|-"] == pytest.approx(0.5)  # inserted letter gap
    assert "|.-" not in n  # never an empty letter


# --- review regressions ----------------------------------------------------------

@pytest.mark.parametrize("text", ["5", "3", "9", "12", "2024", "?", "."])
def test_digits_and_punctuation_never_become_words(text):
    words = [[morse.MORSE[c] for c in text]]
    assert correct_words(words).upper_text == text


def test_numbers_inside_a_sentence_survive():
    assert correct_words(words_of("MEET AT 5 PM")).upper_text == "MEET AT 5 PM"


def test_long_words_are_left_alone_quickly():
    import time
    garbled = [[".-.-", "--.-.", "...-.-", ".-.-", "--.-.", "...-.-", ".-.-", "--.-.", "...-.-",
                ".-.-", "--.-.", "...-.-", ".-.-", "--.-.", "...-.-", ".-.-"]]
    t0 = time.perf_counter()
    correct_words(garbled)
    assert time.perf_counter() - t0 < 1.0


def test_sentence_pause_never_merges_words():
    w = words_of("HE LP")
    t = timing_for(w)
    long_pause = GapTiming(t.letter_gaps, [None, 2.5 * WORD_THR], LETTER_THR, WORD_THR)
    out = correct_words(w, long_pause)
    assert out.upper_text == "HE LP" and out.sentence_starts == [False, True]

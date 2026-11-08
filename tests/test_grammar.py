"""Sentence casing and punctuation (eeg_morse.grammar)."""
import pytest

from eeg_morse import morse
from eeg_morse.grammar import classify, polish
from eeg_morse.language import correct_words


@pytest.mark.parametrize("words, expected", [
    ("HOW ARE YOU", "How are you?"),
    ("CAN YOU HELP ME", "Can you help me?"),
    ("WHERE IS THE DOCTOR", "Where is the doctor?"),
    ("WHAT TIME IS IT", "What time is it?"),
    ("IS IT COLD", "Is it cold?"),
    ("DO YOU HAVE WATER", "Do you have water?"),
    ("I NEED WATER", "I need water."),
    ("THANK YOU", "Thank you."),
    ("I'M COLD", "I'm cold."),
    ("HELP", "Help!"),
    ("HELP ME", "Help me!"),
    ("SOS", "SOS!"),
    ("WHAT A DAY", "What a day!"),
    ("WHY", "Why?"),
    ("WAS GOOD", "Was good."),  # auxiliary without a subject: not a question
])
def test_inferred_punctuation(words, expected):
    assert polish(words.split()).text == expected


def test_keyed_question_mark_wins():
    assert polish(["YOU", "OK?"]).text == "You OK?"


def test_keyed_period_splits_sentences():
    out = polish(["I", "AM", "COLD.", "CAN", "YOU", "HELP"])
    assert out.text == "I am cold. Can you help?"
    assert out.kinds == ["statement", "question"]


def test_long_pause_splits_sentences():
    out = polish(["I", "AM", "COLD", "WHERE", "IS", "MY", "MOM"],
                 [False, False, False, True, False, False, False])
    assert out.text == "I am cold. Where is my mom?"


def test_empty_input():
    assert polish([]).text == ""
    assert classify([]) == "statement"


def test_keyed_punctuation_survives_correction():
    words = morse.encode("ARE YOU OK?")
    corrected = correct_words(words)
    assert corrected.upper_text == "ARE YOU OK?"
    assert polish(corrected.words).text == "Are you OK?"


def test_keyed_comma_does_not_hide_a_question():
    assert polish(["WHAT,", "IS", "IT"]).text == "What, is it?"


def test_stacked_keyed_marks():
    assert polish(["REALLY?!"]).text == "Really!"


@pytest.mark.parametrize("words, expected", [
    ("SEND AN EMAIL TO JOHN", "Send an email to John."),
    ("CREATE A PR AND PUSH IT TO MAIN", "Create a PR and push it to main."),
    ("CAN YOU FIX THIS", "Can you fix this?"),
    ("CALL KEVIN", "Call Kevin."),
])
def test_names_and_acronyms_are_cased(words, expected):
    assert polish(words.split()).text == expected

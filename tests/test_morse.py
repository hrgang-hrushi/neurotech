from eeg_morse import morse


def test_round_trip_letters_digits_punctuation():
    text = "SOS HELP 42 PARIS. WHERE?"
    assert morse.decode(morse.encode(text)) == text


def test_string_notation():
    words = morse.encode("HI THERE")
    assert morse.to_string(words) == ".... .. / - .... . .-. ."
    assert morse.from_string(morse.to_string(words)) == words


def test_unknown_characters_are_skipped_on_encode():
    assert morse.decode(morse.encode("A~B")) == "AB"


def test_repair_merged_letters():
    # ".-" (A) + "-..." (B) sent without a letter gap -> ".--..." is not valid
    text, how = morse.decode_code(".--...")
    assert how == "split" and len(text) == 2


def test_repair_nearest_and_unknown():
    assert morse.decode_code("......-")[1] in ("nearest", "split", "unknown")
    assert morse.decode_code("-.-.-.-.-.-.", correct=False) == ("?", "unknown")


def test_error_prosign_erases_word():
    words = morse.from_string(".... .. / .--. . / ........ / -.-- ---")
    assert morse.decode(words) == "HI YO"


def test_sos_prosign():
    assert morse.decode([["...---..."]]) == "SOS"

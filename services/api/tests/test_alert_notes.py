"""The note text as stored: edges trimmed, line breaks kept, trailing space and control characters removed."""

from app.api.v1.endpoints.alert_notes import clean_body


def test_edges_are_trimmed_lines_kept_and_trailing_space_removed():
    assert clean_body("  Called the user.  \n\nNo answer.   \n") == "Called the user.\n\nNo answer."
    assert clean_body("one\ttwo") == "one\ttwo"


def test_control_characters_are_dropped_and_an_empty_note_is_empty():
    assert clean_body("a\x00b\x07c\x1bd") == "abcd"
    assert clean_body("   \n \t ") == ""
    assert clean_body("") == ""

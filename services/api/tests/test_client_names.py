"""Finding a client by the name a person typed: what counts as the same name, and what must not."""

import pytest
from app.services.client_names import edit_budget, find_clients, normalize

NAMES = {
    "1": "Xstreme MD",
    "2": "Birch Law, PLLC",
    "3": "Waterloo Sparkling Water Corp.",
    "4": "Setpoint",
    "5": "Tecovas",
    "6": "BuildGroup (buildersatx.com)",
}


def ids(typed):
    return [k for k, _ in find_clients(typed, NAMES)]


def test_the_case_that_started_this_xtrememd_finds_xstreme_md():
    assert ids("XtremeMD") == ["1"]
    assert ids("xtreme md") == ["1"]
    assert ids("Xstreme MD") == ["1"]
    assert ids("xstrememd") == ["1"]


def test_case_spaces_and_punctuation_do_not_matter_and_a_part_of_the_name_fits():
    assert ids("BIRCH LAW") == ["2"]
    assert ids("birchlaw pllc") == ["2"]
    assert ids("waterloo sparkling") == ["3"]
    assert ids("buildergroup") == ["6"], "one wrong letter in a long name"
    assert ids("setpoint") == ["4"]


def test_one_slip_is_forgiven_in_a_word_of_five_letters_or_more_and_two_in_nine_or_more():
    assert ids("tecovaz") == ["5"]
    assert ids("tecova") == ["5"]
    assert ids("waterlo sparkling watr") == ["3"], "two slips in a long name"
    assert edit_budget(normalize("abcd")) == 0 and edit_budget(normalize("abcde")) == 1 and edit_budget(normalize("abcdefghi")) == 2


def test_short_words_must_match_exactly_so_nothing_wanders():
    assert ids("zzz") == []
    assert ids("tec") == ["5"], "contained is contained"
    assert ids("tex") == [], "a short word with a wrong letter matches nothing"
    assert ids("") == [] and ids("   ") == [] and ids("!!!") == []


def test_an_exact_name_beats_a_longer_name_that_contains_it_and_several_fits_are_all_returned():
    names = {"a": "Acme", "b": "Acme Dental", "c": "Acme Roofing"}
    assert [k for k, _ in find_clients("acme", names)] == ["a"]
    assert sorted(k for k, _ in find_clients("acme d", names)) == ["b"]
    two = {"b": "Acme Dental", "c": "Acme Dentistry Group"}
    assert sorted(k for k, _ in find_clients("acme dent", two)) == ["b", "c"]


def test_a_wrong_but_different_name_is_not_forced_onto_a_client():
    assert ids("Acme Corporation Holdings") == []
    assert ids("completely different") == []


@pytest.mark.parametrize("typed", ["Xtreme MD", "xtrememd"])
def test_the_match_returns_the_stored_name_not_what_was_typed(typed):
    assert find_clients(typed, NAMES) == [("1", "Xstreme MD")]

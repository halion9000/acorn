"""Matching "name, hourly rate" rows to HaloPSA agents (pure rules)."""

from decimal import Decimal

from app.services import labor_rate_import as lri

AGENTS = [
    {"id": "40", "name": "Alex Caico"},
    {"id": "41", "name": "Alexandra Holt"},
    {"id": "42", "name": "Ben Richard"},
    {"id": "43", "name": "Pat Kim"},
    {"id": "44", "name": "Pat Kim"},  # two agents with one name: never guessed
    {"id": "45", "name": "Braxton Barley"},
    {"id": "", "name": "No Id"},
]


def test_a_rate_is_two_decimals_not_negative_and_at_most_ten_thousand():
    assert [lri.parse_rate(v) for v in ("72.239", "$1,250.5", 55, " 3 ", "0")] == [Decimal("72.24"), Decimal("1250.50"), Decimal("55.00"), Decimal("3.00"), Decimal("0.00")]
    assert [lri.parse_rate(v) for v in ("-1", "10000.01", "abc", "", None, "NaN", "Infinity")] == [None] * 7


def test_a_name_matches_by_the_same_name_or_by_first_and_last_word_and_the_rate_is_kept():
    got, unmatched = lri.match_rates(AGENTS, [("alex  CAICO", "72.2389"), ("Alex Caico", "1"), ("Ben Richard", 60.117), ("Braxton Barley", "37.28")])
    assert {m.agent_id: (m.name, m.rate) for m in got} == {"40": ("Alex Caico", Decimal("1.00")), "42": ("Ben Richard", Decimal("60.12")), "45": ("Braxton Barley", Decimal("37.28"))}, "an agent named twice keeps the last rate"
    assert unmatched == []


def test_first_and_last_word_matching_finds_the_short_name_for_a_long_one():
    got, unmatched = lri.match_rates(AGENTS, [("Alexandra Garcia Holt", "55.59"), ("Braxton J Barley", "37.28"), ("Alexander Leslie Caico", "70")])
    assert sorted((m.agent_id, str(m.rate)) for m in got) == [("40", "70.00"), ("41", "55.59"), ("45", "37.28")]
    assert unmatched == [], "payroll's Alexander Leslie Caico is the agent Halo calls Alex Caico: same last name, a shortened first name"


def test_a_name_that_fits_no_agent_or_several_or_has_no_usable_rate_is_listed_not_guessed():
    got, unmatched = lri.match_rates(AGENTS, [("Pat Kim", "50"), ("Nobody Here", "50"), ("Ben Richard", "free"), ("", "50"), ("No Id", "50")])
    assert got == []
    assert unmatched == ["Pat Kim", "Nobody Here", "Ben Richard", "", "No Id"]


def test_an_exact_match_wins_over_a_first_and_last_word_match():
    agents = [{"id": "1", "name": "Sam Lee"}, {"id": "2", "name": "Sam J Lee"}]
    got, _ = lri.match_rates(agents, [("Sam Lee", "10")])
    assert [(m.agent_id, str(m.rate)) for m in got] == [("1", "10.00")]


def test_alex_caico_is_alexander_caico_and_not_the_other_alexanders():
    people = [
        {"id": "1", "name": "Alexander Caico"},
        {"id": "2", "name": "Cadence Alexander"},
        {"id": "3", "name": "Lake Alexander"},
        {"id": "4", "name": "Alexandra Holt"},
        {"id": "5", "name": "Alex Moreno"},
    ]
    got, unmatched = lri.match_rates(
        people,
        [("Alex Caico", "72.24"), ("Alexander Leslie Caico", "73"), ("Alexandra Garcia Holt", "55.59"), ("Cadence Alexander", "40"), ("Lake Alexander", "41"), ("Alexander", "10"), ("Alex Holt", "1")],
    )
    by = {m.agent_id: str(m.rate) for m in got}
    assert by == {"1": "73.00", "2": "40.00", "3": "41.00", "4": "1.00"}, "Alex Caico and Alexander Leslie Caico are the same person (the last rate given is kept); Alex Holt is Alexandra Holt"
    assert unmatched == ["Alexander"], "a single word fits nobody: said, not guessed"


def test_a_shortening_that_fits_two_people_with_the_same_last_name_is_not_guessed():
    people = [{"id": "1", "name": "Alexander Lee"}, {"id": "2", "name": "Alexandra Lee"}]
    got, unmatched = lri.match_rates(people, [("Alex Lee", "50"), ("Alexandra Lee", "60")])
    assert [(m.agent_id, str(m.rate)) for m in got] == [("2", "60.00")] and unmatched == ["Alex Lee"]

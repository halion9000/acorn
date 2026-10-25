from datetime import date
from types import SimpleNamespace as NS

from app.services.score_history import summary_of_rows, trend


def day(d, score):
    return {"day": date(2026, 10, d), "score": score}


def test_a_score_that_rose_is_better_and_one_that_fell_is_worse_whatever_order_the_days_come_in():
    assert trend([day(3, 80), day(1, 60), day(2, 70)]) == {"first": 60, "last": 80, "change": 20, "direction": "better", "days": 3}
    assert trend([day(1, 90), day(5, 85)])["direction"] == "worse"
    assert trend([day(1, 70), day(2, 70)])["direction"] == "same"


def test_days_without_a_score_are_skipped_and_fewer_than_two_scored_days_is_no_direction():
    assert trend([day(1, None), day(2, 50), day(3, None)]) == {"first": 50, "last": 50, "change": None, "direction": "none", "days": 1}
    assert trend([]) == {"first": None, "last": None, "change": None, "direction": "none", "days": 0}
    assert trend([day(1, None), day(4, 40), day(9, 60)])["first"] == 40


def test_the_stored_checks_make_the_same_score_the_fleet_page_does_and_accepted_ones_are_left_out():
    rows = [
        NS(source="ninjaone", checks=[{"key": "a", "status": "met"}, {"key": "b", "status": "partly"}, {"key": "c", "status": "not_met"}]),
        NS(source="huntress", checks=[{"key": "d", "status": "met"}, {"nokey": 1}]),
    ]
    s = summary_of_rows(rows, set())
    assert (s["score"], s["met"], s["partly"], s["not_met"], s["accepted"]) == (63, 2, 1, 1, 0)  # (1 + .5 + 0 + 1) / 4
    s = summary_of_rows(rows, {"c"})
    assert (s["score"], s["not_met"], s["accepted"]) == (83, 0, 1)  # (1 + .5 + 1) / 3

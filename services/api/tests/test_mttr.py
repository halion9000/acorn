"""MTTR as decided: created to resolved, wall clock, median and 90th percentile, stale sweeps and impossible times left out."""

from datetime import UTC, datetime, timedelta

import pytest
from app.services import mttr

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def pair(hours, stale=False):
    return (T0, T0 + timedelta(hours=hours), T0 if stale else None)


def test_the_figure_is_the_median_and_one_alert_that_sat_for_weeks_does_not_drag_it():
    got = mttr.summarize_pairs([pair(1), pair(2), pair(3), pair(500)])
    assert got.median_hours == 2.5 and got.n == 4
    assert got.p90_hours > 100, "the slow alert shows in the 90th percentile instead"


def test_the_percentile_matches_postgres_linear_interpolation():
    values = [1.0, 2.0, 3.0, 4.0, 10.0]
    assert mttr.percentile(values, 0.5) == 3.0
    assert mttr.percentile(values, 0.9) == pytest.approx(7.6)
    assert mttr.percentile([4.0], 0.9) == 4.0 and mttr.percentile([], 0.5) == 0.0


def test_an_alert_swept_as_stale_a_missing_time_or_a_negative_time_is_not_a_response():
    assert not mttr.is_response(T0, T0 + timedelta(hours=1), T0)
    assert not mttr.is_response(T0, None, None) and not mttr.is_response(None, T0, None)
    assert not mttr.is_response(T0, T0 - timedelta(hours=1), None)
    assert mttr.is_response(T0, T0, None), "answered at once is a response of zero"
    got = mttr.summarize_pairs([pair(2), pair(3, stale=True), (T0, None, None), (T0, T0 - timedelta(hours=5), None)])
    assert (got.median_hours, got.n) == (2.0, 1)


def test_no_responses_is_empty_so_a_page_can_say_so_instead_of_showing_a_made_up_figure():
    assert mttr.summarize_pairs([]) == mttr.EMPTY and mttr.EMPTY.n == 0
    assert mttr.summarize_pairs([pair(1, stale=True)]).n == 0


def sev(severity, hours, stale=False):
    return (severity, T0, T0 + timedelta(hours=hours), T0 if stale else None)


def test_the_breakdown_gives_each_severity_its_own_median_most_severe_first():
    got = mttr.by_severity([sev("low", 10), sev("critical", 1), sev("critical", 3), sev("high", 4), sev("Low", 20), sev("odd", 7)])
    assert [name for name, _ in got] == ["critical", "high", "low", "odd"], "known severities in order, anything else after them"
    figures = {name: (m.median_hours, m.n) for name, m in got}
    assert figures == {"critical": (2.0, 2), "high": (4.0, 1), "low": (15.0, 2), "odd": (7.0, 1)}


def test_the_breakdown_uses_the_same_rule_as_the_tile_and_leaves_out_a_severity_with_nothing_finished():
    rows = [
        sev("critical", 1),
        sev("high", 2, stale=True),
        ("high", T0, None, None),
        ("medium", T0, T0 - timedelta(hours=1), None),
        (None, T0, T0 + timedelta(hours=5), None),
    ]
    got = mttr.by_severity(rows)
    assert [name for name, _ in got] == ["critical", "unknown"]
    everything = mttr.summarize_pairs((c, r, s) for _, c, r, s in rows)
    assert sum(m.n for _, m in got) == everything.n, "every alert the tile counts is in exactly one severity"


def test_the_sentence_is_plain_and_says_nothing_when_there_is_one_severity_or_none():
    two = mttr.by_severity([sev("critical", 1.5), sev("high", 3), sev("high", 3)])
    assert mttr.severity_sentence(two) == "By severity: critical 1.5 h (1), high 3 h (2)."
    assert mttr.severity_sentence(mttr.by_severity([sev("high", 3)])) == ""
    assert mttr.severity_sentence([]) == ""

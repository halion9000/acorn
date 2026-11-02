"""Leafy's AI link: a run of failed questions becomes a warning on the health page and a finding the platform watcher emails; a good answer clears it."""

from datetime import UTC, datetime, timedelta

import pytest
from app.api.v1.endpoints.health import platform_warnings
from app.services.llm_health import FAILURES_IN_A_ROW, llm_status, note_llm_outcome, reset_llm_outcomes
from app.services.platform_watch import evaluate

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean():
    reset_llm_outcomes()
    yield
    reset_llm_outcomes()


def note(minutes_ago: float, ok: bool):
    note_llm_outcome(ok, NOW - timedelta(minutes=minutes_ago))


def test_nothing_asked_lately_or_a_mix_is_not_a_problem():
    assert llm_status(NOW) is None
    note(5, False)
    note(4, False)
    assert llm_status(NOW) is None, "two failures are not yet a run of three"
    note(3, True)
    note(2, False)
    note(1, False)
    assert llm_status(NOW) is None, "a good answer in the last three breaks the run"


def test_three_failures_in_a_row_are_a_problem_and_say_how_many_and_how_long_ago():
    note(20, True)
    for minutes in (9, 6, 3, 1):
        note(minutes, False)
    status = llm_status(NOW)
    assert status is not None
    assert (status["failures"], status["minutes_since"]) == (4, 1)
    assert FAILURES_IN_A_ROW == 3


def test_a_good_answer_after_the_failures_clears_it():
    for minutes in (9, 6, 3):
        note(minutes, False)
    assert llm_status(NOW) is not None
    note(1, True)
    assert llm_status(NOW) is None


def test_old_failures_are_forgotten_after_half_an_hour():
    for minutes in (50, 45, 40):
        note(minutes, False)
    assert llm_status(NOW) is None
    for minutes in (29, 20, 10):
        note(minutes, False)
    assert llm_status(NOW) is not None


def test_the_health_page_warns_as_an_error_and_names_the_likely_causes():
    base = {"down": [], "disk": None, "pending": None, "core_feed": None, "device_feeds": [], "signins": None}
    out = platform_warnings(**base, llm={"failures": 3, "last_failure_at": "x", "minutes_since": 7})
    assert [(w["key"], w["level"]) for w in out] == [("llm", "error")]
    assert "last 3 questions all failed" in out[0]["text"] and "7 minutes ago" in out[0]["text"]
    assert "CORE is running" in out[0]["text"] and "still signed in" in out[0]["text"]
    assert platform_warnings(**base, llm=None) == []


def test_the_platform_watcher_has_a_critical_finding_for_it_and_none_when_fine():
    args = {
        "now": NOW,
        "core_feed_last_report": None,
        "core_feed_sources": 0,
        "connectors": [],
        "connector_silent_after": timedelta(hours=6),
        "disk_free_percent": None,
        "memory_available_percent": None,
    }
    found = evaluate(**args, llm_failing={"failures": 4, "last_failure_at": "x", "minutes_since": 2})
    assert [(f.key, f.severity) for f in found] == [("llm", "critical")]
    assert "last 4 questions all failed" in found[0].message
    assert evaluate(**args) == []
    assert evaluate(**args, llm_failing=None) == []

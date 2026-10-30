"""Rules that have not fired for a long time are listed so they can be tuned or retired."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.api.v1.endpoints.detection_rules import silent_rules

NOW = datetime(2026, 10, 29, tzinfo=UTC)


def rule(name, fired_days_ago=None, created_days_ago=400, status="active"):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        status=status,
        severity="high",
        last_triggered=None if fired_days_ago is None else NOW - timedelta(days=fired_days_ago),
        created_at=NOW - timedelta(days=created_days_ago),
    )


def test_a_rule_is_silent_when_it_last_fired_long_ago_or_never_fired_and_is_old():
    rules = [rule("recent", 5), rule("stale", 120), rule("never-old"), rule("never-new", created_days_ago=10), rule("edge", 90)]
    out = silent_rules(rules, NOW, 90)
    assert [r.name for r in out] == ["never-old", "stale", "edge"]
    assert [r.days_silent for r in out] == [None, 120, 90]


def test_longest_silent_first_ties_by_name_and_a_naive_timestamp_counts_as_utc():
    a, b = rule("b-rule", 200), rule("a-rule", 200)
    n = rule("naive", 150)
    n.last_triggered = n.last_triggered.replace(tzinfo=None)
    n.created_at = n.created_at.replace(tzinfo=None)
    assert [r.name for r in silent_rules([a, b, n], NOW, 90)] == ["a-rule", "b-rule", "naive"]
    assert silent_rules([], NOW, 90) == []

"""Platform Health warns about a connector that is unhealthy and has not synced for over a day."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.api.v1.endpoints.health import failing_connectors, platform_warnings

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def row(name, health="unhealthy", synced_hours_ago=30, enabled=True, created_days_ago=60):
    return SimpleNamespace(
        name=name,
        is_enabled=enabled,
        health_status=health,
        last_sync=None if synced_hours_ago is None else NOW - timedelta(hours=synced_hours_ago),
        created_at=NOW - timedelta(days=created_days_ago),
    )


def test_only_unhealthy_enabled_connectors_quiet_for_over_a_day_are_listed_by_name():
    rows = [
        row("zeta"),
        row("alpha", health="degraded", synced_hours_ago=48),
        row("fresh", synced_hours_ago=2),
        row("fine", health="healthy", synced_hours_ago=500),
        row("off", enabled=False),
        row("setting-up", health="configuring"),
    ]
    assert failing_connectors(rows, NOW) == ["alpha", "zeta"]


def test_a_connector_that_never_synced_counts_from_when_it_was_created():
    assert failing_connectors([row("never", synced_hours_ago=None, created_days_ago=3)], NOW) == ["never"]
    assert failing_connectors([row("new", synced_hours_ago=None, created_days_ago=0)], NOW) == []


def test_a_naive_timestamp_is_read_as_utc():
    r = row("naive")
    r.last_sync = (NOW - timedelta(hours=30)).replace(tzinfo=None)
    assert failing_connectors([r], NOW) == ["naive"]


def _warn(**kw):
    base = {"down": [], "disk": None, "pending": None, "core_feed": None, "device_feeds": [], "signins": None}
    return platform_warnings(**base, **kw)


def test_the_warning_names_up_to_five_and_counts_the_rest_and_is_absent_when_none():
    assert _warn(failing_connectors=[]) == [] and _warn() == []
    text = _warn(failing_connectors=[f"c{i}" for i in range(8)])[0]
    assert text["key"] == "connectors" and text["level"] == "warn"
    assert "c0, c1, c2, c3, c4 and 3 more" in text["text"]

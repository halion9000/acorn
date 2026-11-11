"""What usually happened to earlier alerts of the same kind: counts, ticket share and median time, with a minimum sample."""

from datetime import UTC, datetime, timedelta

from app.services import alert_outcomes as ao

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def row(status="resolved", hours=2.0, ticket=False, disposition=None, stale=None):
    return {
        "status": status,
        "disposition": disposition,
        "has_ticket": ticket,
        "created_at": T0,
        "resolved_at": T0 + timedelta(hours=hours) if hours is not None else None,
        "stale_at": stale,
    }


def test_fewer_than_three_earlier_alerts_is_too_few_and_no_pattern_is_offered():
    assert ao.summarize([]) == {"total": 0, "enough": False, "window_days": 180}
    out = ao.summarize([row(), row()])
    assert out["enough"] is False and "by_status" not in out and "median_hours_to_finish" not in out


def test_counts_by_status_and_disposition_ticket_share_open_ones_and_the_median_hours():
    rows = [
        row("resolved", 1, True, "false_positive"),
        row("resolved", 3, False, "false_positive"),
        row("closed", 8, True, "benign"),
        row("fp", 2),
        row("new", None),
    ]
    out = ao.summarize(rows)
    assert out["total"] == 5 and out["enough"] is True
    assert out["by_status"] == {"resolved": 2, "closed": 1, "fp": 1, "new": 1}
    assert out["by_disposition"] == {"false_positive": 2, "benign": 1}, "an open alert has no disposition counted"
    assert out["still_open"] == 1 and out["with_ticket"] == 2
    assert out["median_hours_to_finish"] == 2.5 and out["timed"] == 4


def test_stale_swept_alerts_and_missing_or_backwards_times_are_left_out_of_the_time_not_the_counts():
    rows = [row(hours=1), row(hours=5), row(hours=9), row(stale=T0, hours=500), row(hours=-3)]
    out = ao.summarize(rows)
    assert out["total"] == 5 and out["timed"] == 3 and out["median_hours_to_finish"] == 5.0
    none_timed = ao.summarize([row(hours=None, status="closed")] * 3)
    assert none_timed["median_hours_to_finish"] is None and none_timed["timed"] == 0

"""The security and work sections of the quarterly business review pack (pure)."""

from datetime import UTC, datetime, timedelta

from app.services import qbr_pack as q

NOW = datetime(2026, 11, 18, tzinfo=UTC)
SINCE = q.period_start(NOW, 3)


def alert(sev, status, days_ago):
    return {"severity": sev, "status": status, "created_at": NOW - timedelta(days=days_ago)}


def test_the_period_is_thirty_day_months_back():
    assert NOW - SINCE == timedelta(days=90)
    assert NOW - q.period_start(NOW, 0) == timedelta(days=30), "at least one month"


def test_security_counts_alerts_in_the_period_handled_ones_and_what_is_open_now():
    alerts = [
        alert("critical", "resolved", 10),
        alert("high", "new", 20),
        alert("low", "fp", 30),
        alert("medium", "closed", 200),  # before the period: not received in it
        alert("high", "in_progress", 400),  # old but still open: counts as open now
    ]
    vulns = [{"severity": "critical", "exploited": True}, {"severity": "low", "exploited": False}]
    s = q.security_section(alerts, vulns, 42, SINCE)
    assert (s["alerts_received"], s["alerts_handled"], s["handled_percent"]) == (3, 2, 67)
    assert s["alerts_received_by_severity"] == {"critical": 1, "high": 1, "medium": 0, "low": 1, "info": 0}
    assert s["alerts_open_now"] == 2 and s["alerts_open_now_by_severity"]["high"] == 2
    assert (s["vulnerabilities_open"], s["vulnerabilities_exploited"], s["devices"]) == (2, 1, 42)


def test_no_alerts_gives_no_percentage_and_work_counts_the_period_only():
    s = q.security_section([], [], 0, SINCE)
    assert s["handled_percent"] is None
    cases = [
        {"created_at": NOW - timedelta(days=5), "closed_at": NOW - timedelta(days=1)},
        {"created_at": NOW - timedelta(days=500), "closed_at": NOW - timedelta(days=490)},
        {"created_at": NOW - timedelta(days=500), "closed_at": None},
    ]
    alerts = [{"status": "resolved", "resolved_at": NOW - timedelta(days=2)}, {"status": "resolved", "resolved_at": NOW - timedelta(days=300)}, {"status": "new", "resolved_at": None}]
    w = q.work_section(cases, alerts, SINCE)
    assert w == {"cases_opened": 1, "cases_closed": 1, "alerts_resolved": 1}


def test_highlights_say_only_what_there_is():
    s = q.security_section([alert("critical", "new", 3)], [{"severity": "high", "exploited": True}], 5, SINCE)
    lines = q.highlights(s, {"cases_opened": 0, "cases_closed": 2, "alerts_resolved": 0})
    assert lines[0].startswith("1 alerts came in and 0 were handled (0%)")
    assert any("1 critical or high alert is still open" in x for x in lines)
    assert any("known to be exploited" in x for x in lines)
    assert any("2 cases closed" in x for x in lines)
    assert q.highlights(q.security_section([], [], 0, SINCE), {"cases_opened": 0, "cases_closed": 0, "alerts_resolved": 0}) == ["No alerts came in during the period."]

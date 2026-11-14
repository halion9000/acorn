"""How healthy a control is from its evidence: healthy, at risk, unhealthy or not tested, and which controls have expired evidence."""

from datetime import UTC, datetime, timedelta

from app.services import compliance_health as ch

NOW = datetime(2026, 11, 14, tzinfo=UTC)


def ago(days):
    return NOW - timedelta(days=days)


def test_a_control_with_recent_accepted_evidence_and_nothing_rejected_is_healthy():
    assert ch.control_state(2, 0, 0, ago(20), NOW) == "healthy"
    assert ch.control_state(1, 3, 0, ago(20), NOW) == "healthy", "pending items beside accepted evidence do not make it worse"


def test_rejected_evidence_makes_a_control_unhealthy_whatever_else_it_has():
    assert ch.control_state(0, 0, 1, None, NOW) == "unhealthy"
    assert ch.control_state(5, 0, 1, ago(10), NOW) == "unhealthy"


def test_only_pending_evidence_or_accepted_evidence_past_a_year_is_at_risk():
    assert ch.control_state(0, 2, 0, None, NOW) == "at_risk"
    assert ch.control_state(1, 0, 0, ago(366), NOW) == "at_risk"
    assert ch.control_state(1, 0, 0, ago(365), NOW) == "healthy"


def test_no_evidence_at_all_is_not_tested():
    assert ch.control_state(0, 0, 0, None, NOW) == "not_tested"


def test_a_framework_is_added_up_over_every_control_it_has_and_lists_the_expired_ones():
    known = {"A": "a", "B": "b", "C": "c", "D": "d", "E": "e"}
    evidence = {
        "A": {"accepted": 1, "pending": 0, "rejected": 0, "newest": ago(5)},
        "B": {"accepted": 1, "pending": 0, "rejected": 0, "newest": ago(400)},
        "C": {"accepted": 0, "pending": 0, "rejected": 2, "newest": None},
        "D": {"accepted": 0, "pending": 1, "rejected": 0, "newest": None},
        "ZZ": {"accepted": 9, "pending": 0, "rejected": 0, "newest": ago(1)},
    }
    out = ch.framework_health(known, evidence, NOW)
    assert out["counts"] == {"healthy": 1, "at_risk": 2, "unhealthy": 1, "not_tested": 1}
    assert out["total"] == 5
    assert out["expired"] == ["B"], "a control the framework does not list is not counted"


def test_percent_healthy_is_none_with_no_controls_and_rounds_otherwise():
    assert ch.percent_healthy({"healthy": 0, "at_risk": 0, "unhealthy": 0, "not_tested": 0}) is None
    assert ch.percent_healthy({"healthy": 25, "at_risk": 14, "unhealthy": 83, "not_tested": 34}) == 16

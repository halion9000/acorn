"""Evidence age: whole days since the newest accepted evidence, the controls past a year, and nothing invented where there is no date."""

from datetime import UTC, datetime, timedelta

from app.services import evidence_age as ea

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def test_age_is_whole_days_and_none_for_no_date():
    assert ea.age_days(NOW - timedelta(days=14, hours=23), NOW) == 14
    assert ea.age_days(NOW, NOW) == 0
    assert ea.age_days(None, NOW) is None
    assert ea.age_days("2026-01-01", NOW) is None


def test_a_date_in_the_future_counts_as_today_and_a_date_with_no_zone_is_read_in_the_same_zone():
    assert ea.age_days(NOW + timedelta(days=3), NOW) == 0
    assert ea.age_days(datetime(2026, 11, 1, 12, 0), NOW) == 10


def test_a_control_is_stale_only_past_a_year_and_the_oldest_age_is_reported():
    out = ea.summarize(
        {
            "B.fresh": NOW - timedelta(days=30),
            "A.old": NOW - timedelta(days=400),
            "C.exactly": NOW - timedelta(days=ea.MAX_AGE_DAYS),
            "D.over": NOW - timedelta(days=ea.MAX_AGE_DAYS + 1),
            "E.none": None,
        },
        NOW,
    )
    assert out == {"stale": ["A.old", "D.over"], "oldest_days": 400}


def test_no_accepted_evidence_at_all_gives_no_age_and_nothing_stale():
    assert ea.summarize({}, NOW) == {"stale": [], "oldest_days": None}
    assert ea.summarize({"X": None}, NOW) == {"stale": [], "oldest_days": None}

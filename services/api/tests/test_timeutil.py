from datetime import UTC, datetime, timedelta, timezone

from app.services.timeutil import as_utc, as_utc_or_none


def test_a_moment_with_no_zone_is_taken_to_be_utc():
    naive = datetime(2026, 10, 29, 12, 0)
    got = as_utc(naive)
    assert got.tzinfo is UTC and got.replace(tzinfo=None) == naive


def test_a_moment_with_a_zone_is_left_exactly_as_it_is():
    plus_two = datetime(2026, 10, 29, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    assert as_utc(plus_two) is plus_two
    aware = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
    assert as_utc(aware) is aware


def test_nothing_stays_nothing():
    assert as_utc_or_none(None) is None
    assert as_utc_or_none(datetime(2026, 1, 1)).tzinfo is UTC

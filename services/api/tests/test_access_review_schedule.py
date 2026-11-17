"""When a self-starting access review is due, its name, due day and next start."""

from datetime import date

from app.services.access_review_schedule import clamp_days, due_date_for, is_due, next_start_after, review_name

D = date(2026, 11, 17)


def test_due_only_when_enabled_and_the_day_has_come():
    assert is_due(D, True, D)
    assert is_due(date(2026, 11, 1), True, D)
    assert not is_due(date(2026, 11, 18), True, D)
    assert not is_due(D, False, D)


def test_next_start_counts_from_the_day_it_started_and_the_interval_is_clamped():
    assert next_start_after(D, 90) == date(2027, 2, 15)
    assert next_start_after(D, 1) == date(2026, 11, 24), "never faster than weekly"
    assert next_start_after(D, 9999) == date(2027, 12, 22), "never slower than 400 days"
    assert clamp_days(90) == 90


def test_name_carries_the_quarter_and_system_and_the_due_day_is_thirty_days_on():
    assert review_name("Microsoft 365", D) == "Q4 2026 access review: Microsoft 365"
    assert review_name("Huntress", date(2027, 1, 1)) == "Q1 2027 access review: Huntress"
    assert due_date_for(D) == date(2026, 12, 17)

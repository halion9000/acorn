"""The review calendar: due states and the plain rule for the next date after a review."""

from datetime import date

from app.services import governance as gov

TODAY = date(2026, 11, 8)


def test_overdue_after_the_date_due_soon_within_14_days_else_ok():
    assert gov.due_state(date(2026, 11, 7), TODAY) == "overdue"
    assert gov.due_state(TODAY, TODAY) == "due soon", "due today is not overdue yet"
    assert gov.due_state(date(2026, 11, 22), TODAY) == "due soon"
    assert gov.due_state(date(2026, 11, 23), TODAY) == "ok"
    assert gov.days_until(date(2026, 11, 3), TODAY) == -5 and gov.days_until(date(2026, 12, 8), TODAY) == 30


def test_a_review_sets_the_next_date_to_today_plus_the_interval_even_when_early():
    assert gov.next_due_after_review(TODAY, 365) == date(2027, 11, 8)
    assert gov.next_due_after_review(TODAY, 90) == date(2027, 2, 6)
    assert gov.next_due_after_review(date(2028, 2, 28), 1) == date(2028, 2, 29), "leap day"

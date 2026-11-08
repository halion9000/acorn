"""The review calendar: when something is due, and the date it is next due after a review.

Dates are plain calendar dates. ``due_state`` is "overdue" once the due date has passed, "due soon" within 14 days, else "ok". Marking something reviewed sets the last-reviewed date to today and the next due
date to today plus its interval: one plain, predictable rule, also when it is reviewed early.
"""

from __future__ import annotations

from datetime import date, timedelta

DUE_SOON_DAYS = 14
KINDS = ("policy", "vendor", "evidence", "other")


def due_state(next_due: date, today: date) -> str:
    if next_due < today:
        return "overdue"
    return "due soon" if (next_due - today).days <= DUE_SOON_DAYS else "ok"


def days_until(next_due: date, today: date) -> int:
    return (next_due - today).days


def next_due_after_review(today: date, interval_days: int) -> date:
    return today + timedelta(days=interval_days)

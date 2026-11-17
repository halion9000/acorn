"""When a self-starting access review is due, what it is called and when it comes next (pure)."""

from __future__ import annotations

from datetime import date, timedelta

DUE_AFTER_DAYS = 30
MIN_DAYS, MAX_DAYS = 7, 400


def clamp_days(days: int) -> int:
    return max(MIN_DAYS, min(MAX_DAYS, days))


def is_due(next_start: date, enabled: bool, today: date) -> bool:
    return enabled and next_start <= today


def next_start_after(today: date, every_days: int) -> date:
    """The next start counted from the day a review actually started, so a late start does not pile up catch-up reviews."""
    return today + timedelta(days=clamp_days(every_days))


def due_date_for(today: date) -> date:
    return today + timedelta(days=DUE_AFTER_DAYS)


def review_name(system: str, today: date) -> str:
    """ "Q4 2026 access review: Microsoft 365"."""
    return f"Q{(today.month - 1) // 3 + 1} {today.year} access review: {system}"

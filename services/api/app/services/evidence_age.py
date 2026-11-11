"""How old a control's newest accepted evidence is, in whole days, and which controls are past the usual audit period.

The Compliance page worked this out in the browser; the same numbers from the API let the report and the digest use them. Only accepted evidence counts: pending or rejected evidence proves nothing yet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# A year, the usual audit period: accepted evidence older than this is worth refreshing.
MAX_AGE_DAYS = 365


def age_days(newest: Any, now: datetime) -> int | None:
    """Whole days since ``newest``; None when it is not a date. A date in the future counts as today."""
    if not isinstance(newest, datetime):
        return None
    if newest.tzinfo is None and now.tzinfo is not None:
        newest = newest.replace(tzinfo=now.tzinfo)
    return max(0, (now - newest).days)


def summarize(newest_by_control: dict[str, Any], now: datetime) -> dict[str, Any]:
    """``newest_by_control``: {control id: when its newest accepted evidence was collected, or None}. The controls past a year (sorted) and the age of the oldest of those newest dates (pure)."""
    ages = {control: age_days(newest, now) for control, newest in newest_by_control.items()}
    known = {control: days for control, days in ages.items() if days is not None}
    return {
        "stale": sorted(control for control, days in known.items() if days > MAX_AGE_DAYS),
        "oldest_days": max(known.values()) if known else None,
    }

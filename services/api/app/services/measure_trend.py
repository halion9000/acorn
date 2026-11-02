"""A measure's trend over a period, from the snapshots recorded for it: one figure per calendar day (UTC), and the summary a progress report shows.

Rules, so the numbers are honest:
* The last snapshot of a day is that day's figure.
* A day with no snapshot repeats the last known figure (the line does not drop to zero because nothing reported).
* The line starts on the first day a figure was recorded inside the period: nothing is invented for earlier days.
* A measure whose latest snapshot is more than ``SILENT_AFTER_DAYS`` days older than the end of the period has stopped being recorded, so it is left out
  rather than shown as a flat line of stale numbers.
A snapshot with no figure (for example a client with no tools has no health score) is not a recording and is skipped.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

SILENT_AFTER_DAYS = 7


@dataclass(frozen=True)
class TrendSummary:
    start: float
    now: float
    change: float
    lowest: float
    highest: float
    last_recorded: date


def _day(moment: datetime) -> date:
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)).astimezone(UTC).date()


def daily_series(points: Iterable[tuple[datetime, float | None]], start_day: date, end_day: date) -> list[tuple[date, float]]:
    """(day, figure) for each day from the first recorded day in the period to ``end_day``; empty when nothing usable was recorded or the measure went silent."""
    last_by_day: dict[date, float] = {}
    for moment, value in sorted((p for p in points if p[1] is not None), key=lambda p: p[0]):
        d = _day(moment)
        if start_day <= d <= end_day:
            last_by_day[d] = float(value)  # type: ignore[arg-type]
    if not last_by_day:
        return []
    if (end_day - max(last_by_day)).days > SILENT_AFTER_DAYS:
        return []
    out: list[tuple[date, float]] = []
    current: float | None = None
    day = min(last_by_day)
    while day <= end_day:
        current = last_by_day.get(day, current)
        out.append((day, current))  # type: ignore[arg-type]
        day += timedelta(days=1)
    return out


def summarise(series: list[tuple[date, float]], last_recorded: date | None = None) -> TrendSummary | None:
    if not series:
        return None
    values = [v for _, v in series]
    return TrendSummary(
        start=values[0],
        now=values[-1],
        change=values[-1] - values[0],
        lowest=min(values),
        highest=max(values),
        last_recorded=last_recorded or series[-1][0],
    )

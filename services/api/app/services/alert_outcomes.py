"""What usually happened to earlier alerts of the same kind: how they ended, how often a ticket was made and how long they took.

"The same kind" is: same client, same exact title, in the last 180 days, not counting the alert being looked at. It reports counts and a median, says how many alerts it is built from, and keeps quiet (a plain "too few") under three, so it
never reads a pattern into one or two cases. Alerts swept as stale are left out of the time, as in the MTTR definition. It only describes; it never closes or advises.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from statistics import median
from typing import Any

MIN_SAMPLE = 3
WINDOW_DAYS = 180
OPEN_STATUSES = ("new", "triaging", "in_progress", "investigating")


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """``rows``: [{status, disposition, has_ticket, created_at, resolved_at, stale_at}] for earlier alerts of the kind (pure)."""
    total = len(rows)
    by_status = Counter(str(r.get("status") or "unknown") for r in rows)
    finished = [r for r in rows if str(r.get("status")) not in OPEN_STATUSES]
    dispositions = Counter(str(r["disposition"]) for r in finished if r.get("disposition"))
    hours: list[float] = []
    for r in finished:
        created, resolved = r.get("created_at"), r.get("resolved_at")
        if r.get("stale_at") is None and isinstance(created, datetime) and isinstance(resolved, datetime) and resolved >= created:
            hours.append((resolved - created).total_seconds() / 3600)
    out: dict[str, Any] = {"total": total, "enough": total >= MIN_SAMPLE, "window_days": WINDOW_DAYS}
    if total < MIN_SAMPLE:
        return out
    out.update(
        {
            "still_open": sum(1 for r in rows if str(r.get("status")) in OPEN_STATUSES),
            "by_status": dict(by_status.most_common()),
            "by_disposition": dict(dispositions.most_common()),
            "with_ticket": sum(1 for r in rows if r.get("has_ticket")),
            "median_hours_to_finish": round(median(hours), 1) if hours else None,
            "timed": len(hours),
        }
    )
    return out

"""How healthy each control is, from the evidence held for it (pure, no database).

A control is **healthy** when it has accepted evidence, none of its evidence was rejected and the newest accepted item is under a year old; **unhealthy** when any of its evidence was rejected; **at risk** when it
has evidence but not enough (only pending, or accepted evidence past a year); **not tested** when there is none. The Compliance dashboard adds these up over the frameworks a person turned on.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services import evidence_age

STATES = ("healthy", "at_risk", "unhealthy", "not_tested")


def control_state(accepted: int, pending: int, rejected: int, newest_accepted: Any, now: datetime) -> str:
    if rejected > 0:
        return "unhealthy"
    if accepted > 0:
        days = evidence_age.age_days(newest_accepted, now)
        return "at_risk" if days is not None and days > evidence_age.MAX_AGE_DAYS else "healthy"
    if pending > 0:
        return "at_risk"
    return "not_tested"


def framework_health(known: dict[str, str], evidence: dict[str, dict[str, Any]], now: datetime) -> dict[str, Any]:
    """``known``: {control id: title}. ``evidence``: {control id: {accepted, pending, rejected, newest}} for the controls that have any.
    Returns the count in each state, and the controls whose accepted evidence is past a year (the dashboard's "evidence expired" items)."""
    counts = dict.fromkeys(STATES, 0)
    expired: list[str] = []
    for control in known:
        e = evidence.get(control, {})
        state = control_state(int(e.get("accepted", 0)), int(e.get("pending", 0)), int(e.get("rejected", 0)), e.get("newest"), now)
        counts[state] += 1
        days = evidence_age.age_days(e.get("newest"), now) if e.get("accepted") else None
        if days is not None and days > evidence_age.MAX_AGE_DAYS:
            expired.append(control)
    return {"counts": counts, "total": len(known), "expired": sorted(expired)}


def percent_healthy(counts: dict[str, int]) -> int | None:
    total = sum(counts.values())
    return round(counts.get("healthy", 0) * 100 / total) if total else None

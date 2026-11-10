"""Time-to-fix targets for a failing client check (Hal accepted these defaults on 2026-11-10).

How long a check may stay NOT MET before it counts as overdue depends on how serious it is: critical 4 hours, high 24 hours, medium 5 days, low 14 days. The seriousness comes from the weight an owner set
for the check (5 critical, 4 high, 3 medium, otherwise low), and a check that raises an alert when it gets worse (``check_alerts.WATCHED``) is at least high. Only a check that is NOT MET and has a known
"since" has a clock; a partly-met check is shown without one.
"""

from __future__ import annotations

from datetime import datetime

from app.services.check_alerts import WATCHED

TARGET_HOURS: dict[str, int] = {"critical": 4, "high": 24, "medium": 5 * 24, "low": 14 * 24}
_ORDER = ("low", "medium", "high", "critical")


def severity_of(key: str, weight: int = 1) -> str:
    """The seriousness of a check (pure)."""
    by_weight = "critical" if weight >= 5 else "high" if weight == 4 else "medium" if weight == 3 else "low"
    if key in WATCHED and _ORDER.index(by_weight) < _ORDER.index("high"):
        return "high"
    return by_weight


def standing(key: str, status: str, since: datetime | None, now: datetime, weight: int = 1) -> tuple[int | None, bool]:
    """(target hours, overdue) for a check: (None, False) when it has no clock (not NOT MET, or no known since)."""
    if status != "not_met" or since is None:
        return None, False
    hours = TARGET_HOURS[severity_of(key, weight)]
    return hours, (now - since).total_seconds() > hours * 3600

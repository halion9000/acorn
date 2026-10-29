"""The alert statuses that mean an alert is finished, in one place.

Eight modules each wrote their own list, and they disagreed: the shift handoff, Leafy's "only open" search, the executive digest and the KPI bar's false-positive rate left out ``false_positive``, ``fp`` or ``suppressed``, so a bulk close as ``false_positive`` showed up as open work and read as 0% false positives.
"""

from __future__ import annotations

SUPPRESSED = "suppressed"

# Both spellings are in use: the alerts API and the bulk close write ``false_positive``, older code and imports write ``fp``.
FALSE_POSITIVE_STATUSES: tuple[str, ...] = ("false_positive", "fp")

# Someone dealt with the alert.
HANDLED_ALERT_STATUSES: tuple[str, ...] = ("resolved", "closed", *FALSE_POSITIVE_STATUSES)

# Nothing is left to do: handled, or hidden by a suppression rule.
FINISHED_ALERT_STATUSES: tuple[str, ...] = (*HANDLED_ALERT_STATUSES, SUPPRESSED)


def is_finished(status: str | None) -> bool:
    return (status or "") in FINISHED_ALERT_STATUSES


def sql_in(statuses: tuple[str, ...]) -> str:
    """``'a','b'`` for a raw SQL ``IN (...)``. Only the constants above are ever passed, never a request value."""
    return ",".join("'" + s.replace("'", "''") + "'" for s in statuses)

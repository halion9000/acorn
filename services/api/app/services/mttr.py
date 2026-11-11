"""MTTR, defined once (decided by Hal, 2026-11-07, "MTTR as proposed").

Three pages used to work it out three ways (a seven-day mean on the dashboard, a window mean on SOC Insights, a per-alert event mean on the SLA page). They now all use this:

 - the clock STARTS when the alert is created in A.C.O.R.N (``created_at``) and STOPS when it is resolved or closed (``resolved_at``), wall-clock time;
 - an alert that was swept away as stale (``stale_at`` set) is NOT a response: it sat untouched and was bulk-closed, so counting it would make a quiet week look slow, and hiding an alert never sets
   ``resolved_at`` at all;
 - the figure is the MEDIAN, with the 90th percentile beside it, because a few alerts that sat for weeks drag a mean far from what a typical alert experiences;
 - per severity when asked.

The arithmetic is plain Python over the (created, resolved) pairs so the same rule applies to every source (SQL rows, digest rows, snapshots) and is easy to test; ``MAX_ROWS`` bounds the read.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime
from typing import Any, NamedTuple

from sqlalchemy import select

MAX_ROWS = 200_000


class Mttr(NamedTuple):
    median_hours: float
    p90_hours: float
    n: int


EMPTY = Mttr(0.0, 0.0, 0)


def is_response(created_at: datetime | None, resolved_at: datetime | None, stale_at: datetime | None) -> bool:
    """Whether an alert counts toward MTTR (pure): it has both times, it was not resolved before it was created, and it was not swept as stale."""
    return created_at is not None and resolved_at is not None and resolved_at >= created_at and stale_at is None


def hours(created_at: datetime, resolved_at: datetime) -> float:
    return (resolved_at - created_at).total_seconds() / 3600


def percentile(sorted_values: list[float], p: float) -> float:
    """The p-th percentile (0 to 1) of an ascending list by linear interpolation, the same rule Postgres' percentile_cont uses (pure). An empty list is 0."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = p * (len(sorted_values) - 1)
    lo, hi = math.floor(rank), math.ceil(rank)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (rank - lo)


def summarize(durations_hours: Iterable[float]) -> Mttr:
    """Median, 90th percentile and count of response times in hours, to two places (pure). Nothing at all is EMPTY, never an invented zero-looking figure: callers check ``n``."""
    values = sorted(v for v in durations_hours if v >= 0)
    if not values:
        return EMPTY
    return Mttr(round(percentile(values, 0.5), 2), round(percentile(values, 0.9), 2), len(values))


def summarize_pairs(pairs: Iterable[tuple[datetime | None, datetime | None, datetime | None]]) -> Mttr:
    """MTTR from (created_at, resolved_at, stale_at) rows, applying the one rule (pure)."""
    return summarize(hours(c, r) for c, r, s in pairs if is_response(c, r, s) and c is not None and r is not None)


async def window(db: Any, tenant_ids: list[Any], start: datetime, end: datetime | None = None, severity: str | None = None) -> Mttr:
    """MTTR of alerts CREATED in [start, end) for these tenants. The caller has put ``db`` in the right row-level-security scope (a cross-tenant read for several tenants)."""
    from app.models.alert import Alert  # noqa: PLC0415

    where = [Alert.tenant_id.in_(tenant_ids), Alert.resolved_at.isnot(None), Alert.stale_at.is_(None), Alert.created_at >= start]
    if end is not None:
        where.append(Alert.created_at < end)
    if severity:
        where.append(Alert.severity == severity)
    rows = (await db.execute(select(Alert.created_at, Alert.resolved_at, Alert.stale_at).where(*where).limit(MAX_ROWS))).all()
    return summarize_pairs((r[0], r[1], r[2]) for r in rows)


SEVERITY_ORDER = ("critical", "high", "medium", "low", "info")


def by_severity(rows: Iterable[tuple[str | None, datetime | None, datetime | None, datetime | None]]) -> list[tuple[str, Mttr]]:
    """MTTR per severity from (severity, created_at, resolved_at, stale_at) rows, by the one rule, most severe first (pure). A severity with nothing finished is left out, never shown as zero;
    a severity outside the known five is listed after them by name."""
    groups: dict[str, list[float]] = {}
    for severity, created, resolved, stale in rows:
        if is_response(created, resolved, stale) and created is not None and resolved is not None:
            groups.setdefault(str(severity or "unknown").lower(), []).append(hours(created, resolved))
    order = {name: i for i, name in enumerate(SEVERITY_ORDER)}
    out = [(name, summarize(values)) for name, values in groups.items()]
    return sorted((x for x in out if x[1].n > 0), key=lambda x: (order.get(x[0], len(order)), x[0]))


def severity_sentence(parts: list[tuple[str, Mttr]]) -> str:
    """The breakdown as one plain sentence for a tile, or "" when there is nothing to break down (one severity says no more than the tile's own figure)."""
    if len(parts) < 2:
        return ""
    return "By severity: " + ", ".join(f"{name} {m.median_hours:g} h ({m.n})" for name, m in parts) + "."


async def window_by_severity(db: Any, tenant_ids: list[Any], start: datetime, end: datetime | None = None) -> list[tuple[str, Mttr]]:
    """``window`` broken down by severity: the same alerts (created in [start, end), finished by a person, not swept as stale), in one query. Same scope rule for the caller as ``window``."""
    from app.models.alert import Alert  # noqa: PLC0415

    where = [Alert.tenant_id.in_(tenant_ids), Alert.resolved_at.isnot(None), Alert.stale_at.is_(None), Alert.created_at >= start]
    if end is not None:
        where.append(Alert.created_at < end)
    rows = (
        await db.execute(select(Alert.severity, Alert.created_at, Alert.resolved_at, Alert.stale_at).where(*where).limit(MAX_ROWS))
    ).all()
    return by_severity((r[0], r[1], r[2], r[3]) for r in rows)

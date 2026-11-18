"""The risk heat map for a date, and how it moved month by month (pure).

Each risk keeps a row of its levels every time they change (likelihood and impact, and the same after treatment) and when it is archived or brought back. The map for a date is the newest row of each risk on or before that date;
a risk whose newest row says it was archived does not count. The grid is likelihood (rows, 5 down to 1) against impact (columns, 1 to 5); a risk with no level after treatment counts at its starting level in the "after treatment" map,
since nothing has been done about it that the register knows.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from app.services.risk_register import level, score

KINDS = ("inherent", "residual")
LEVELS = ("critical", "high", "medium", "low")


@dataclass(frozen=True)
class Levels:
    risk_id: Any
    at: datetime
    likelihood: int
    impact: int
    residual_likelihood: int | None
    residual_impact: int | None
    active: bool


def _utc(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def end_of_day(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=UTC)


def newest_on(rows: list[Levels], when: datetime) -> list[Levels]:
    """The newest row of each risk on or before ``when`` that says the risk counted (pure)."""
    best: dict[Any, Levels] = {}
    for r in rows:
        if _utc(r.at) <= when and (r.risk_id not in best or _utc(r.at) >= _utc(best[r.risk_id].at)):
            best[r.risk_id] = r
    return [r for r in best.values() if r.active]


def cell(r: Levels, kind: str) -> tuple[int, int]:
    """The likelihood and impact a risk counts at in the chosen map."""
    if kind == "residual" and r.residual_likelihood is not None and r.residual_impact is not None:
        return r.residual_likelihood, r.residual_impact
    return r.likelihood, r.impact


def heatmap(rows: list[Levels], when: datetime, kind: str = "inherent") -> dict[str, Any]:
    """The grid and the totals for a date: ``cells`` (every likelihood and impact from 1 to 5 with the risks in it), ``by_level`` and ``total``."""
    counted = newest_on(rows, when)
    grid: dict[tuple[int, int], list[Any]] = {}
    by_level = dict.fromkeys(LEVELS, 0)
    for r in counted:
        l, i = cell(r, kind)
        grid.setdefault((l, i), []).append(r.risk_id)
        lv = level(score(l, i))
        if lv:
            by_level[lv] += 1
    cells = [{"likelihood": l, "impact": i, "count": len(grid.get((l, i), [])), "risk_ids": grid.get((l, i), []), "level": level(score(l, i))} for l in range(5, 0, -1) for i in range(1, 6)]
    return {"as_of": when.date().isoformat(), "kind": kind, "total": len(counted), "by_level": by_level, "cells": cells}


def month_ends(today: date, count: int = 12) -> list[date]:
    """The last day of each of the ``count`` months before this one, oldest first, then ``today`` (pure): the dates a trend is read at."""
    out: list[date] = []
    y, m = today.year, today.month
    for _ in range(count):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(date(y, m, monthrange(y, m)[1]))
    out.reverse()
    out.append(today)
    return out


def monthly(rows: list[Levels], today: date, kind: str = "inherent", count: int = 12) -> list[dict[str, Any]]:
    """For each month end (and today): how many risks counted at each level."""
    out = []
    for d in month_ends(today, count):
        h = heatmap(rows, end_of_day(d), kind)
        out.append({"date": d.isoformat(), "total": h["total"], **h["by_level"]})
    return out

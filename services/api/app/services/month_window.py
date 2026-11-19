"""Which months a Metrics page covers: the newest N, or a custom range chosen with a start month and an end month.

Every Metrics service picked "the newest ``months`` months of the data". A custom range ("Jan 2025 to Jun 2025") is the same choice made another way, so instead of adding two parameters to a dozen functions the range
is set once for the request (``use_window``, from the ``start`` and ``end`` query parameters, by a dependency on the Metrics routers) and ``pick_months`` answers with it when one is set. A request with no range
behaves exactly as before. The range lives in a context variable, which belongs to one request, so two requests at once never see each other's.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterator
from contextvars import ContextVar
from typing import Annotated

from fastapi import HTTPException, Query

MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_window: ContextVar[tuple[str, str] | None] = ContextVar("metrics_month_window", default=None)


def clean_window(start: str | None, end: str | None) -> tuple[str, str] | None:
    """The range as (first month, last month), or None when none was asked for. A range needs both months, each as YYYY-MM; a start after the end is turned around (pure)."""
    if not start and not end:
        return None
    if not start or not end or not MONTH.match(start) or not MONTH.match(end):
        raise ValueError("A custom range needs a start month and an end month, each like 2026-03.")
    return (start, end) if start <= end else (end, start)


def use_window(start: str | None, end: str | None) -> Iterator[None]:
    """A FastAPI dependency body: set the range for this request and clear it after."""
    token = _window.set(clean_window(start, end))
    try:
        yield
    finally:
        _window.reset(token)


def pick_months(all_months: list[str], newest: int) -> list[str]:
    """The months to cover, oldest first: those inside the request's range when one is set, else the newest ``newest`` (none when that is 0 or less) (pure given the range)."""
    months = sorted(all_months)
    rng = _window.get()
    if rng is not None:
        return [m for m in months if rng[0] <= m <= rng[1]]
    return months[-newest:] if newest > 0 else []


def chosen_window() -> tuple[str, str] | None:
    """The custom range of this request as (first month, last month), or None when the newest N months are wanted."""
    return _window.get()


async def month_window(
    start: Annotated[str | None, Query(max_length=7, description="First month of a custom range, YYYY-MM (needs end)")] = None,
    end: Annotated[str | None, Query(max_length=7, description="Last month of a custom range, YYYY-MM (needs start)")] = None,
) -> AsyncIterator[None]:
    """The dependency on the Metrics routers: a custom range from ``start`` and ``end`` replaces "the newest N months" for this request. It is async so the range reaches the handler in the same task."""
    try:
        rng = clean_window(start, end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    token = _window.set(rng)
    try:
        yield
    finally:
        _window.reset(token)


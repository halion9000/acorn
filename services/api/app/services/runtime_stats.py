"""What the API can say about its own speed, kept in memory (it starts over with the process): how late the event loop wakes up, and which routes take the most time.

The loop-delay sampler sleeps one second at a time and records how much later than that it woke; a single busy request (model building, a big list) shows up as a delay for everyone. The route
table is fed from the request path with the route template, never the URL, so it holds no ids or search text.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

LOOP_TICK_SECONDS = 1.0
LOOP_HISTORY_SECONDS = 600
LOOP_WARN_SECONDS = 2.0
ROUTE_SAMPLES_KEPT = 200
ROUTES_KEPT = 300

_lags: deque[tuple[float, float]] = deque(maxlen=int(LOOP_HISTORY_SECONDS / LOOP_TICK_SECONDS) + 8)
_routes: dict[str, dict[str, Any]] = {}
_task: asyncio.Task | None = None


def note_loop_lag(now: float, lag: float) -> None:
    _lags.append((now, max(0.0, lag)))


def loop_lag(now: float, window_seconds: int = 300) -> dict[str, Any]:
    """The worst and the typical (median) wake-up delay in the last ``window_seconds``, in seconds, and how many readings that rests on."""
    recent = sorted(lag for at, lag in _lags if at >= now - window_seconds)
    if not recent:
        return {"window_seconds": window_seconds, "samples": 0}
    return {
        "window_seconds": window_seconds,
        "samples": len(recent),
        "max_seconds": round(recent[-1], 2),
        "typical_seconds": round(recent[len(recent) // 2], 3),
        "slow": recent[-1] >= LOOP_WARN_SECONDS,
    }


async def _sample_forever() -> None:
    while True:
        started = time.monotonic()
        await asyncio.sleep(LOOP_TICK_SECONDS)
        note_loop_lag(time.time(), time.monotonic() - started - LOOP_TICK_SECONDS)


def start_loop_sampler() -> None:
    """Start the sampler once on the running loop. Safe to call again."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_sample_forever())


def stop_loop_sampler() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        _task = None


def note_route(method: str, endpoint: str, seconds: float) -> None:
    """Add one request's time to its route. A table that grows past ROUTES_KEPT drops the route with the least total time."""
    key = f"{method} {endpoint}"
    row = _routes.get(key)
    if row is None:
        if len(_routes) >= ROUTES_KEPT:
            _routes.pop(min(_routes, key=lambda k: _routes[k]["total"]))
        row = _routes[key] = {"count": 0, "total": 0.0, "worst": 0.0, "recent": deque(maxlen=ROUTE_SAMPLES_KEPT)}
    row["count"] += 1
    row["total"] += seconds
    row["worst"] = max(row["worst"], seconds)
    row["recent"].append(seconds)


def slow_routes(limit: int = 8) -> list[dict[str, Any]]:
    """The routes that have taken the most time in total: calls, total, typical (median of the recent ones), 95th percentile of the recent ones, and the worst single call, in seconds."""
    out = []
    for key, row in sorted(_routes.items(), key=lambda kv: kv[1]["total"], reverse=True)[:limit]:
        recent = sorted(row["recent"])
        out.append(
            {
                "route": key,
                "calls": row["count"],
                "total_seconds": round(row["total"], 1),
                "typical_seconds": round(recent[len(recent) // 2], 3),
                "p95_seconds": round(recent[min(len(recent) - 1, int(len(recent) * 0.95))], 3),
                "worst_seconds": round(row["worst"], 2),
            }
        )
    return out


def reset() -> None:
    _lags.clear()
    _routes.clear()

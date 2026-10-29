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


FEED_PREFIX = "/api/v1/inbox/core-feed/{tenant_token}/"
_started_at = time.time()
_feed: dict[str, dict[str, Any]] = {}


def note_feed_receipt(endpoint: str, status: int, now: float | None = None) -> None:
    """Note one request to a CORE feed route (by its template, never the URL, so no token is kept): when it last succeeded, when it last failed and with what status, and how many of each."""
    if not endpoint.startswith(FEED_PREFIX):
        return
    route = endpoint[len(FEED_PREFIX) :]
    row = _feed.setdefault(route, {"ok": 0, "errors": 0, "ok_at": None, "error_at": None, "error_status": None})
    at = now if now is not None else time.time()
    if status < 400:
        row["ok"] += 1
        row["ok_at"] = at
    else:
        row["errors"] += 1
        row["error_at"] = at
        row["error_status"] = status


def feed_receipts(now: float | None = None) -> dict[str, Any]:
    """The last receipt per CORE feed route since the API started: oldest success first, so a route that has gone quiet is at the top. A route never seen is not listed (it may simply not be used)."""
    moment = now if now is not None else time.time()

    def minutes(at: float | None) -> int | None:
        return None if at is None else max(0, int((moment - at) // 60))

    rows = [
        {
            "route": route,
            "last_ok_minutes_ago": minutes(row["ok_at"]),
            "ok": row["ok"],
            "errors": row["errors"],
            "last_error_minutes_ago": minutes(row["error_at"]),
            "last_error_status": row["error_status"],
        }
        for route, row in _feed.items()
    ]
    rows.sort(key=lambda r: (r["last_ok_minutes_ago"] is not None, -(r["last_ok_minutes_ago"] or 0), r["route"]))
    return {"since_minutes_ago": max(0, int((moment - _started_at) // 60)), "routes": rows}


def reset() -> None:
    _lags.clear()
    _routes.clear()
    _feed.clear()

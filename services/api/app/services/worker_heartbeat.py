"""Whether each background worker is still doing its rounds.

A worker that loops forever fails quietly: the loop swallows an error, or stops, and nothing says so until the thing it does (reading the DMARC mailbox, sweeping hidden alerts) is noticed missing. Each worker
registers how often it should run and records a beat after every pass; the health page shows any that went quiet or whose last pass failed. In-process: workers run inside the API process, so this is only
what THIS process saw since it started (a restart begins a fresh clock, and a worker that has not had its first turn yet is "waiting", not "late").
"""

from __future__ import annotations

import time
from dataclasses import dataclass

GRACE_FACTOR = 2.5  # a worker is late when it has not beaten for this many of its own intervals
GRACE_FLOOR_SECONDS = 120  # ... and never sooner than this, so a slow pass is not called late


@dataclass
class _Worker:
    interval: float
    first_turn_after: float  # seconds after registering before its first pass is expected
    registered_at: float
    last_beat: float | None = None
    last_ok: bool = True
    last_error: str | None = None
    passes: int = 0
    next_within: float | None = None  # this pass told us when to expect the next (a worker that backs off after failures)


_WORKERS: dict[str, _Worker] = {}


def expect(name: str, interval_seconds: float, first_turn_after_seconds: float = 0, now: float | None = None) -> None:
    """A worker announces itself: how often it runs, and how long before its first pass (many sleep first)."""
    t = time.monotonic() if now is None else now
    _WORKERS[name] = _Worker(interval=max(1.0, float(interval_seconds)), first_turn_after=max(0.0, float(first_turn_after_seconds)), registered_at=t)


def beat(name: str, error: str | None = None, now: float | None = None, next_within_seconds: float | None = None) -> None:
    """One pass finished. ``error`` is a short reason when it failed (a type name, never a message that could carry a secret). A worker that waits longer after a failure says how long, so its slow retry is "failing", not "late"."""
    w = _WORKERS.get(name)
    if w is None:
        return
    w.last_beat = time.monotonic() if now is None else now
    w.last_ok = error is None
    w.last_error = error[:80] if error else None
    w.passes += 1
    w.next_within = None if next_within_seconds is None else max(w.interval, float(next_within_seconds))


def _status(w: _Worker, t: float) -> str:
    allowed = max(GRACE_FLOOR_SECONDS, (w.next_within or w.interval) * GRACE_FACTOR)
    if w.last_beat is None:
        return "waiting" if t - w.registered_at <= w.first_turn_after + allowed else "late"
    if t - w.last_beat > allowed:
        return "late"
    return "ok" if w.last_ok else "failing"


def snapshot(now: float | None = None) -> list[dict[str, object]]:
    """Every registered worker: its name, how often it should run, seconds since its last pass, passes since start, the last error, and ok / failing / waiting / late. Worst first."""
    t = time.monotonic() if now is None else now
    order = {"late": 0, "failing": 1, "waiting": 2, "ok": 3}
    rows = [
        {
            "name": name,
            "interval_seconds": int(w.interval),
            "seconds_since_pass": None if w.last_beat is None else int(t - w.last_beat),
            "passes": w.passes,
            "last_error": w.last_error,
            "status": _status(w, t),
        }
        for name, w in _WORKERS.items()
    ]
    return sorted(rows, key=lambda r: (order[str(r["status"])], str(r["name"])))


def reset() -> None:
    _WORKERS.clear()

"""Whether each background worker is still doing its rounds.

A worker that loops forever fails quietly: the loop swallows an error, or stops, and nothing says so until the thing it does (reading the DMARC mailbox, sweeping hidden alerts) is noticed missing. Each worker
registers how often it should run and records a beat after every pass; the health page shows any that went quiet or whose last pass failed. In-process: workers run inside the API process, so this is only
what THIS process saw since it started (a restart begins a fresh clock, and a worker that has not had its first turn yet is "waiting", not "late").
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

GRACE_FACTOR = 2.5  # a worker is late when it has not beaten for this many of its own intervals
GRACE_FLOOR_SECONDS = 120  # ... and never sooner than this, so a slow pass is not called late
RECENT_PASSES = 10  # how many of a worker's latest passes are remembered, so a failure that has since recovered still shows


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
    recent: deque[tuple[float, str | None]] = field(
        default_factory=lambda: deque(maxlen=RECENT_PASSES)
    )  # (when, error or None), oldest first


_WORKERS: dict[str, _Worker] = {}


def expect(name: str, interval_seconds: float, first_turn_after_seconds: float = 0, now: float | None = None) -> None:
    """A worker announces itself: how often it runs, and how long before its first pass (many sleep first)."""
    t = time.monotonic() if now is None else now
    _WORKERS[name] = _Worker(
        interval=max(1.0, float(interval_seconds)), first_turn_after=max(0.0, float(first_turn_after_seconds)), registered_at=t
    )


def beat(name: str, error: str | None = None, now: float | None = None, next_within_seconds: float | None = None) -> None:
    """One pass finished. ``error`` is a short reason when it failed (a type name, never a message that could carry a secret). A worker that waits longer after a failure says how long, so its slow retry is "failing", not "late"."""
    w = _WORKERS.get(name)
    if w is None:
        return
    w.last_beat = time.monotonic() if now is None else now
    w.last_ok = error is None
    w.last_error = error[:80] if error else None
    w.passes += 1
    w.recent.append((w.last_beat, w.last_error))
    w.next_within = None if next_within_seconds is None else max(w.interval, float(next_within_seconds))


def _status(w: _Worker, t: float) -> str:
    allowed = max(GRACE_FLOOR_SECONDS, (w.next_within or w.interval) * GRACE_FACTOR)
    if w.last_beat is None:
        return "waiting" if t - w.registered_at <= w.first_turn_after + allowed else "late"
    if t - w.last_beat > allowed:
        return "late"
    return "ok" if w.last_ok else "failing"


def snapshot(now: float | None = None) -> list[dict[str, object]]:
    """Every registered worker: its name, how often it should run, seconds since its last pass, passes since start, the last error, its latest passes, and ok / failing / waiting / late. Worst first."""
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
            # The latest passes, newest first: how long ago and the error's type name when it failed. A worker that failed and recovered shows here though its status is ok again.
            "recent": [{"seconds_ago": int(t - at), "ok": error is None, "error": error} for at, error in reversed(w.recent)],
            "recent_failed": sum(1 for _, error in w.recent if error is not None),
        }
        for name, w in _WORKERS.items()
    ]
    return sorted(rows, key=lambda r: (order[str(r["status"])], str(r["name"])))


def reset() -> None:
    _WORKERS.clear()


# ---- several API processes -----------------------------------------------------------------------------------------------------------------------------------
# With more than one uvicorn worker the background workers run in ONE process (the one that holds each scheduler lock) while any process may answer the health page. Each process therefore publishes
# its own snapshot to Redis every PUBLISH_EVERY seconds, and the page merges what every live process published: for each worker the freshest report wins.

PUBLISH_EVERY = 15
STALE_AFTER = 90  # a process that has not published for this long is gone: its report is ignored
_KEY = "acorn:worker-heartbeats:"


def merge_published(published: list[tuple[float, list[dict[str, object]]]], now_epoch: float) -> list[dict[str, object]]:
    """The worker rows of every live process merged into one list (pure). `published` is [(when the process published, its snapshot rows)]. A report older than STALE_AFTER is dropped; the ages in a row are advanced by
    how long ago it was published; for a worker several processes know of, the report with the most recent pass wins (a process that only knows it is waiting loses to one that has a pass)."""
    order = {"late": 0, "failing": 1, "waiting": 2, "ok": 3}
    best: dict[str, dict[str, object]] = {}
    for published_at, rows in published:
        age = max(0.0, now_epoch - published_at)
        if age > STALE_AFTER:
            continue
        for row in rows:
            r = dict(row)
            since = r.get("seconds_since_pass")
            if isinstance(since, int | float):
                r["seconds_since_pass"] = int(since + age)
            r["recent"] = [{**p, "seconds_ago": int(p.get("seconds_ago", 0) + age)} for p in r.get("recent", [])]  # type: ignore[union-attr]
            name = str(r["name"])
            mine = r.get("seconds_since_pass")
            theirs = best.get(name, {}).get("seconds_since_pass")
            if name not in best or (mine is not None and (theirs is None or mine < theirs)):
                best[name] = r
    return sorted(best.values(), key=lambda r: (order.get(str(r["status"]), 9), str(r["name"])))


async def publish_once(client: object, pid: int, now_epoch: float | None = None) -> None:
    """Write this process's snapshot to Redis (it expires by itself)."""
    import json
    import time as _time

    payload = json.dumps({"at": _time.time() if now_epoch is None else now_epoch, "rows": snapshot()})
    await client.set(f"{_KEY}{pid}", payload, ex=STALE_AFTER * 2)  # type: ignore[attr-defined]


async def publish_loop(client: object, pid: int) -> None:
    """Run in every API process: publish now and every PUBLISH_EVERY seconds. A Redis failure never ends it."""
    import asyncio

    while True:
        try:
            await publish_once(client, pid)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(PUBLISH_EVERY)


async def shared_snapshot(client: object) -> list[dict[str, object]]:
    """What the health page shows: every live process's workers merged; this process's own snapshot alone when Redis cannot be read."""
    import json
    import time as _time

    try:
        keys = [k async for k in client.scan_iter(match=f"{_KEY}*")]  # type: ignore[attr-defined]
        published: list[tuple[float, list[dict[str, object]]]] = []
        for k in keys:
            raw = await client.get(k)  # type: ignore[attr-defined]
            if raw:
                d = json.loads(raw)
                published.append((float(d["at"]), list(d["rows"])))
        merged = merge_published(published, _time.time()) if published else []
    except Exception:  # noqa: BLE001
        return snapshot()
    own = snapshot()
    return merged if merged else own

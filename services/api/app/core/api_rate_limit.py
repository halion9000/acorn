"""A limit on how fast one caller may use the main API (improvement A19).

Only a few endpoints had any limit. This adds one for everything, in three modes set by ``AISOC_RATE_LIMIT_MODE``:

 - ``log`` (the default, as decided: log only for a week): nothing is ever refused; a caller over the limit is counted and logged, and the health page shows how many requests WOULD have been refused, so the
   limit can be judged against real traffic before it is enforced;
 - ``enforce``: a caller over the limit gets 429 with ``Retry-After``;
 - ``off``: nothing is counted.

A caller is the signed-in session or API key (a hash of its Authorization header, never the token), else the address the request came from. The limit is ``AISOC_RATE_LIMIT_PER_MINUTE`` requests in a sliding
minute (default 300) for each caller, in this API process (with several workers each counts its own, so the real limit is at most workers times higher).

Never limited, whatever the mode, because a limit that is too tight here would stall a working system: the CORE feed (its token is in the path and it posts in bursts), the health and metrics routes, and any
request carrying the key named in ``AISOC_RATE_LIMIT_EXEMPT_KEY_HASHES`` (comma separated key hashes as ``caller_key`` makes them, for the agents' service keys).
"""

from __future__ import annotations

import hashlib
import os
import time
from collections import deque
from typing import Any

WINDOW_SECONDS = 60.0
DEFAULT_PER_MINUTE = 300
MAX_TRACKED_CALLERS = 20_000  # one entry per caller; the oldest idle ones are dropped past this so a flood of addresses cannot use up memory

EXEMPT_PREFIXES = ("/health", "/metrics", "/api/v1/health")
EXEMPT_FRAGMENTS = ("/inbox/core-feed/",)


def mode() -> str:
    value = (os.environ.get("AISOC_RATE_LIMIT_MODE") or "log").strip().lower()
    return value if value in ("off", "log", "enforce") else "log"


def per_minute() -> int:
    try:
        n = int(os.environ.get("AISOC_RATE_LIMIT_PER_MINUTE") or DEFAULT_PER_MINUTE)
    except ValueError:
        return DEFAULT_PER_MINUTE
    return n if n > 0 else DEFAULT_PER_MINUTE


def exempt_hashes() -> set[str]:
    return {h.strip() for h in (os.environ.get("AISOC_RATE_LIMIT_EXEMPT_KEY_HASHES") or "").split(",") if h.strip()}


def caller_key(authorization: str | None, forwarded_for: str | None, client_host: str | None) -> str:
    """Who is calling (pure): a hash of the Authorization header when there is one, else the first forwarded address, else the connecting address. Never the token itself."""
    if authorization and authorization.strip():
        return "k:" + hashlib.sha256(authorization.strip().encode()).hexdigest()[:16]
    first = (forwarded_for or "").split(",")[0].strip()
    return "ip:" + (first or client_host or "unknown")


def is_exempt(path: str, key: str) -> bool:
    if path.startswith(EXEMPT_PREFIXES) or any(f in path for f in EXEMPT_FRAGMENTS):
        return True
    return key.startswith("k:") and key[2:] in exempt_hashes()


class SlidingWindow:
    """How many times each caller has been seen in the last ``WINDOW_SECONDS`` (pure apart from the clock it is given)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, now: float) -> int:
        q = self._hits.get(key)
        if q is None:
            if len(self._hits) >= MAX_TRACKED_CALLERS:
                self._drop_idle(now)
            q = self._hits.setdefault(key, deque())
        cutoff = now - WINDOW_SECONDS
        while q and q[0] <= cutoff:
            q.popleft()
        q.append(now)
        return len(q)

    def _drop_idle(self, now: float) -> None:
        cutoff = now - WINDOW_SECONDS
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= cutoff]:
            del self._hits[k]
        if len(self._hits) >= MAX_TRACKED_CALLERS:  # all busy: forget the quietest half rather than grow
            for k in sorted(self._hits, key=lambda k: self._hits[k][-1])[: MAX_TRACKED_CALLERS // 2]:
                del self._hits[k]


class Tally:
    """What the limit has done since this process started, for the health page: no caller is named, only counts."""

    def __init__(self) -> None:
        self.checked = 0
        self.over = 0  # requests that were over the limit (refused in enforce mode, only counted in log mode)
        self.callers_over: set[str] = set()
        self.last_over_at: float | None = None

    def snapshot(self) -> dict[str, Any]:
        return {"mode": mode(), "per_minute": per_minute(), "checked": self.checked, "over_limit": self.over, "callers_over_limit": len(self.callers_over), "last_over_seconds_ago": None if self.last_over_at is None else int(time.time() - self.last_over_at)}


window = SlidingWindow()
tally = Tally()


def decide(path: str, authorization: str | None, forwarded_for: str | None, client_host: str | None, now: float | None = None) -> tuple[bool, int]:
    """(over the limit, seconds to wait). Counts the request. Exempt routes and callers, and mode ``off``, are never over."""
    if mode() == "off":
        return False, 0
    key = caller_key(authorization, forwarded_for, client_host)
    if is_exempt(path, key):
        return False, 0
    moment = now if now is not None else time.time()
    count = window.hit(key, moment)
    tally.checked += 1
    if count <= per_minute():
        return False, 0
    tally.over += 1
    tally.callers_over.add(key)
    tally.last_over_at = moment
    return True, int(WINDOW_SECONDS)


class RateLimitMiddleware:
    """Plain ASGI middleware: counts each HTTP request and, in enforce mode only, answers 429 to a caller over the limit."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        client = scope.get("client")
        over, wait = decide(scope.get("path", ""), headers.get("authorization"), headers.get("x-forwarded-for"), client[0] if client else None)
        if over and mode() == "enforce":
            body = b'{"detail":"Too many requests. Slow down and try again shortly."}'
            await send({"type": "http.response.start", "status": 429, "headers": [(b"content-type", b"application/json"), (b"retry-after", str(wait).encode()), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)

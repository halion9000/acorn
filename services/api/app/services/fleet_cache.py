"""A short-lived memory of the fleet read, so the Fleet posture page's tabs (each of which reads every client) do not each cost a full pass. Per account, in this process only.

The read is about two seconds for two hundred clients. A tab switch inside ``TTL_SECONDS`` reuses it; anything that changes what the read would show (CORE sending checks, a person accepting a check)
calls ``clear`` so the next read is fresh.
"""

from __future__ import annotations

import time
from typing import Any

TTL_SECONDS = 30.0
_store: dict[str, tuple[float, Any]] = {}


def get(key: str, now: float | None = None) -> Any | None:
    hit = _store.get(key)
    if hit is None:
        return None
    at, value = hit
    if (now if now is not None else time.monotonic()) - at > TTL_SECONDS:
        _store.pop(key, None)
        return None
    return value


def put(key: str, value: Any, now: float | None = None) -> None:
    _store[key] = (now if now is not None else time.monotonic(), value)


def clear() -> None:
    _store.clear()

"""Whether the AI behind Leafy is answering, judged from what actually happened to the last few questions (kept in memory, so it starts over with the process).

Nothing here calls the AI: probing it every few minutes would spend the Claude plan's limits for nothing. So it can only notice a problem while someone is using Leafy, and it forgets an old one after
30 minutes without a new question. A run of failures is the signal: one failure can be a slow answer, three in a row, with nothing good between them, is a broken link (for example the Claude sign-in
on the CORE VM expired).
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from typing import Any

WINDOW_MINUTES = 30
FAILURES_IN_A_ROW = 3
_outcomes: deque[tuple[datetime, bool]] = deque(maxlen=50)


def note_llm_outcome(ok: bool, at: datetime | None = None) -> None:
    """Record that a question to the AI got an answer (True) or could not be answered (False)."""
    _outcomes.append((at or datetime.now(UTC), ok))


def reset_llm_outcomes() -> None:
    _outcomes.clear()


def llm_status(now: datetime | None = None) -> dict[str, Any] | None:
    """None when the AI looks fine or has not been asked lately; otherwise ``{failures, last_failure_at, minutes_since}`` for a run of failed questions inside the window."""
    now = now or datetime.now(UTC)
    recent = [(at, ok) for at, ok in _outcomes if now - at <= timedelta(minutes=WINDOW_MINUTES)]
    tail = recent[-FAILURES_IN_A_ROW:]
    if len(tail) < FAILURES_IN_A_ROW or any(ok for _, ok in tail):
        return None
    failures = 0
    for _, ok in reversed(recent):
        if ok:
            break
        failures += 1
    last = recent[-1][0]
    return {"failures": failures, "last_failure_at": last.isoformat(), "minutes_since": int((now - last).total_seconds() // 60)}

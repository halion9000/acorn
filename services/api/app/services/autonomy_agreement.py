"""How often people agree with what an agent proposed, per kind of action (the autonomy plan's "agreement rate").

Every approval card an agent raises ends as approved, denied or expired; the ones still waiting are counted separately. From those rows this works out, for each kind of action, how many proposals were
made and what share a person approved. It only ever REPORTS and SUGGESTS: a kind of action with enough decided proposals and a very high approval share is offered for a promotion to a higher rung of the
autonomy ladder, a kind that people often turn down or let expire is offered for a demotion, and nothing changes by itself (a person sets the rung).

Rules (stated once, here, and shown on the page):
  * decided = approved + denied + expired. An expired card counts AGAINST agreement: nobody wanted it enough to say yes.
  * agreement = approved / decided.
  * "promote" at 20 or more decided and at least 95% agreement; "demote" at 5 or more decided and under 80%; "keep" in between; "too few" under 5 decided.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

PROMOTE_MIN_DECIDED = 20
PROMOTE_AT = 0.95
DEMOTE_MIN_DECIDED = 5
DEMOTE_BELOW = 0.80
WINDOW_DAYS = 90

_KEYS = ("type", "action", "name", "tool", "kind")


def action_key(action: Any, title: str | None = None) -> str:
    """The kind of action an approval is about: the first of ``type``/``action``/``name``/``tool``/``kind`` in its payload that is text, else the card's title, else "unknown" (pure)."""
    if isinstance(action, dict):
        for k in _KEYS:
            v = action.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip().lower()[:80]
    if isinstance(title, str) and title.strip():
        return title.strip().lower()[:80]
    return "unknown"


@dataclass
class AgreementRow:
    action: str
    proposed: int = 0
    approved: int = 0
    denied: int = 0
    expired: int = 0
    pending: int = 0
    decided: int = 0
    agreement: float | None = None
    suggestion: str = "too few"


def suggestion_for(decided: int, agreement: float | None) -> str:
    if agreement is None or decided < DEMOTE_MIN_DECIDED:
        return "too few"
    if decided >= PROMOTE_MIN_DECIDED and agreement >= PROMOTE_AT:
        return "promote"
    if agreement < DEMOTE_BELOW:
        return "demote"
    return "keep"


def summarize(rows: list[dict[str, Any]], now: datetime, days: int = WINDOW_DAYS) -> list[AgreementRow]:
    """One row per kind of action, from approval rows (dicts with ``action``, ``title``, ``status``, ``created_at``). Only rows from the last ``days`` days; most proposed first (pure)."""
    since = now - timedelta(days=days)
    out: dict[str, AgreementRow] = defaultdict(lambda: AgreementRow(""))
    for r in rows:
        created = r.get("created_at")
        if isinstance(created, datetime) and created < since:
            continue
        key = action_key(r.get("action"), r.get("title"))
        row = out[key]
        row.action = key
        row.proposed += 1
        status = r.get("status")
        if status == "approved":
            row.approved += 1
        elif status == "denied":
            row.denied += 1
        elif status == "expired":
            row.expired += 1
        else:
            row.pending += 1
    for row in out.values():
        row.decided = row.approved + row.denied + row.expired
        row.agreement = round(row.approved / row.decided, 3) if row.decided else None
        row.suggestion = suggestion_for(row.decided, row.agreement)
    return sorted(out.values(), key=lambda x: (-x.proposed, x.action))

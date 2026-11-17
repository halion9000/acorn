"""Similar alerts: other alerts of the same client that look like the one being read, and why.

Two alerts are alike when they share the rule that raised them, have the same exact title, or name the same host, user or IP address. Each match carries the reasons in plain words, so a person can
tell "the same rule fired on another machine" from "the same machine raised something else". The best matches come first (rule and title count most, then the number of shared hosts, users and addresses,
then the newest). It only describes; it never closes or links anything.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

WINDOW_DAYS = 30
MAX_SHOWN = 8
# How much each reason weighs when ordering matches.
_WEIGHT = {"rule": 4, "title": 3, "host": 2, "user": 2, "ip": 1}


def _names(value: Any) -> set[str]:
    """The distinct names in a JSON list of hosts, users or addresses, lower case; anything that is not a list of text gives none."""
    if not isinstance(value, list):
        return set()
    return {v.strip().lower() for v in value if isinstance(v, str) and v.strip()}


def reasons(this: dict[str, Any], other: dict[str, Any]) -> list[str]:
    """Why ``other`` is like ``this``, in the order of weight; empty when it is not."""
    out: list[str] = []
    if this.get("rule_id") and this.get("rule_id") == other.get("rule_id"):
        out.append("same rule")
    if this.get("title") and this.get("title") == other.get("title"):
        out.append("same title")
    for key, label in (("affected_hosts", "host"), ("affected_users", "user"), ("affected_ips", "ip")):
        shared = sorted(_names(this.get(key)) & _names(other.get(key)))
        if shared:
            out.append(f"same {label}: {', '.join(shared[:3])}")
    return out


def _weight(why: list[str]) -> int:
    return sum(_WEIGHT.get(("rule" if r == "same rule" else "title" if r == "same title" else r.split(":")[0].replace("same ", "")), 0) for r in why)


def rank(this: dict[str, Any], candidates: list[dict[str, Any]], limit: int = MAX_SHOWN) -> list[dict[str, Any]]:
    """The candidates that are like ``this``, best first, at most ``limit`` (pure). ``this`` is never in its own list."""
    scored: list[tuple[int, datetime | None, dict[str, Any]]] = []
    for c in candidates:
        if c.get("id") == this.get("id"):
            continue
        why = reasons(this, c)
        if not why:
            continue
        scored.append((_weight(why), c.get("created_at"), {"id": str(c["id"]), "title": c.get("title"), "severity": c.get("severity"), "status": c.get("status"), "created_at": c.get("created_at"), "why": why}))
    scored.sort(key=lambda s: (-s[0], -(s[1].timestamp() if isinstance(s[1], datetime) else 0.0)))
    return [s[2] for s in scored[:limit]]

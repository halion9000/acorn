"""The noise report: which rules raise the most alerts that end with nothing done.

An alert is *quiet* when it was finished as a false positive or closed without a ticket, or was hidden or set aside as stale. Per rule (the rule name, else the alert's title) this counts all the alerts, how many
were quiet, and how many got a ticket, and ranks the rules by quiet alerts. A rule that is mostly quiet and has enough alerts to say so gets a plain suggestion; the report never hides or changes anything.
"""

from __future__ import annotations

from typing import Any

MIN_FOR_SUGGESTION = 10
QUIET_SHARE = 0.9
MAX_RULES = 15
QUIET_STATUSES = ("closed", "false_positive", "suppressed", "stale")


def rank(rows: list[dict[str, Any]], limit: int = MAX_RULES) -> list[dict[str, Any]]:
    """``rows``: [{rule, total, quiet, with_ticket}] one per rule (pure). Rules with nothing quiet are left out; the most quiet first, then the busiest, then by name."""
    out: list[dict[str, Any]] = []
    for r in rows:
        total, quiet = int(r.get("total") or 0), int(r.get("quiet") or 0)
        if total <= 0 or quiet <= 0:
            continue
        share = quiet / total
        suggestion = None
        if total >= MIN_FOR_SUGGESTION and share >= QUIET_SHARE:
            suggestion = f"{round(share * 100)}% of its {total} alerts ended with nothing done. Consider tuning the rule or hiding this alert type."
        out.append(
            {
                "rule": str(r.get("rule") or "(no rule name)"),
                "total": total,
                "quiet": quiet,
                "quiet_percent": round(share * 100),
                "with_ticket": int(r.get("with_ticket") or 0),
                "suggestion": suggestion,
            }
        )
    out.sort(key=lambda x: (-x["quiet"], -x["total"], x["rule"].lower()))
    return out[:limit]

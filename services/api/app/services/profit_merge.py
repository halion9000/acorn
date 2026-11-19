"""Keeping every month of the profitability data A.C.O.R.N has been sent, instead of only the latest summary (pure).

CORE used to send a whole summary each time and A.C.O.R.N replaced the one it held, so whatever CORE had not re-read (after a restart, for instance) disappeared from the Net income and Profitability month lists
until it was read again. Now each summary is merged into what is held: the months it lists are replaced (their invoices, hours and tickets), every other month is kept, and the agent list is the newest. CORE
asks which months are held (``held_months``) and reads only the others, so the older history is read once and kept in the database.
"""

from __future__ import annotations

from typing import Any

MAX_MONTHS = 240  # twenty years: far more than any source holds, so it only stops a runaway


def merge_profit(old: dict[str, Any] | None, new: dict[str, Any], limit: int = MAX_MONTHS) -> dict[str, Any]:
    """The held summary with ``new`` merged in. The months ``new`` lists are replaced, other months stay; agents are replaced; the newest ``limit`` months are kept."""
    if not old:
        return new
    fresh = {str(m) for m in new.get("months") or []}
    months = sorted({str(m) for m in old.get("months") or []} | fresh)[-limit:]
    keep = set(months)

    def merged(field: str) -> list[dict[str, Any]]:
        kept = [r for r in old.get(field) or [] if str(r.get("month")) not in fresh and str(r.get("month")) in keep]
        return kept + [r for r in new.get(field) or [] if str(r.get("month")) in keep]

    out: dict[str, Any] = {**new, "months": months, "invoices": merged("invoices"), "hours": merged("hours")}
    if new.get("tickets") is not None or old.get("tickets") is not None:
        out["tickets"] = merged("tickets")
    return out


def held_months(snapshot: dict[str, Any] | None, ticket_months: set[str]) -> list[str]:
    """The months CORE need not read again: in the held summary and with their tickets held too (a month whose tickets did not arrive is read again) (pure)."""
    have = {str(m) for m in (snapshot or {}).get("months") or []}
    return sorted(have & ticket_months)

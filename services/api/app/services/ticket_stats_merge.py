"""Keeping every month of the ticket statistics A.C.O.R.N has been sent when a later pass reads fewer months (pure).

CORE reads 36 months through the HaloPSA report call; when that call does not answer in time it falls back to a paged read of the last few months. Replacing the held statistics with that smaller answer cut the
Ticket Summary from 36 months to 5. Now a pass is merged into what is held: the months it lists are replaced (every client row of them), every other month is kept, and the open tickets are the newest.
"""

from __future__ import annotations

from typing import Any

MAX_MONTHS = 40


def merge_ticket_stats(old: dict[str, Any] | None, new: dict[str, Any], limit: int = MAX_MONTHS) -> dict[str, Any]:
    """The held statistics with ``new`` merged in; the newest ``limit`` months are kept."""
    if not old:
        return new
    fresh = {str(m) for m in new.get("months") or []}
    months = sorted({str(m) for m in old.get("months") or []} | fresh)[-limit:]
    keep = set(months)
    kept = [r for r in old.get("rows") or [] if str(r.get("month")) not in fresh and str(r.get("month")) in keep]
    return {**new, "months": months, "rows": kept + [r for r in new.get("rows") or [] if str(r.get("month")) in fresh and str(r.get("month")) in keep]}

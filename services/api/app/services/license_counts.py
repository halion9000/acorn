"""The arithmetic of the billing view: what changed between two reports of a client's counts, the count at a past date, and totals across clients. Pure: no database, no clock."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

UNITS = ("licence", "device", "user", "seat", "mailbox", "other")


def changes(previous: dict[str, int], reported: list[dict[str, Any]]) -> dict[str, Any]:
    """What a new report does to a client's counts for one tool.

    ``previous`` is {item: count} as held; ``reported`` is the new list. Returns ``history`` (a row for each item that is new, whose count changed, or that is gone: its count then is 0), ``upserts``
    (every reported item, to store) and ``removed`` (items held but no longer reported, to delete). An unchanged count adds no history.
    """
    history: list[dict[str, Any]] = []
    upserts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in reported:
        item = str(r["item"])
        if item in seen:
            continue
        seen.add(item)
        count = int(r["count"])
        upserts.append({"item": item, "unit": r.get("unit") or "other", "count": count, "available": r.get("available")})
        before = previous.get(item)
        if before != count:
            history.append({"item": item, "unit": r.get("unit") or "other", "count": count, "previous_count": before})
    removed = [i for i in previous if i not in seen]
    for item in removed:
        history.append({"item": item, "unit": "other", "count": 0, "previous_count": previous[item]})
    return {"history": history, "upserts": upserts, "removed": removed}


def count_at(history: list[dict[str, Any]], current: int, first_seen: datetime, when: datetime, tracking_since: datetime) -> int | None:
    """What an item's count was at ``when``.

    The count of the newest history row at or before then. An item with no row that old was either already there and unchanged (``first_seen`` is not after ``when``: it is ``current``), or it appeared
    after ``when`` (then it was 0, but only if A.C.O.R.N was already tracking this tool for the client at ``when``: ``tracking_since`` is not after it; otherwise nothing is known, None).
    ``history`` is the item's rows, any order.
    """
    rows = sorted(history, key=lambda h: h["observed_at"], reverse=True)
    for h in rows:
        if h["observed_at"] <= when:
            return int(h["count"])
    if first_seen <= when:
        return current
    return 0 if tracking_since <= when else None


def delta(current: int, then: int | None) -> int | None:
    """How much a count moved since ``then`` (None when it is not known what it was)."""
    return None if then is None else current - then


def totals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One line per tool and item across clients: how many clients have it, the total, the total not assigned (licences) and the total a while ago, with the change."""
    by: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        t = by.setdefault((r["source"], r["item"]), {"source": r["source"], "item": r["item"], "unit": r["unit"], "clients": 0, "total": 0, "available": 0, "had_available": False, "before": 0, "before_known": True})
        t["clients"] += 1
        t["total"] += r["count"]
        if r.get("available") is not None:
            t["available"] += r["available"]
            t["had_available"] = True
        if r.get("then") is None:
            t["before_known"] = False
        else:
            t["before"] += r["then"]
    out = []
    for t in by.values():
        out.append(
            {
                "source": t["source"],
                "item": t["item"],
                "unit": t["unit"],
                "clients": t["clients"],
                "total": t["total"],
                "available": t["available"] if t["had_available"] else None,
                "change": t["total"] - t["before"] if t["before_known"] else None,
            }
        )
    return sorted(out, key=lambda t: (t["source"], t["item"]))


def window_start(now: datetime, days: int) -> datetime:
    return now - timedelta(days=max(1, min(days, 400)))

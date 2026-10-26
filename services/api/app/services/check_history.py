"""What changed between two reports of one client's tool checks, for the history table. Pure: no database, no clock."""

from __future__ import annotations

from typing import Any

STATUSES = ("met", "partly", "not_met")


def changes(previous: list[dict[str, Any]] | None, new: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    """One entry for each check that is new, or whose status differs from the previous report's, in the new report's order.

    A check that vanished from the report is not an entry (a tool that could not read it today has not fixed it). A check with an unknown status, or no key, is ignored.
    """
    before = {str(c["key"]): str(c["status"]) for c in (previous or []) if isinstance(c, dict) and c.get("key") and c.get("status")}
    out: list[dict[str, Any]] = []
    for c in new:
        if not isinstance(c, dict) or not c.get("key") or c.get("status") not in STATUSES:
            continue
        key, status = str(c["key"]), str(c["status"])
        if before.get(key) == status:
            continue
        out.append({"source": source, "key": key[:80], "status": status, "previous_status": before.get(key), "evidence": str(c.get("evidence", ""))[:300]})
    return out


MAX_ITEM_EVENTS_PER_CHECK = 200


def item_changes(previous: list[dict[str, Any]] | None, new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Items that joined or left the list behind each check since the last report: ``{key, item, event}``, joined first, each list in the order it was given.

    Nothing is reported for the first report of a client (``previous`` is None: every item would "join"), for a check that was not in the last report, or for a check with no list. A check that
    has more than ``MAX_ITEM_EVENTS_PER_CHECK`` changes at once keeps the first that many (a tool replaced wholesale is not a hundred stories).
    """
    if previous is None:
        return []
    before = {str(c["key"]): [str(i) for i in (c.get("items") or [])] for c in previous if isinstance(c, dict) and c.get("key")}
    out: list[dict[str, Any]] = []
    for c in new:
        if not isinstance(c, dict) or not c.get("key") or str(c["key"]) not in before:
            continue
        key = str(c["key"])
        now_items = [str(i) for i in (c.get("items") or [])]
        was, is_ = set(before[key]), set(now_items)
        events = [{"key": key[:80], "item": i[:120], "event": "joined"} for i in dict.fromkeys(now_items) if i not in was]
        events += [{"key": key[:80], "item": i[:120], "event": "left"} for i in dict.fromkeys(before[key]) if i not in is_]
        out += events[:MAX_ITEM_EVENTS_PER_CHECK]
    return out


def trend(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """From a check's history (newest first): how many times it has changed, the longest it has stayed not met in the rows given, and whether it is better or worse than before."""
    if not rows:
        return {"changes": 0, "direction": "none"}
    rank = {"met": 0, "partly": 1, "not_met": 2}
    latest, prior = rows[0], rows[1] if len(rows) > 1 else None
    direction = "new"
    if prior is not None:
        a, b = rank.get(latest["status"], 0), rank.get(prior["status"], 0)
        direction = "worse" if a > b else "better" if a < b else "same"
    return {"changes": len(rows), "direction": direction}

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


UNUSUAL_FRACTION = 0.2
UNUSUAL_MIN_PREVIOUS = 5


def unusual(count: int, previous: int | None) -> bool:
    """A change big enough to look at twice: more than a fifth of what the count was, when it was at least five (a change from 2 to 3 is not news)."""
    if previous is None or previous < UNUSUAL_MIN_PREVIOUS:
        return False
    return abs(count - previous) > previous * UNUSUAL_FRACTION


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


# What an invoice line most likely counts, matched on its description (lower case). A suggestion is only offered for a line nobody has mapped; a person confirms it.
SUGGESTIONS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("huntress sat", (("huntress", "Awareness training learners"),)),
    ("huntress", (("huntress", "Agents"),)),
    ("ninjaone", (("ninjaone", "Windows workstations"), ("ninjaone", "Windows servers"), ("ninjaone", "Macs"))),
    ("threatmate", (("threatmate", "Internal assets"),)),
    ("datto saas", (("datto-saas", "Billable seats"),)),
    ("autoelevate", (("autoelevate", "Computers"),)),
    ("dnsfilter", (("dnsfilter", "Roaming agents"),)),
    ("slide", (("slide", "Protected systems"),)),
    ("field effect", (("fieldeffect", "Endpoint devices"),)),
)


def suggest(invoice_item: str) -> list[dict[str, str]]:
    """The tool counts an invoice line probably equals, or none. The first rule that matches wins, so more specific words come first ("huntress sat" before "huntress")."""
    low = invoice_item.lower()
    for needle, counted in SUGGESTIONS:
        if needle in low:
            return [{"source": s, "item": i} for s, i in counted]
    return []


def reconcile(billed: list[dict[str, Any]], held: list[dict[str, Any]], mapping: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    """One client's invoice lines against the tool counts they are mapped to.

    ``billed`` is [{item, count}] (what HaloPSA bills); ``held`` is [{source, item, count}] (what the tools count); ``mapping`` is {invoice item: [{source, item}]}. Returns ``rows`` (one per mapped invoice
    line: billed, counted (the mapped items added up), difference = counted - billed, and the parts) and ``unmapped`` (billed lines nobody has mapped).
    """
    have = {(h["source"], h["item"]): int(h["count"]) for h in held}
    rows: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    for b in billed:
        item = str(b["item"])
        parts = mapping.get(item)
        if not parts:
            unmapped.append({"item": item, "billed": int(b["count"])})
            continue
        shown = [{"source": p["source"], "item": p["item"], "count": have.get((p["source"], p["item"]), 0)} for p in parts]
        counted = sum(p["count"] for p in shown)
        rows.append({"invoice_item": item, "billed": int(b["count"]), "counted": counted, "difference": counted - int(b["count"]), "parts": shown})
    rows.sort(key=lambda r: (-abs(r["difference"]), r["invoice_item"]))
    return {"rows": rows, "unmapped": unmapped}


# The count every other endpoint tool is held against: what the RMM manages.
BASELINE_TOOL = "ninjaone"
BASELINE_ITEMS = ("Windows workstations", "Windows servers", "Macs", "Linux servers")
# Tools that count the same machines, and the item that does it.
ENDPOINT_COUNTS = {"huntress": "Agents", "autoelevate": "Computers", "dnsfilter": "Roaming agents", "fieldeffect": "Endpoint devices"}
DISAGREE_FRACTION = 0.2
DISAGREE_MIN_GAP = 3


def endpoint_disagreements(per_client: dict[Any, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Clients where a tool counts noticeably fewer or more machines than the RMM does.

    ``per_client`` is {client: [{source, item, count}]}. A tool that has a count for a client is compared with the RMM's endpoint total (when the RMM has one): it disagrees when the gap is at least
    ``DISAGREE_MIN_GAP`` machines and more than ``DISAGREE_FRACTION`` of the RMM's count. Biggest gap first. A tool with no row for the client is not here (that is coverage, not disagreement).
    """
    out: list[dict[str, Any]] = []
    for client, rows in per_client.items():
        have = {(r["source"], r["item"]): int(r["count"]) for r in rows}
        base_parts = [have[(BASELINE_TOOL, i)] for i in BASELINE_ITEMS if (BASELINE_TOOL, i) in have]
        if not base_parts:
            continue
        base = sum(base_parts)
        for tool, item in ENDPOINT_COUNTS.items():
            if (tool, item) not in have:
                continue
            n = have[(tool, item)]
            gap = n - base
            if abs(gap) >= DISAGREE_MIN_GAP and abs(gap) > base * DISAGREE_FRACTION:
                out.append({"client": client, "tool": tool, "tool_count": n, "baseline_count": base, "gap": gap})
    out.sort(key=lambda r: (-abs(r["gap"]), str(r["client"]), r["tool"]))
    return out


SILENT_AFTER_DAYS = 2


def last_reported(rows: list[dict[str, Any]], now: datetime, silent_after_days: int = SILENT_AFTER_DAYS) -> list[dict[str, Any]]:
    """When each tool last reported a count for each client, silent ones first.

    ``rows`` is [{client, source, updated_at}] (one per stored count). Returns one entry per client and tool: the newest ``updated_at`` among that client's counts from that tool, how many whole days ago that
    is, and ``silent`` when it is more than ``silent_after_days`` days ago (the daily report stopped arriving: a stopped feed, a removed mapping or a tool that lost access).
    """
    latest: dict[tuple[Any, str], datetime] = {}
    for r in rows:
        k = (r["client"], r["source"])
        if k not in latest or r["updated_at"] > latest[k]:
            latest[k] = r["updated_at"]
    out = []
    for (client, source), at in latest.items():
        days = max(0, (now - at).days)
        out.append({"client": client, "source": source, "last_reported_at": at, "days_ago": days, "silent": days > silent_after_days})
    out.sort(key=lambda r: (not r["silent"], -r["days_ago"], str(r["client"]), r["source"]))
    return out


# Tools whose clients are mapped but whose count lives under another name (the tool and the source of its counts differ).
_COUNT_SOURCE_OF = {"datto-saas-seats": "datto-saas", "cipp-health": "cipp"}


def tools_without_counts(mapped_vendors: set[str], count_sources: set[str]) -> list[str]:
    """Tools that have clients mapped to them but have never stored a count, sorted. Some tools count nothing by design (a detection feed); the page says so, this only lists them."""
    return sorted(v for v in mapped_vendors if _COUNT_SOURCE_OF.get(v, v) not in count_sources)

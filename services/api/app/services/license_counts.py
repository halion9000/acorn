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
    ("dns filter", (("dnsfilter", "Roaming agents"),)),
    ("slide", (("slide", "Protected systems"),)),
    ("field effect", (("fieldeffect", "Endpoint devices"),)),
)


# How sure a suggestion is. A rule is "high" when its tool counts exactly what the invoice line names (one agent, one seat, one machine); "medium" when the count is made of several items or can include
# things that are not billed (NinjaOne's workstations, servers and Macs, Slide's protected systems, Field Effect's devices); "low" when the line may be priced on something else (ThreatMate's assets).
SUGGESTION_CONFIDENCE: dict[str, str] = {
    "huntress sat": "high",
    "huntress": "high",
    "ninjaone": "medium",
    "threatmate": "low",
    "datto saas": "high",
    "autoelevate": "high",
    "dnsfilter": "high",
    "dns filter": "high",
    "slide": "medium",
    "field effect": "medium",
}


def suggestion_confidence(invoice_item: str) -> str | None:
    """How sure the suggestion for an invoice line is (``high``, ``medium`` or ``low``), or None when there is no suggestion."""
    low = invoice_item.lower()
    for needle, _counted in SUGGESTIONS:
        if needle in low:
            return SUGGESTION_CONFIDENCE[needle]
    return None


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


def note_state(note: dict[str, Any] | None, difference: int) -> str:
    """How a line's accepted-difference note stands: ``none`` (no note), ``accepted`` (the note was written for this very difference) or ``stale`` (the difference has changed since, so the note no longer
    says anything about it and the line needs a look again). A line that now matches is ``none`` whatever its note says."""
    if note is None or difference == 0:
        return "none"
    return "accepted" if int(note["difference"]) == difference else "stale"


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


def unbilled_clients(per_client: dict[Any, list[dict[str, Any]]], billed_source: str = "halopsa") -> list[dict[str, Any]]:
    """Clients the RMM manages machines for but that have no billed line at all: counted, never billed.

    ``per_client`` is {client: [{source, item, count, unit?}]}. A client qualifies when its RMM endpoint total is above zero and it holds no count from ``billed_source`` other than tickets (a ticket count is not
    something billed). A client with no billing data AT ALL looks the same as one that is not billed: the caller says so. Largest machine count first.
    """
    out = []
    for client, rows in per_client.items():
        machines = sum(int(r["count"]) for r in rows if r["source"] == BASELINE_TOOL and r["item"] in BASELINE_ITEMS)
        has_billed = any(r["source"] == billed_source and r.get("unit") != "ticket" for r in rows)
        if machines > 0 and not has_billed:
            out.append({"client": client, "machines": machines})
    out.sort(key=lambda r: (-r["machines"], str(r["client"])))
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


def count_series(history: list[dict[str, Any]], current: int, now: datetime, since: datetime) -> list[dict[str, Any]]:
    """One count over a window, oldest first, as points a chart can draw.

    ``history`` is the item's change rows ({observed_at, count, previous_count}). The series starts at ``since`` with the count the first change in the window replaced (when that is known: an item
    that first appeared inside the window has no earlier value, so the series starts at its first row), has one point per change, and ends at ``now`` with the current count.
    """
    inside = sorted((h for h in history if since <= h["observed_at"] <= now), key=lambda h: h["observed_at"])
    points: list[dict[str, Any]] = []
    if inside and inside[0].get("previous_count") is not None:
        points.append({"at": since, "count": int(inside[0]["previous_count"])})
    points += [{"at": h["observed_at"], "count": int(h["count"])} for h in inside]
    if not inside:
        earlier = sorted((h for h in history if h["observed_at"] < since), key=lambda h: h["observed_at"])
        points.append({"at": since, "count": int(earlier[-1]["count"]) if earlier else current})
    points.append({"at": now, "count": current})
    return points


def forecast_next(points: list[dict[str, Any]], horizon_days: int = 30) -> int | None:
    """Where a count is heading: a straight line through the series' points (least squares over time), read ``horizon_days`` after the last point, never below 0 and rounded.

    ``points`` is the output of ``count_series`` (each has ``at`` and ``count``). Fewer than three points, or no time between them, gives None: there is no trend to project. A flat series forecasts itself.
    """
    if len(points) < 3:
        return None
    t0 = min(p["at"] for p in points)
    xs = [(p["at"] - t0).total_seconds() / 86400 for p in points]
    ys = [float(p["count"]) for p in points]
    n = len(points)
    mx, my = sum(xs) / n, sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
    at = max(xs) + horizon_days
    return max(0, int(round(my + slope * (at - mx))))


def disagreement_since(
    billed: tuple[str, str],
    parts: list[tuple[str, str]],
    history: dict[tuple[str, str], list[dict[str, Any]]],
    current: dict[tuple[str, str], tuple[int, datetime]],
    tracking: dict[str, datetime],
    now: datetime,
) -> tuple[datetime, bool]:
    """Since when an invoice line has not matched the tools' added-up count, and whether that is the real start.

    The counts of the billed line and of every part are known at each moment one of them changed (``history``: item -> rows of observed_at and count; ``current``: item -> latest count and when it was first
    seen; ``tracking``: tool -> when A.C.O.R.N started keeping counts for the client). Walking back from now, the line has disagreed since the oldest change after which it never matched. The second value is
    False when that is only as far back as A.C.O.R.N can see (the line has never matched since it was first recorded, or a count from before then is not known), so the true start may be earlier.
    A line that is balanced right now has no start: call this only for a line whose difference is not zero.
    """
    keys = [billed, *parts]

    def at(key: tuple[str, str], when: datetime) -> int | None:
        if key not in current:
            return 0 if any(h["observed_at"] <= when for h in history.get(key, [])) else None
        count, first_seen = current[key]
        return count_at(history.get(key, []), count, first_seen, when, tracking.get(key[0], first_seen))

    def difference(when: datetime) -> int | None:
        counts = [at(k, when) for k in keys]
        if any(c is None for c in counts):
            return None
        return sum(c for c in counts[1:]) - counts[0]  # type: ignore[misc]

    times = sorted({h["observed_at"] for k in keys for h in history.get(k, [])}, reverse=True)
    start = now
    for t in times:
        d = difference(t)
        if d is None:
            return start, False
        if d == 0:
            return start, True
        start = t
    return start, False

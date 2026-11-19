"""The Tickets and Finance pages of Metrics (Ticket Resolution, Ticket Volume Analysis, the open-ticket breakdown of Ticket Summary, Monthly Invoicing), worked out from the datasets CORE sends
(``metric_datasets``, migration 196).

``ticket-detail``::

    {"weeks": [...], "rows": [{"week" (Monday), "client_id", "client_name", "type", "category", "priority", "created", "resolved", "resolution_hours" (summed over the resolved tickets that have a time),
      "resolved_with_time"}],
     "open": [{"client_id", "client_name", "status", "priority", "count"}],            # what is open now (not date filtered)
     "stale": [{"ticket_id", "client_name", "agent", "title", "priority", "status", "age_days"}]}   # open more than 30 days

``invoice-lines``: ``{"months": [...], "rows": [{"month", "client_id", "client_name", "item", "category", "quantity", "amount"}]}``.

A period counts whole weeks (or months) back from the newest one in the data; a month is four weeks and a third (rounded), at most 52 weeks for a year.
"""

from __future__ import annotations

from typing import Any
from app.services.month_window import pick_months

from app.services.metrics_staff import recent_weeks


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _rows_in(payload: dict[str, Any] | None, weeks: list[str]) -> list[dict[str, Any]]:
    want = set(weeks)
    return [r for r in (payload or {}).get("rows") or [] if str(r.get("week")) in want]


def _month_of(week: str) -> str:
    return str(week)[:7]


def _top(d: dict[str, float], limit: int | None = None) -> list[tuple[str, float]]:
    items = sorted(d.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    return items[:limit] if limit else items


def ticket_resolution(detail: dict[str, Any] | None, staff: dict[str, Any] | None, months: int) -> dict[str, Any]:
    """Resolved tickets by team member by month (from the weekly staff facts), and the average hours to resolve by client (from the ticket facts, over the resolved tickets that have a time)."""
    weeks = recent_weeks(staff, months)
    months_list = sorted({_month_of(w) for w in weeks})
    table: dict[str, dict[str, int]] = {}
    for r in _rows_in(staff, weeks):
        name = str(r.get("engineer") or "")
        m = _month_of(str(r["week"]))
        row = table.setdefault(name, {})
        row[m] = row.get(m, 0) + int(_num(r.get("closed")))
    dweeks = recent_weeks(detail, months)
    hours: dict[str, float] = {}
    counted: dict[str, float] = {}
    for r in _rows_in(detail, dweeks):
        c = str(r.get("client_name") or "")
        hours[c] = hours.get(c, 0.0) + _num(r.get("resolution_hours"))
        counted[c] = counted.get(c, 0.0) + _num(r.get("resolved_with_time"))
    by_client = [{"client": c, "hours": round(hours[c] / counted[c], 1), "tickets": int(counted[c])} for c in counted if counted[c] > 0]
    by_client.sort(key=lambda x: (-x["hours"], x["client"].lower()))
    return {
        "months": months_list,
        "members": [
            {"engineer": n, "total": sum(v.values()), "by_month": v}
            for n, v in sorted(table.items(), key=lambda kv: (-sum(kv[1].values()), kv[0].lower()))
            if sum(v.values()) > 0
        ],
        "resolution_by_client": by_client,
    }


def resolution_from_report(resolution: dict[str, Any] | None, months: int) -> dict[str, Any] | None:
    """The Ticket Resolution page from the statistics CORE read through the HaloPSA report call (the Rewst way), or None when CORE has not sent them (then the older weekly facts are used).

    Resolved tickets per team member per month, and the hours from opened to closed added up per client per month, both counted by the month a ticket was opened, for the months chosen (the newest ``months``
    or a custom range). People and clients are listed biggest total first, with the months they have nothing in as zero.
    """
    if not resolution:
        return None
    all_months = sorted({str(r["month"]) for r in resolution.get("agents") or []} | {str(r["month"]) for r in resolution.get("clients") or []})
    chosen = pick_months(all_months, months)
    want = set(chosen)
    people: dict[str, dict[str, int]] = {}
    for r in resolution.get("agents") or []:
        if str(r["month"]) in want:
            row = people.setdefault(str(r["agent_name"]), {})
            row[str(r["month"])] = row.get(str(r["month"]), 0) + int(r["n"])
    clients: dict[str, dict[str, float]] = {}
    for r in resolution.get("clients") or []:
        if str(r["month"]) in want:
            row = clients.setdefault(str(r["client"]), {})
            row[str(r["month"])] = round(row.get(str(r["month"]), 0.0) + float(r["hours"]), 1)
    return {
        "source": "report",
        "months": chosen,
        "available_months": len(all_months),
        "members": [{"engineer": n, "total": sum(v.values()), "by_month": v} for n, v in sorted(people.items(), key=lambda kv: (-sum(kv[1].values()), kv[0].lower())) if sum(v.values()) > 0],
        "clients": [{"client": c, "total": round(sum(v.values()), 1), "by_month": v} for c, v in sorted(clients.items(), key=lambda kv: (-sum(kv[1].values()), kv[0].lower())) if sum(v.values()) > 0],
        "resolution_by_client": [],
    }


def ticket_volume(detail: dict[str, Any] | None, months: int, tech: str | None = None) -> dict[str, Any]:
    """Tickets created by type, by category, per month and by client; the priority mix of the last 60 days; stale tickets (open more than 30 days) by tech, with the detail (for one tech when chosen)."""
    weeks = recent_weeks(detail, months)
    rows = _rows_in(detail, weeks)
    months_list = sorted({_month_of(w) for w in weeks})

    def matrix(field: str) -> list[dict[str, Any]]:
        cell: dict[str, dict[str, int]] = {}
        for r in rows:
            k = str(r.get(field) or "(none)")
            m = _month_of(str(r["week"]))
            cell.setdefault(k, {})[m] = cell.get(k, {}).get(m, 0) + int(_num(r.get("created")))
        return [
            {"name": k, "total": sum(v.values()), "by_month": v}
            for k, v in sorted(cell.items(), key=lambda kv: (-sum(kv[1].values()), kv[0].lower()))
        ]

    per_month = {m: 0 for m in months_list}
    by_client: dict[str, float] = {}
    for r in rows:
        per_month[_month_of(str(r["week"]))] += int(_num(r.get("created")))
        by_client[str(r.get("client_name") or "")] = by_client.get(str(r.get("client_name") or ""), 0.0) + _num(r.get("created"))
    last60 = _rows_in(detail, recent_weeks(detail, 2))
    priority: dict[str, float] = {}
    for r in last60:
        priority[str(r.get("priority") or "(none)")] = priority.get(str(r.get("priority") or "(none)"), 0.0) + _num(r.get("created"))
    stale = list((detail or {}).get("stale") or [])
    techs = sorted({str(s.get("agent") or "Unassigned") for s in stale}, key=str.lower)
    shown = [s for s in stale if not tech or str(s.get("agent") or "Unassigned") == tech]
    by_tech: dict[str, float] = {}
    for s in stale:
        by_tech[str(s.get("agent") or "Unassigned")] = by_tech.get(str(s.get("agent") or "Unassigned"), 0.0) + 1
    return {
        "months": months_list,
        "total_created": sum(per_month.values()),
        "by_type": matrix("type"),
        "by_category": matrix("category"),
        "per_month": [{"month": m, "created": n} for m, n in per_month.items()],
        "by_client": [{"client": c, "created": int(n)} for c, n in _top(by_client, 25)],
        "priority_last_60_days": [{"priority": p, "created": int(n)} for p, n in _top(priority)],
        "stale_by_tech": [{"tech": t, "tickets": int(n)} for t, n in _top(by_tech)],
        "stale": sorted(
            (
                {
                    "ticket_id": str(s.get("ticket_id") or ""),
                    "client": str(s.get("client_name") or ""),
                    "agent": str(s.get("agent") or "Unassigned"),
                    "title": str(s.get("title") or "")[:200],
                    "priority": str(s.get("priority") or ""),
                    "status": str(s.get("status") or ""),
                    "age_days": int(_num(s.get("age_days"))),
                    "type": str(s.get("type") or ""),
                    "opened": str(s.get("opened") or ""),
                    "last_activity": str(s.get("last_activity") or ""),
                    "idle_days": int(_num(s.get("idle_days"))) if s.get("idle_days") is not None else None,
                }
                for s in shown
            ),
            key=lambda s: (-s["age_days"], s["ticket_id"]),
        )[:500],
        "techs": techs,
    }


def open_breakdown(detail: dict[str, Any] | None, client_id: str | None = None) -> dict[str, Any]:
    """What is open now by status and by priority (not date filtered), for all clients or one (by HaloPSA client id)."""
    status: dict[str, float] = {}
    priority: dict[str, float] = {}
    for o in (detail or {}).get("open") or []:
        if client_id and str(o.get("client_id")) != client_id:
            continue
        n = _num(o.get("count"))
        status[str(o.get("status") or "(none)")] = status.get(str(o.get("status") or "(none)"), 0.0) + n
        priority[str(o.get("priority") or "(none)")] = priority.get(str(o.get("priority") or "(none)"), 0.0) + n
    return {
        "total": int(sum(status.values())),
        "by_status": [{"status": k, "tickets": int(v)} for k, v in _top(status)],
        "by_priority": [{"priority": k, "tickets": int(v)} for k, v in _top(priority)],
    }


def monthly_invoicing(payload: dict[str, Any] | None, months: int) -> dict[str, Any]:
    """The monthly revenue trend, the total billed by billing category and each client's revenue by invoice line, for the newest ``months`` months of the invoiced lines."""
    all_months = sorted(
        {str(m) for m in (payload or {}).get("months") or []} | {str(r.get("month")) for r in (payload or {}).get("rows") or []}
    )
    chosen = pick_months(all_months, months)
    want = set(chosen)
    rows = [r for r in (payload or {}).get("rows") or [] if str(r.get("month")) in want]
    trend = {m: 0.0 for m in chosen}
    category: dict[str, float] = {}
    clients: dict[str, dict[str, Any]] = {}
    for r in rows:
        amount = _num(r.get("amount"))
        trend[str(r["month"])] += amount
        cat = str(r.get("category") or "(none)")
        category[cat] = category.get(cat, 0.0) + amount
        c = clients.setdefault(str(r.get("client_name") or ""), {"client": str(r.get("client_name") or ""), "total": 0.0, "items": {}})
        c["total"] += amount
        item = str(r.get("item") or "")
        cell = c["items"].setdefault(item, {"item": item, "category": cat, "quantity": 0.0, "amount": 0.0})
        cell["quantity"] += _num(r.get("quantity"))
        cell["amount"] += amount
    return {
        "months": chosen,
        "total": round(sum(trend.values()), 2),
        "trend": [{"month": m, "amount": round(v, 2)} for m, v in trend.items()],
        "by_category": [{"category": k, "amount": round(v, 2)} for k, v in _top(category)],
        "clients": sorted(
            (
                {
                    "client": c["client"],
                    "total": round(c["total"], 2),
                    "items": sorted(
                        ({**i, "quantity": round(i["quantity"], 2), "amount": round(i["amount"], 2)} for i in c["items"].values()),
                        key=lambda i: (-i["amount"], i["item"].lower()),
                    ),
                }
                for c in clients.values()
            ),
            key=lambda c: (-c["total"], c["client"].lower()),
        ),
    }


def volume_from_stats(stats: dict[str, Any] | None, months: int) -> dict[str, Any] | None:
    """The Ticket Volume counts the Rewst way, from the monthly statistics CORE read through the HaloPSA report call: tickets opened per month (the same counts as the Ticket Summary), by type, by category and by client, for
    the newest ``months`` months or a custom range. None when CORE has not sent them (the page then uses the weekly facts)."""
    volume = (stats or {}).get("volume")
    rows = (stats or {}).get("rows") or []
    if not volume or not rows:
        return None
    per_month: dict[str, int] = {}
    by_client: dict[str, int] = {}
    for r in rows:
        per_month[str(r["month"])] = per_month.get(str(r["month"]), 0) + int(r.get("created") or 0)
    all_months = sorted(m for m, n in per_month.items() if n > 0)
    chosen = pick_months(all_months, months)
    want = set(chosen)
    for r in rows:
        if str(r["month"]) in want:
            name = str(r.get("client_name") or "")
            by_client[name] = by_client.get(name, 0) + int(r.get("created") or 0)

    def matrix(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        cell: dict[str, dict[str, int]] = {}
        for i in items:
            if str(i["month"]) in want:
                cell.setdefault(str(i[key]), {})[str(i["month"])] = cell.get(str(i[key]), {}).get(str(i["month"]), 0) + int(i["n"])
        return [{"name": k, "total": sum(v.values()), "by_month": v} for k, v in sorted(cell.items(), key=lambda kv: (-sum(kv[1].values()), kv[0].lower()))]

    return {
        "months": chosen,
        "available_months": len(all_months),
        "total_created": sum(per_month[m] for m in chosen),
        "per_month": [{"month": m, "created": per_month[m]} for m in chosen],
        "by_type": matrix(volume.get("types") or [], "type"),
        "by_category": matrix(volume.get("categories") or [], "category"),
        "by_client": [{"client": c, "created": n} for c, n in sorted(by_client.items(), key=lambda kv: (-kv[1], kv[0].lower())) if n > 0][:25],
    }

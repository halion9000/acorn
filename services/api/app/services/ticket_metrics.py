"""Ticket metrics worked out from the HaloPSA ticket statistics CORE sends (``ticket_stats_snapshots``, migration 192).

For all clients or one: the months asked for (the newest first count back from the latest month in the data), how many tickets were created and resolved each month, the monthly average of each, the average
first response in minutes (over the tickets that had one), tickets by type, tickets resolved by agent, and what is open now. Counts are exact; an average is rounded to one decimal.
"""

from __future__ import annotations

from typing import Any

from app.services.month_window import pick_months

PERIODS = (1, 3, 6, 12)


def months_in(payload: dict[str, Any]) -> list[str]:
    return sorted({str(m) for m in payload.get("months") or []})


def clients_in(payload: dict[str, Any]) -> list[dict[str, str]]:
    """The HaloPSA clients that appear in the data, by name."""
    seen: dict[str, str] = {}
    for r in payload.get("rows") or []:
        seen.setdefault(str(r.get("client_id")), str(r.get("client_name") or ""))
    for r in payload.get("open_now") or []:
        seen.setdefault(str(r.get("client_id")), str(r.get("client_name") or ""))
    return sorted(({"client_id": k, "client_name": v} for k, v in seen.items()), key=lambda c: c["client_name"].lower())


def name_key(name: object) -> str:
    """A client name as a matching key: lower case, letters and digits only."""
    import re

    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def csat_for(payload: dict[str, Any], months: int, company: str | None = None) -> dict[str, Any]:
    """Customer satisfaction for the newest ``months`` months in the data, for one company (matched by name, ignoring case and punctuation) or all: counts by sentiment, the satisfied share (positive over
    positive, neutral and negative), a monthly trend and the newest comments."""
    available = sorted({str(m) for m in payload.get("months") or []})
    chosen = pick_months(available, months)
    keep = set(chosen)
    want = name_key(company) if company else None
    trend = {m: {"month": m, "positive": 0, "neutral": 0, "negative": 0, "total": 0} for m in chosen}
    for r in payload.get("rows") or []:
        m = str(r.get("month"))
        if m not in keep or (want is not None and name_key(r.get("company")) != want):
            continue
        for k in ("positive", "neutral", "negative", "total"):
            trend[m][k] += int(r.get(k) or 0)
    positive = sum(t["positive"] for t in trend.values())
    neutral = sum(t["neutral"] for t in trend.values())
    negative = sum(t["negative"] for t in trend.values())
    rated = positive + neutral + negative
    recent = [
        r
        for r in payload.get("recent") or []
        if str(r.get("date") or "")[:7] in keep and (want is None or name_key(r.get("company")) == want)
    ]
    recent.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    return {
        "months": chosen,
        "responses": sum(t["total"] for t in trend.values()),
        "positive": positive,
        "neutral": neutral,
        "negative": negative,
        "satisfied_percent": round(100 * positive / rated, 1) if rated else None,
        "trend": [
            dict(
                trend[m],
                satisfied_percent=round(100 * trend[m]["positive"] / (trend[m]["positive"] + trend[m]["neutral"] + trend[m]["negative"]), 1)
                if (trend[m]["positive"] + trend[m]["neutral"] + trend[m]["negative"])
                else None,
            )
            for m in chosen
        ],
        "recent": recent[:25],
    }


def _avg(total: float, n: int) -> float | None:
    return round(total / n, 1) if n else None


def summarize(
    payload: dict[str, Any], months: int, client_id: str | None = None, agent_names: dict[str, str] | None = None
) -> dict[str, Any]:
    """The summary for the newest ``months`` months of the data (fewer when the data has fewer), for one client or all."""
    available = months_in(payload)
    chosen = pick_months(available, months)
    keep = set(chosen)
    series = {m: {"month": m, "created": 0, "resolved": 0} for m in chosen}
    answered = {m: [0, 0.0] for m in chosen}  # per month: tickets that count toward first response, and their minutes
    by_type: dict[str, int] = {}
    by_agent: dict[str, int] = {}
    responded = 0
    response_minutes = 0.0
    critical = high = 0
    for r in payload.get("rows") or []:
        m = str(r.get("month"))
        if m not in keep or (client_id is not None and str(r.get("client_id")) != client_id):
            continue
        series[m]["created"] += int(r.get("created") or 0)
        series[m]["resolved"] += int(r.get("resolved") or 0)
        responded += int(r.get("responded") or 0)
        response_minutes += float(r.get("response_minutes") or 0)
        answered[m][0] += int(r.get("responded") or 0)
        answered[m][1] += float(r.get("response_minutes") or 0)
        critical += int(r.get("critical") or 0)
        high += int(r.get("high") or 0)
        for name, n in (r.get("created_by_type") or {}).items():
            by_type[str(name)] = by_type.get(str(name), 0) + int(n)
        for agent, n in (r.get("resolved_by_agent") or {}).items():
            by_agent[str(agent)] = by_agent.get(str(agent), 0) + int(n)
    created = sum(s["created"] for s in series.values())
    resolved = sum(s["resolved"] for s in series.values())
    names = agent_names or {}
    open_rows = [o for o in payload.get("open_now") or [] if client_id is None or str(o.get("client_id")) == client_id]
    return {
        "months": chosen,
        "series": [{**series[m], "first_response_minutes": _avg(answered[m][1], answered[m][0])} for m in chosen],
        "created": created,
        "resolved": resolved,
        "created_per_month": _avg(created, len(chosen)),
        "resolved_per_month": _avg(resolved, len(chosen)),
        "first_response_minutes": _avg(response_minutes, responded),
        "responded": responded,
        "critical_created": critical,
        "high_created": high,
        "by_type": sorted(({"type": k, "tickets": v} for k, v in by_type.items()), key=lambda x: (-x["tickets"], x["type"])),
        "resolved_by_agent": sorted(
            ({"agent_id": k, "name": names.get(k) or f"Agent {k}", "tickets": v} for k, v in by_agent.items()),
            key=lambda x: (-x["tickets"], x["name"].lower()),
        ),
        "open_now": {
            "total": sum(int(o.get("total") or 0) for o in open_rows),
            "critical": sum(int(o.get("critical") or 0) for o in open_rows),
            "high": sum(int(o.get("high") or 0) for o in open_rows),
        },
    }


def labor_hours(payload: dict[str, Any], months: int, client: str | None = None) -> dict[str, Any]:
    """Hours worked on tickets from the HaloPSA profitability summary: for the newest ``months`` months (counting back from the latest in the data), by month, by engineer, by client and by ticket type, for all
    clients or one (matched by name). Hours only: no rates or money, so this is readable with ``metrics:view``. Hours are rounded to two decimals."""
    all_months = sorted({str(m) for m in payload.get("months") or []})
    chosen = pick_months(all_months, months)
    want = set(chosen)
    agents = {str(a.get("id")): str(a.get("name") or "") for a in payload.get("agents") or []}
    teams = {str(a.get("id")): str(a.get("team") or "") for a in payload.get("agents") or []}
    key = name_key(client) if client else ""
    clients: dict[str, str] = {}
    cell_agent: dict[str, dict[str, float]] = {}
    cell_client: dict[str, dict[str, float]] = {}
    cell_type: dict[str, dict[str, float]] = {}
    by_month: dict[str, float] = {m: 0.0 for m in chosen}
    by_agent: dict[str, float] = {}
    by_client: dict[str, float] = {}
    by_type: dict[str, float] = {}
    for h in payload.get("hours") or []:
        month, name = str(h.get("month")), str(h.get("client") or "")
        if month not in want:
            continue
        clients.setdefault(name_key(name), name)
        if key and name_key(name) != key:
            continue
        hours = float(h.get("hours") or 0)
        agent = str(h.get("agent_id") or "")
        by_month[month] += hours
        by_agent[agent] = by_agent.get(agent, 0.0) + hours
        by_client[name] = by_client.get(name, 0.0) + hours
        charge = str(h.get("charge_type") or "(none)")
        by_type[charge] = by_type.get(charge, 0.0) + hours
        for table, who in ((cell_agent, agent), (cell_client, name), (cell_type, charge)):
            table.setdefault(who, {})[month] = table.get(who, {}).get(month, 0.0) + hours

    def top(d: dict[str, float]) -> list[tuple[str, float]]:
        return sorted(d.items(), key=lambda kv: (-kv[1], kv[0].lower()))

    def matrix(cells: dict[str, dict[str, float]], label: str, names: dict[str, str] | None = None) -> list[dict[str, Any]]:
        return [
            {label: (names or {}).get(k) or (f"Agent {k}" if names is not None else k), "total": round(sum(v.values()), 2), "by_month": {m: round(x, 2) for m, x in v.items()}}
            for k, v in sorted(cells.items(), key=lambda kv: (((names or {}).get(kv[0]) or kv[0]).lower()))
        ]

    total = sum(by_month.values())
    return {
        "engineers": [{**row, "team": teams.get(k) or ""} for row, k in zip(matrix(cell_agent, "name", agents), sorted(cell_agent, key=lambda a: (agents.get(a) or a).lower()), strict=True)],
        "teams": sorted({t for t in teams.values() if t}, key=str.lower),
        "client_months": matrix(cell_client, "client"),
        "type_months": matrix(cell_type, "type"),
        "months": chosen,
        "total_hours": round(total, 2),
        "hours_per_month": round(total / len(chosen), 2) if chosen else None,
        "clients": sorted(clients.values(), key=str.lower),
        "by_month": [{"month": m, "hours": round(by_month[m], 2)} for m in chosen],
        "by_agent": [{"agent_id": a, "name": agents.get(a) or f"Agent {a}", "team": teams.get(a) or "", "hours": round(v, 2)} for a, v in top(by_agent)],
        "by_client": [{"client": c, "hours": round(v, 2)} for c, v in top(by_client)],
        "by_type": [{"type": t, "hours": round(v, 2)} for t, v in top(by_type)],
    }

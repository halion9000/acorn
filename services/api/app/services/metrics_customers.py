"""The Customer Insights pages of Metrics (Customer Experience, Monthly Licensing, User Roles), worked out from stored facts (see ``metric_datasets``, migration 196, the SimpleSat summary and the license counts).

Customer Experience combines the SimpleSat summary CORE already sends (per company per month: positive, neutral, negative, plus each company's newest responses) with the survey scores each engineer's weeks
carry (``surveys``: ``total_surveys``, ``survey_sum`` and optionally ``positive``, ``neutral``, ``negative``). Monthly Licensing is a client by license-item table for a month, as of the end of that month from the
history of counts. User Roles is a client by Microsoft 365 directory role table from ``m365-roles``: ``{"clients": [{"client_id", "client_name", "roles": [{"role", "members": [{"name", "upn", "enabled"}]}]}]}``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from app.services.month_window import pick_months

from app.services.metrics_staff import recent_weeks

SENTIMENTS = ("all", "positive", "neutral", "negative")


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _share(part: float, whole: float) -> float | None:
    return round(part / whole * 100, 1) if whole > 0 else None


def customer_experience(csat: dict[str, Any] | None, staff: dict[str, Any] | None, months: int, sentiment: str = "all") -> dict[str, Any]:
    """CSAT by company, by team member and by month for the newest ``months`` months, and the newest responses (only those of the sentiment chosen unless "all")."""
    s = sentiment if sentiment in SENTIMENTS else "all"
    all_months = sorted({str(m) for m in (csat or {}).get("months") or []})
    chosen = pick_months(all_months, months)
    want = set(chosen)
    rows = [r for r in (csat or {}).get("rows") or [] if str(r.get("month")) in want]

    def count(r: dict[str, Any]) -> dict[str, int]:
        return {
            "positive": int(_num(r.get("positive"))),
            "neutral": int(_num(r.get("neutral"))),
            "negative": int(_num(r.get("negative"))),
            "total": int(_num(r.get("total"))),
        }

    def summarize(items: dict[str, dict[str, int]], key: str) -> list[dict[str, Any]]:
        out = []
        for name, c in items.items():
            rated = c["positive"] + c["neutral"] + c["negative"]
            shown = c["total"] if s == "all" else c[s]
            out.append(
                {
                    key: name,
                    **c,
                    "responses": shown,
                    "csat": _share(c["positive"], rated),
                    "neutral_percent": _share(c["neutral"], rated),
                    "negative_percent": _share(c["negative"], rated),
                }
            )
        return sorted((o for o in out if o["responses"] > 0), key=lambda o: (-o["responses"], str(o[key]).lower()))

    by_company: dict[str, dict[str, int]] = {}
    by_month: dict[str, dict[str, int]] = {m: {"positive": 0, "neutral": 0, "negative": 0, "total": 0} for m in chosen}
    for r in rows:
        c = count(r)
        for target, key in ((by_company, str(r.get("company") or "")), (by_month, str(r["month"]))):
            cell = target.setdefault(key, {"positive": 0, "neutral": 0, "negative": 0, "total": 0})
            for k, v in c.items():
                cell[k] += v
    weeks = recent_weeks(staff, months)
    want_w = set(weeks)
    by_member: dict[str, dict[str, int]] = {}
    for r in (staff or {}).get("rows") or []:
        if str(r.get("week")) not in want_w:
            continue
        sv = r.get("surveys") or {}
        total = int(_num(sv.get("total_surveys")))
        if total <= 0:
            continue
        cell = by_member.setdefault(str(r.get("engineer") or ""), {"positive": 0, "neutral": 0, "negative": 0, "total": 0})
        cell["total"] += total
        for k in ("positive", "neutral", "negative"):
            cell[k] += int(_num(sv.get(k)))
    recent = [x for x in (csat or {}).get("recent") or [] if s == "all" or x.get("sentiment") == s]
    totals = {k: sum(v[k] for v in by_month.values()) for k in ("positive", "neutral", "negative", "total")}
    everyone = summarize({"All": totals}, "name")
    overall = everyone[0] if everyone else None
    return {
        "months": chosen,
        "sentiment": s,
        "overall": overall,
        "by_company": summarize(by_company, "company"),
        "by_member": summarize(by_member, "member"),
        "by_month": summarize(by_month, "month") if by_month else [],
        "recent": sorted(recent, key=lambda x: str(x.get("date")), reverse=True)[:100],
    }


def month_end(month: str) -> datetime:
    """The first instant after the month (UTC), so "as of the end of the month" is everything before it."""
    y, m = int(month[:4]), int(month[5:7])
    return datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=UTC)


def licensing_matrix(
    current: list[dict[str, Any]], history: list[dict[str, Any]], names: dict[str, str], month: str, now: datetime | None = None
) -> dict[str, Any]:
    """A client by license-item table for ``month``. The newest month (or any month not yet over) is the counts held now; an earlier month is each count as of the end of that month, from the history (an
    item with no history that early is absent). ``current`` rows: ``{client_id, source, item, unit, count}``; ``history`` rows: ``{client_id, source, item, count, observed_at}`` (datetime)."""
    now = now or datetime.now(UTC)
    end = month_end(month)
    cells: dict[tuple[str, str, str], int] = {}
    units: dict[tuple[str, str], str] = {}
    if end > now:
        for r in current:
            cells[(str(r["client_id"]), str(r["source"]), str(r["item"]))] = int(r["count"])
            units[(str(r["source"]), str(r["item"]))] = str(r.get("unit") or "other")
    else:
        latest: dict[tuple[str, str, str], tuple[datetime, int]] = {}
        for h in history:
            at = h["observed_at"]
            if at >= end:
                continue
            k = (str(h["client_id"]), str(h["source"]), str(h["item"]))
            if k not in latest or at > latest[k][0]:
                latest[k] = (at, int(h["count"]))
        for k, (_, n) in latest.items():
            if n > 0:
                cells[k] = n
        for r in current:
            units[(str(r["source"]), str(r["item"]))] = str(r.get("unit") or "other")
    items = sorted({(s, i) for (_, s, i) in cells}, key=lambda t: (t[0].lower(), t[1].lower()))
    by_client: dict[str, dict[str, int]] = {}
    for (cid, s, i), n in cells.items():
        by_client.setdefault(cid, {})[f"{s}|{i}"] = n
    return {
        "month": month,
        "as_of": "now" if end > now else end.date().isoformat(),
        "items": [
            {
                "key": f"{s}|{i}",
                "source": s,
                "item": i,
                "unit": units.get((s, i), "other"),
                "total": sum(c.get(f"{s}|{i}", 0) for c in by_client.values()),
            }
            for s, i in items
        ],
        "clients": sorted(
            ({"client_id": cid, "client": names.get(cid) or cid, "counts": c} for cid, c in by_client.items()),
            key=lambda c: c["client"].lower(),
        ),
    }


def user_roles(payload: dict[str, Any] | None) -> dict[str, Any]:
    """A client by Microsoft 365 directory role table: how many people hold each role, and who."""
    totals: dict[str, int] = {}
    clients = []
    for c in (payload or {}).get("clients") or []:
        counts: dict[str, int] = {}
        members: dict[str, list[dict[str, Any]]] = {}
        for r in c.get("roles") or []:
            role = str(r.get("role") or "")
            people = [
                {"name": str(m.get("name") or "")[:120], "upn": str(m.get("upn") or "")[:200], "enabled": m.get("enabled") is not False}
                for m in r.get("members") or []
            ]
            if not role or not people:
                continue
            counts[role] = len(people)
            members[role] = people
            totals[role] = totals.get(role, 0) + len(people)
        if counts:
            clients.append(
                {
                    "client_id": str(c.get("client_id") or ""),
                    "client": str(c.get("client_name") or ""),
                    "counts": counts,
                    "members": members,
                }
            )
    return {
        "roles": [{"role": r, "total": n} for r, n in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0].lower()))],
        "clients": sorted(clients, key=lambda c: c["client"].lower()),
    }

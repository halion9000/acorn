"""The Staff pages of Metrics (Rewst's metric dashboards, rebuilt), worked out from the datasets CORE sends (``metric_datasets``, migration 196). Nothing here reads HaloPSA or Dialpad: it only turns stored rows
into what a page shows, when a person asks.

``staff-weekly`` (per engineer per week; ``week`` is that week's Monday, YYYY-MM-DD)::

    {"weeks": [...], "rows": [{"week", "agent_id", "engineer", "team", "labor_hours", "billable_hours", "weekly_utilization" (percent), "days_off", "holidays",
      "days_worked", "closed", "ticket_updates", "comments_added", "created", "total_calls", "total_call_time" (minutes), "surveys": {"total_surveys", "survey_sum"}}]}

``dialpad-weekly``: ``{"weeks": [...], "rows": [{"week", "engineer", "email", "total_calls", "total_call_time" (minutes), "triage_inbound"}]}``.

A team is the HaloPSA team an engineer belongs to; a pod is a team (Rewst named the page "Pods", and its pods are the team names). Periods count whole weeks back from the newest week in the data: a month is 4 weeks
at most 52 for a year.
"""

from __future__ import annotations

from typing import Any

from app.services.month_window import chosen_window, pick_months

WEEKS_PER_MONTH = 4.345

ZERO_ROW: dict[str, float] = {
    "labor_hours": 0,
    "weekly_utilization": 0,
    "closed": 0,
    "ticket_updates": 0,
    "comments_added": 0,
    "created": 0,
    "total_calls": 0,
    "total_call_time": 0,
}


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def weeks_of(payload: dict[str, Any] | None) -> list[str]:
    """Every week in the data, oldest first."""
    rows = (payload or {}).get("rows") or []
    return sorted({str(r.get("week")) for r in rows if r.get("week")})


def recent_weeks(payload: dict[str, Any] | None, months: int) -> list[str]:
    """The newest weeks that make up ``months`` months (rounded up), oldest first."""
    weeks = weeks_of(payload)
    window = chosen_window()
    if window is not None:  # a custom range: the weeks that start inside it
        return [w for w in weeks if window[0] <= w[:7] <= window[1]]
    keep = max(1, round(months * WEEKS_PER_MONTH))
    return weeks[-keep:]


def _rows_in(payload: dict[str, Any] | None, weeks: list[str]) -> list[dict[str, Any]]:
    want = set(weeks)
    return [r for r in (payload or {}).get("rows") or [] if str(r.get("week")) in want]


def _active(r: dict[str, Any]) -> bool:
    return _num(r.get("labor_hours")) > 0 or _num(r.get("weekly_utilization")) > 0


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def week_available(r: dict[str, Any]) -> float:
    """Hours a person could work in a week: 40, less the hours of time off and of holidays (CORE sends both in hours, eight for a day, the way Rewst counts them); 0 when nothing is left."""
    return max(0.0, 40.0 - _num(r.get("days_off")) - _num(r.get("holidays")))


def week_util(r: dict[str, Any]) -> float | None:
    """The Rewst utilization of one person-week in percent: hours logged over the hours available; None when no hours are available."""
    avail = week_available(r)
    return round(_num(r.get("labor_hours")) / avail * 100, 2) if avail > 0 else None


def teams_of(payload: dict[str, Any] | None) -> list[str]:
    return sorted({str(r.get("team") or "") for r in (payload or {}).get("rows") or [] if r.get("team")}, key=str.lower)


def staff_metrics(payload: dict[str, Any] | None, months: int, team: str | None = None) -> dict[str, Any]:
    """Utilization by week, tickets closed by week and utilization by team member, for all teams or one. Utilization is hours logged over the hours available (40 less time off and holidays), as Rewst counts it;
    a team's week is all its logged hours over all its available hours."""
    weeks = recent_weeks(payload, months)
    rows = [r for r in _rows_in(payload, weeks) if not team or str(r.get("team") or "") == team]
    by_week: dict[str, dict[str, Any]] = {w: {"week": w, "logged": 0.0, "avail": 0.0, "closed": 0} for w in weeks}
    members: dict[str, dict[str, Any]] = {}
    for r in rows:
        w = by_week[str(r["week"])]
        w["closed"] += int(_num(r.get("closed")))
        avail = week_available(r)
        logged = _num(r.get("labor_hours"))
        if avail > 0:
            w["logged"] += logged
            w["avail"] += avail
        name = " ".join(str(r.get("engineer") or "").split())
        m = members.setdefault(name, {"engineer": name, "team": str(r.get("team") or ""), "logged": 0.0, "avail": 0.0, "closed": 0, "labor_hours": 0.0, "by_week": {}})
        m["closed"] += int(_num(r.get("closed")))
        m["labor_hours"] += logged
        if avail > 0:
            m["logged"] += logged
            m["avail"] += avail
        m["by_week"][str(r["week"])] = week_util(r)
    pct = lambda logged, avail: round(logged / avail * 100, 1) if avail > 0 else None  # noqa: E731
    return {
        "weeks": [{"week": w["week"], "utilization": pct(w["logged"], w["avail"]), "closed": w["closed"]} for w in by_week.values()],
        "members": sorted(
            (
                {
                    "engineer": m["engineer"],
                    "team": m["team"],
                    "utilization": pct(m["logged"], m["avail"]),
                    "closed": m["closed"],
                    "labor_hours": round(m["labor_hours"], 2),
                    "by_week": m["by_week"],
                }
                for m in members.values()
            ),
            key=lambda m: m["engineer"].lower(),
        ),
        "teams": teams_of(payload),
    }


def pods(payload: dict[str, Any] | None, months: int) -> dict[str, Any]:
    """Metrics by pod (team): engineers, average utilization, tickets resolved and created, days off and holidays over the period, and each pod's engineers week by week."""
    weeks = recent_weeks(payload, months)
    rows = _rows_in(payload, weeks)
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        pod = str(r.get("team") or "(no team)")
        p = out.setdefault(
            pod, {"pod": pod, "engineers": set(), "utils": [], "resolved": 0, "created": 0, "days_off": 0.0, "holidays": 0.0, "weekly": {}}
        )
        p["engineers"].add(str(r.get("engineer") or ""))
        p["resolved"] += int(_num(r.get("closed")))
        p["created"] += int(_num(r.get("created")))
        p["days_off"] += _num(r.get("days_off"))
        p["holidays"] += _num(r.get("holidays"))
        if _active(r):
            p["utils"].append(_num(r.get("weekly_utilization")))
        wk = p["weekly"].setdefault(str(r["week"]), [])
        wk.append(
            {
                "engineer": str(r.get("engineer") or ""),
                "utilization": round(_num(r.get("weekly_utilization")), 1),
                "resolved": int(_num(r.get("closed"))),
                "created": int(_num(r.get("created"))),
                "days_off": _num(r.get("days_off")),
                "holidays": _num(r.get("holidays")),
            }
        )
    pods_out = []
    for p in out.values():
        pods_out.append(
            {
                "pod": p["pod"],
                "engineers": len(p["engineers"]),
                "utilization": _mean(p["utils"]),
                "resolved": p["resolved"],
                "created": p["created"],
                "days_off": round(p["days_off"], 1),
                "holidays": round(p["holidays"], 1),
                "weekly": [
                    {"week": w, "engineers": sorted(e, key=lambda x: x["engineer"].lower())} for w, e in sorted(p["weekly"].items())
                ],
            }
        )
    pods_out.sort(key=lambda p: (-(p["utilization"] or 0), p["pod"].lower()))
    # One row per engineer per week for the pod matrix: hours logged against the 40-hour week less time off and holidays (HaloPSA time off and holidays are hours), as the Rewst Pods page counts it.
    flat = [
        {
            "week": str(r["week"]),
            "pod": str(r.get("team") or "(no team)"),
            "engineer": " ".join(str(r.get("engineer") or "").split()),
            "resolved": int(_num(r.get("closed"))),
            "created": int(_num(r.get("created"))),
            "logged_hours": round(_num(r.get("labor_hours")), 2),
            "days_off": _num(r.get("days_off")),
            "holidays": _num(r.get("holidays")),
        }
        for r in rows
    ]
    return {"weeks": weeks, "pods": pods_out, "rows": flat}


def ticket_updates(payload: dict[str, Any] | None, months: int, members: list[str] | None = None) -> dict[str, Any]:
    """Ticket updates per team member per week for the period, for the members chosen (all when none are)."""
    weeks = recent_weeks(payload, months)
    want = set(members or [])
    table: dict[str, dict[str, int]] = {}
    detail: dict[str, dict[str, dict[str, int]]] = {}
    for r in _rows_in(payload, weeks):
        name = str(r.get("engineer") or "")
        if want and name not in want:
            continue
        row = table.setdefault(name, {})
        row[str(r["week"])] = row.get(str(r["week"]), 0) + int(_num(r.get("ticket_updates")))
        d = detail.setdefault(name, {}).setdefault(str(r["week"]), {"comments": 0, "updated": 0, "resolved": 0})
        d["comments"] += int(_num(r.get("comments_added")))
        d["updated"] += int(_num(r.get("ticket_updates")))
        d["resolved"] += int(_num(r.get("closed")))
    everyone = sorted({str(r.get("engineer") or "") for r in (payload or {}).get("rows") or []}, key=str.lower)
    return {
        "weeks": weeks,
        "members": everyone,
        "rows": [
            {"engineer": n, "total": sum(v.values()), "by_week": v, "detail": detail.get(n, {})}
            for n, v in sorted(table.items(), key=lambda kv: (-sum(kv[1].values()), kv[0].lower()))
        ],
        "weekly_total": {w: sum(v.get(w, 0) for v in table.values()) for w in weeks},
    }


def dialpad(payload: dict[str, Any] | None, months: int, engineer: str | None = None) -> dict[str, Any]:
    """Triage inbound calls by week, hours on call by week, and calls and hours per team member per week."""
    weeks = recent_weeks(payload, months)
    rows = [r for r in _rows_in(payload, weeks) if not engineer or str(r.get("engineer") or "") == engineer]
    by_week = {w: {"week": w, "triage_inbound": 0, "hours_on_call": 0.0, "calls": 0} for w in weeks}
    people: dict[str, dict[str, Any]] = {}
    for r in rows:
        w = by_week[str(r["week"])]
        w["triage_inbound"] += int(_num(r.get("triage_inbound")))
        w["hours_on_call"] += _num(r.get("total_call_time")) / 60
        w["calls"] += int(_num(r.get("total_calls")))
        name = str(r.get("engineer") or "")
        p = people.setdefault(name, {"engineer": name, "calls": 0, "hours": 0.0, "by_week": {}})
        p["calls"] += int(_num(r.get("total_calls")))
        p["hours"] += _num(r.get("total_call_time")) / 60
        p["by_week"][str(r["week"])] = {"calls": int(_num(r.get("total_calls"))), "hours": round(_num(r.get("total_call_time")) / 60, 2)}
    return {
        "weeks": [{**w, "hours_on_call": round(w["hours_on_call"], 2)} for w in by_week.values()],
        "people": sorted(
            ({**p, "hours": round(p["hours"], 2)} for p in people.values()), key=lambda p: (-p["calls"], p["engineer"].lower())
        ),
        "engineers": sorted({str(r.get("engineer") or "") for r in (payload or {}).get("rows") or []}, key=str.lower),
    }


def meetings(payload: dict[str, Any] | None, months: int, team: str | None = None) -> dict[str, Any]:
    """Meeting hours per team member per week for the period, the total by week, and the total for each team (the Rewst Meetings page). A person's team is the one on their row; people with none are Unassigned."""
    weeks = recent_weeks(payload, months)
    rows = [r for r in _rows_in(payload, weeks) if not team or (str(r.get("team") or "") or "Unassigned") == team]
    people: dict[str, dict[str, Any]] = {}
    by_week = {w: 0.0 for w in weeks}
    teams: dict[str, float] = {}
    for r in rows:
        hours = max(0.0, _num(r.get("total_hours")))
        who = str(r.get("engineer") or r.get("email") or "")
        t = str(r.get("team") or "") or "Unassigned"
        p = people.setdefault(who, {"engineer": who, "team": t, "total": 0.0, "by_week": {}})
        p["total"] += hours
        p["by_week"][str(r["week"])] = round(hours, 2)
        by_week[str(r["week"])] += hours
        teams[t] = teams.get(t, 0.0) + hours
    return {
        "weeks": weeks,
        "total_hours": round(sum(by_week.values()), 2),
        "by_week": [{"week": w, "hours": round(h, 2)} for w, h in by_week.items()],
        "people": sorted(({**p, "total": round(p["total"], 2)} for p in people.values()), key=lambda p: (-p["total"], p["engineer"].lower())),
        "by_team": sorted(({"team": t, "hours": round(h, 2)} for t, h in teams.items()), key=lambda x: (-x["hours"], x["team"].lower())),
        "teams": sorted({str(r.get("team") or "") or "Unassigned" for r in (payload or {}).get("rows") or []}, key=str.lower),
    }


def _name_key(name: Any) -> str:
    return " ".join(str(name or "").lower().split())


def without_excluded(key: str, payload: dict[str, Any] | None, excluded: list[str]) -> dict[str, Any] | None:
    """The dataset with the people marked excluded left out of what is shown (pure). Only people-shaped rows go: the weekly staff, Dialpad and meeting rows by engineer, and the stale tickets by their tech. Tickets, client counts and totals worked out from client rows are untouched."""
    # CORE names the agents the Rewst dashboards do not show as people (disabled, service accounts, hidden teams, gone): they are left out like the ones marked in Settings.
    hidden = (payload or {}).get("hidden_engineers") if isinstance((payload or {}).get("hidden_engineers"), list) else []
    skip = {_name_key(n) for n in [*excluded, *hidden] if _name_key(n)}
    if not payload or not skip:
        return payload
    out = dict(payload)
    if key in ("staff-weekly", "dialpad-weekly", "meetings-weekly") and isinstance(payload.get("rows"), list):
        out["rows"] = [r for r in payload["rows"] if _name_key(r.get("engineer")) not in skip]
    elif key == "ticket-detail" and isinstance(payload.get("stale"), list):
        out["stale"] = [s for s in payload["stale"] if _name_key(s.get("agent")) not in skip]
    return out


def engineers_of(payload: dict[str, Any] | None) -> list[str]:
    """Every engineer name in the weekly staff data, sorted without regard to case (pure)."""
    hidden = {_name_key(n) for n in (payload or {}).get("hidden_engineers") or []}
    return sorted({str(r.get("engineer")) for r in (payload or {}).get("rows") or [] if r.get("engineer") and _name_key(r.get("engineer")) not in hidden}, key=str.lower)


def weekly_comparison(payload: dict[str, Any] | None, week: str | None = None) -> dict[str, Any]:
    """The Weekly Tech Comparison for one week (the newest in the data when none is asked for): per engineer, grouped by pod, the days worked, tickets new, opened and closed the same week, older tickets closed, closed in all, net (closed less new), new and closed per day worked, and the Dialpad call tickets left out; and the same for all pods.

    ``has_detail`` is False while CORE has not yet sent the new ticket fields (the page says it is waiting for CORE's next round)."""
    weeks = weeks_of(payload)
    chosen = week if week in weeks else (weeks[-1] if weeks else None)
    rows = _rows_in(payload, [chosen]) if chosen else []
    has_detail = any("new_tickets" in r for r in rows)

    def line(group: list[dict[str, Any]]) -> dict[str, Any]:
        days = sum(_num(r.get("days_worked", 5)) for r in group)
        new = int(sum(_num(r.get("new_tickets")) for r in group))
        closed = int(sum(_num(r.get("closed_tickets")) for r in group))
        return {
            "days_worked": round(days, 1),
            "new": new,
            "opened_closed": int(sum(_num(r.get("opened_closed")) for r in group)),
            "older_closed": int(sum(_num(r.get("older_closed")) for r in group)),
            "closed": closed,
            "net": closed - new,
            "new_per_day": round(new / days, 1) if days > 0 else None,
            "closed_per_day": round(closed / days, 1) if days > 0 else None,
            "calls_excluded": int(sum(_num(r.get("calls_excluded")) for r in group)),
        }

    people = [r for r in rows if r.get("team") and (_active(r) or _num(r.get("new_tickets")) or _num(r.get("closed_tickets")))]
    people.sort(key=lambda r: (str(r.get("team")), str(r.get("engineer")).lower()))
    return {
        "weeks": weeks,
        "week": chosen,
        "has_detail": has_detail,
        "rows": [{"pod": str(r.get("team")), "engineer": str(r.get("engineer")), **line([r])} for r in people],
        "total": line(people),
    }


def halo_user_roles(payload: dict[str, Any] | None, clients: list[str] | None = None) -> dict[str, Any]:
    """The HaloPSA user roles page (the Rewst User Roles page): for each client how many users are in each role, with each client's total and each role's total. ``clients`` limits the rows to those names (all when none)."""
    roles = sorted({str(r) for r in (payload or {}).get("roles") or []}, key=str.lower)
    want = set(clients or [])
    rows = []
    for c in (payload or {}).get("clients") or []:
        name = str(c.get("client") or "")
        if want and name not in want:
            continue
        counts = {r: int((c.get("counts") or {}).get(r) or 0) for r in roles}
        rows.append({"client": name, "client_id": str(c.get("client_id") or ""), "counts": counts, "total": sum(counts.values())})
    rows.sort(key=lambda r: r["client"].lower())
    return {
        "roles": [{"role": r, "total": sum(x["counts"][r] for x in rows)} for r in roles],
        "clients": rows,
        "all_clients": sorted({str(c.get("client") or "") for c in (payload or {}).get("clients") or []}, key=str.lower),
        "without_client": int((payload or {}).get("without_client") or 0),
        "unread": [str(u) for u in (payload or {}).get("unread") or []],
    }


def hours_distribution(profit_payload: dict[str, Any] | None, months: int) -> dict[str, Any]:
    """Hours worked per person by ticket type (the charge type) for the newest ``months`` months of the HaloPSA hours summary, with each person's total and each type's share of all hours."""
    all_months = sorted({str(m) for m in (profit_payload or {}).get("months") or []})
    chosen = set(pick_months(all_months, months))
    agents = {str(a.get("id")): str(a.get("name") or "") for a in (profit_payload or {}).get("agents") or []}
    cell: dict[str, dict[str, float]] = {}
    types: dict[str, float] = {}
    for h in (profit_payload or {}).get("hours") or []:
        if str(h.get("month")) not in chosen:
            continue
        who = agents.get(str(h.get("agent_id") or "")) or f"Agent {h.get('agent_id')}"
        kind = str(h.get("charge_type") or "(none)")
        hours = _num(h.get("hours"))
        cell.setdefault(who, {})[kind] = cell.get(who, {}).get(kind, 0.0) + hours
        types[kind] = types.get(kind, 0.0) + hours
    total = sum(types.values())
    type_names = [t for t, _ in sorted(types.items(), key=lambda kv: (-kv[1], kv[0].lower()))]
    return {
        "months": sorted(chosen),
        "total_hours": round(total, 2),
        "types": [
            {"type": t, "hours": round(types[t], 2), "share_percent": round(types[t] / total * 100, 1) if total else None}
            for t in type_names
        ],
        "people": sorted(
            (
                {"name": n, "total": round(sum(v.values()), 2), "by_type": {t: round(v.get(t, 0.0), 2) for t in type_names}}
                for n, v in cell.items()
            ),
            key=lambda p: (-p["total"], p["name"].lower()),
        ),
    }


# ---- The Service Desk Scorecard (the scoring rules Rewst's template used, kept exactly) -----------------------------------------------------------------------------------

METRIC_ORDER = ("Tickets Closed", "Tickets Updated", "Labor Hours", "Calls Made", "Call Time", "CSAT", "Utilization")

_VOLUME_5 = [[30, 5], [24, 4], [19, 3], [13, 2], [1, 1]]
METRIC_CONFIG: dict[str, dict[str, Any]] = {
    "Tickets Closed": {
        "field": "closed",
        "weight": 3.0,
        "floor": 0,
        "by_days": {
            5: _VOLUME_5,
            4: [[24, 5], [19, 4], [15, 3], [10, 2], [1, 1]],
            3: [[18, 5], [14, 4], [11, 3], [8, 2], [1, 1]],
            2: [[12, 5], [10, 4], [8, 3], [5, 2], [1, 1]],
            1: [[6, 5], [5, 4], [4, 3], [3, 2], [1, 1]],
        },
    },
    "Tickets Updated": {
        "field": "ticket_updates",
        "weight": 1.5,
        "floor": 0,
        "by_days": {
            5: _VOLUME_5,
            4: [[24, 5], [19, 4], [15, 3], [10, 2], [1, 1]],
            3: [[18, 5], [14, 4], [11, 3], [8, 2], [1, 1]],
            2: [[12, 5], [10, 4], [8, 3], [5, 2], [1, 1]],
            1: [[6, 5], [5, 4], [4, 3], [3, 2], [1, 1]],
        },
    },
    "Labor Hours": {
        "field": "labor_hours",
        "weight": 2.0,
        "floor": 1,
        "by_days": {
            5: [[30, 5], [20, 4], [10, 3], [1, 2]],
            4: [[24, 5], [16, 4], [8, 3], [1, 2]],
            3: [[18, 5], [12, 4], [6, 3], [1, 2]],
            2: [[12, 5], [8, 4], [4, 3], [1, 2]],
            1: [[6, 5], [4, 4], [2, 3], [1, 2]],
        },
    },
    "Calls Made": {
        "field": "total_calls",
        "weight": 0.5,
        "floor": 0,
        "by_days": {
            5: [[20, 5], [12, 4], [8, 3], [3, 2], [1, 1]],
            4: [[16, 5], [10, 4], [6, 3], [2, 2], [1, 1]],
            3: [[12, 5], [7, 4], [5, 3], [2, 2], [1, 1]],
            2: [[8, 5], [5, 4], [3, 3], [1, 2]],
            1: [[4, 5], [2, 4], [1, 2]],
        },
    },
    "Call Time": {
        "field": "total_call_time",
        "scale": 1 / 60,  # the data is minutes; the brackets are hours
        "weight": 0.5,
        "floor": 1,
        "by_days": {
            5: [[5, 5], [4, 4], [3, 3], [2, 2]],
            4: [[4, 5], [3.2, 4], [2.4, 3], [1.6, 2]],
            3: [[3, 5], [2.4, 4], [1.8, 3], [1.2, 2]],
            2: [[2, 5], [1.6, 4], [1.2, 3], [0.8, 2]],
            1: [[1, 5], [0.8, 4], [0.6, 3], [0.4, 2]],
        },
    },
    "CSAT": {"field": None, "weight": 1.0, "floor": 0, "brackets": [[5, 5], [4, 4], [3, 3], [2, 2], [1, 1]]},
    "Utilization": {"field": "weekly_utilization", "weight": 2.5, "floor": 0, "brackets": [[75, 5], [60, 4], [45, 3], [30, 2], [1, 1]]},
}


def day_bucket(row: dict[str, Any]) -> int:
    """Days worked for choosing a bracket row: the (fractional) days worked rounded and held to 0..5; a week with no day count counts as a full five."""
    dw = row.get("days_worked")
    if dw is None:
        return 5
    return int(min(5, max(0, round(_num(dw)))))


def has_activity(row: dict[str, Any]) -> bool:
    keys = ("labor_hours", "weekly_utilization", "closed", "ticket_updates", "comments_added", "total_calls", "total_call_time")
    if any(_num(row.get(k)) > 0 for k in keys):
        return True
    s = row.get("surveys") or {}
    return _num(s.get("total_surveys")) > 0


def metric_value(metric: str, row: dict[str, Any]) -> float | None:
    cfg = METRIC_CONFIG[metric]
    if metric == "CSAT":
        s = row.get("surveys") or {}
        total = _num(s.get("total_surveys"))
        return _num(s.get("survey_sum")) / total if total > 0 else None
    if row.get(cfg["field"]) is None:
        return None  # not reported at all (calls when Dialpad is not connected): nothing to score, so it leaves the weighting
    raw = _num(row.get(cfg["field"]))
    return raw * cfg["scale"] if "scale" in cfg else raw


def metric_score(metric: str, row: dict[str, Any]) -> int | None:
    """One metric's 1-5 score for a week, or None when there is nothing to score (CSAT with no surveys)."""
    cfg = METRIC_CONFIG[metric]
    value = metric_value(metric, row)
    if value is None:
        return None
    if "by_days" in cfg:
        table = cfg["by_days"].get(max(1, day_bucket(row))) or cfg["by_days"][5]
    else:
        table = cfg["brackets"]
    for threshold, score in table:
        if value >= threshold:
            return int(score)
    return int(cfg["floor"])


def week_score(row: dict[str, Any]) -> float | None:
    """The weighted average of the metric scores for one week, one decimal, or None when the week is not graded (no activity, or a full week off)."""
    if not has_activity(row) or day_bucket(row) == 0:
        return None
    total = weight = 0.0
    for metric in METRIC_ORDER:
        s = metric_score(metric, row)
        if s is None:
            continue
        total += s * METRIC_CONFIG[metric]["weight"]
        weight += METRIC_CONFIG[metric]["weight"]
    return round(total / weight * 10) / 10 if weight > 0 else None


def grade(avg: float | None) -> str:
    if avg is None:
        return "-"
    if avg >= 4.5:
        return "S"
    if avg >= 4.0:
        return "A"
    if avg >= 3.0:
        return "B"
    if avg >= 2.0:
        return "C"
    if avg >= 1.0:
        return "D"
    return "F"


def scorecard(payload: dict[str, Any] | None, months: int, member: str | None = None) -> dict[str, Any]:
    """The scorecard: every team member's average week score and grade for the period, and, for ``member``, each week's scores per metric, the weekly score trend and the grade."""
    weeks = recent_weeks(payload, months)
    by_person: dict[str, dict[str, dict[str, Any]]] = {}
    for r in _rows_in(payload, weeks):
        by_person.setdefault(str(r.get("engineer") or ""), {})[str(r["week"])] = r
    people = []
    for name, wk in by_person.items():
        scores = [s for s in (week_score(r) for r in wk.values()) if s is not None]
        avg = round(sum(scores) / len(scores), 2) if scores else None
        people.append(
            {
                "engineer": name,
                "team": str(next(iter(wk.values())).get("team") or ""),
                "weeks_scored": len(scores),
                "average": avg,
                "grade": grade(avg),
            }
        )
    people.sort(key=lambda p: (-(p["average"] if p["average"] is not None else -1), p["engineer"].lower()))
    detail = None
    if member and member in by_person:
        rows = []
        sums = {m: 0 for m in METRIC_ORDER}
        counts = {m: 0 for m in METRIC_ORDER}
        for w in sorted(by_person[member], reverse=True):
            r = by_person[member][w]
            ws = week_score(r)
            factors = {m: (metric_score(m, r) if ws is not None else None) for m in METRIC_ORDER}
            for m, f in factors.items():
                if f is not None:
                    sums[m] += f
                    counts[m] += 1
            rows.append(
                {
                    "week": w,
                    "score": ws,
                    "grade": grade(ws),
                    "factors": factors,
                    "values": {m: (None if metric_value(m, r) is None else round(metric_value(m, r) or 0, 2)) for m in METRIC_ORDER},
                    "days_worked": day_bucket(r),
                }
            )
        scored = [r["score"] for r in rows if r["score"] is not None]
        avg = round(sum(scored) / len(scored), 2) if scored else None
        detail = {
            "engineer": member,
            "average": avg,
            "grade": grade(avg),
            "weeks": rows,
            "metric_averages": {m: (round(sums[m] / counts[m], 2) if counts[m] else None) for m in METRIC_ORDER},
            "trend": [{"week": r["week"], "score": r["score"]} for r in reversed(rows)],
        }
    return {
        "weeks": weeks,
        "metrics": list(METRIC_ORDER),
        "weights": {m: METRIC_CONFIG[m]["weight"] for m in METRIC_ORDER},
        "people": people,
        "detail": detail,
    }


GRADES = (("S", 4.5), ("A", 4.0), ("B", 3.0), ("C", 2.0), ("D", 1.0))
METRIC_UNITS = {"Tickets Closed": "tickets", "Tickets Updated": "tickets", "Labor Hours": "hours", "Calls Made": "calls", "Call Time": "hours", "CSAT": "average survey score (1-5)", "Utilization": "percent"}


def scoring_template() -> dict[str, Any]:
    """The template the scorecard is worked out with, as the Settings page shows it (read only): each metric's weight and its share of the score, the brackets (a value at or above the threshold earns the score; below the last
    threshold earns the floor), the table used for each number of days worked, and the grade cut-offs."""
    total = sum(float(METRIC_CONFIG[m]["weight"]) for m in METRIC_ORDER)
    out = []
    for m in METRIC_ORDER:
        cfg = METRIC_CONFIG[m]
        tables = {str(d): t for d, t in sorted(cfg["by_days"].items(), reverse=True)} if "by_days" in cfg else {"any": cfg["brackets"]}
        out.append(
            {
                "metric": m,
                "unit": METRIC_UNITS[m],
                "weight": float(cfg["weight"]),
                "share": round(float(cfg["weight"]) / total * 100, 1) if total else 0.0,
                "floor": int(cfg["floor"]),
                "by_days_worked": "by_days" in cfg,
                "tables": {k: [[float(th), int(sc)] for th, sc in v] for k, v in tables.items()},
            }
        )
    return {"metrics": out, "total_weight": total, "grades": [{"grade": g, "from": c} for g, c in GRADES] + [{"grade": "F", "from": 0.0}]}

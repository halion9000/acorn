"""Client profitability from the HaloPSA summary CORE sends (``finance_profit_snapshots``, migration 191), the labor rates the owner set and, for information, the cost HaloPSA's recurring invoices carry.

Per client per month: revenue (what was invoiced, before tax, credit notes taken off), hours worked, labor cost (hours x the hourly cost of the agent who worked them) and what is left after labor. Money
is in whole cents (``Decimal``). The most specific labor rate wins: the agent's own, else the agent's team, else the default (65.00 an hour until the owner sets one: the same flat figure the Rewst
dashboard used).

What is NOT in the number, and is said so on the page: software, hardware, travel, equipment, sales and marketing and overhead. Software is shown per invoice run from the recurring invoices, never
turned into a month (HaloPSA's period code is not documented here, and a guess would put the wrong number on a page about money). Hours are matched to a client by name; hours whose name matches no
invoiced client are listed, never dropped.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.services.finance import money

DEFAULT_RATE = Decimal("65.00")
ZERO = Decimal("0.00")


def _dec(v: Any) -> Decimal:
    try:
        return money(v)
    except Exception:
        return ZERO


def name_key(name: Any) -> str:
    """A client name as a matching key: lower case, letters and digits only."""
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def resolve_rates(rates: list[dict[str, Any]]) -> dict[str, Any]:
    """The rate table as lookups: ``default`` (a Decimal), ``team`` and ``agent`` (key to Decimal)."""
    out: dict[str, Any] = {"default": DEFAULT_RATE, "team": {}, "agent": {}}
    for r in rates:
        scope, key, rate = str(r.get("scope")), str(r.get("key") or ""), _dec(r.get("hourly_rate"))
        if scope == "default":
            out["default"] = rate
        elif scope in ("team", "agent") and key:
            out[scope][key] = rate
    return out


def rate_for(agent_id: str, agents: dict[str, dict[str, Any]], rates: dict[str, Any]) -> tuple[Decimal, str]:
    """The hourly cost of one agent and where it came from (agent, team, default)."""
    if agent_id in rates["agent"]:
        return rates["agent"][agent_id], "agent"
    team = str((agents.get(agent_id) or {}).get("team") or "")
    if team and team in rates["team"]:
        return rates["team"][team], "team"
    return rates["default"], "default"


def available_months(snapshot: dict[str, Any]) -> list[str]:
    return sorted({str(m) for m in snapshot.get("months") or []})


def profit_for_month(
    snapshot: dict[str, Any], rates: list[dict[str, Any]], month: str, software_per_run: dict[str, Decimal] | None = None
) -> dict[str, Any]:
    """The month's rows, largest revenue first, with totals, the hours that matched no client, and which agents were priced by the default rate."""
    table = resolve_rates(rates)
    agents = {str(a.get("id")): a for a in snapshot.get("agents") or []}
    by_client: dict[str, dict[str, Any]] = {}
    by_name: dict[str, str] = {}
    for inv in snapshot.get("invoices") or []:
        if str(inv.get("month")) != month:
            continue
        cid = str(inv.get("client_id") or "")
        c = by_client.setdefault(
            cid,
            {
                "client_id": cid,
                "client_name": str(inv.get("client_name") or ""),
                "revenue": ZERO,
                "invoices": 0,
                "hours": Decimal("0"),
                "labor": ZERO,
            },
        )
        c["revenue"] += _dec(inv.get("revenue"))
        c["invoices"] += int(inv.get("invoices") or 0)
        by_name[name_key(inv.get("client_name"))] = cid
    unmatched: dict[str, dict[str, Any]] = {}
    defaulted: dict[str, dict[str, Any]] = {}
    for h in snapshot.get("hours") or []:
        if str(h.get("month")) != month:
            continue
        hours = Decimal(str(h.get("hours") or 0))
        agent_id = str(h.get("agent_id") or "")
        rate, source = rate_for(agent_id, agents, table)
        cost = money(hours * rate)
        cid = by_name.get(name_key(h.get("client")))
        if cid is None:
            u = unmatched.setdefault(
                str(h.get("client") or ""), {"client": str(h.get("client") or ""), "hours": Decimal("0"), "labor": ZERO}
            )
            u["hours"] += hours
            u["labor"] += cost
        else:
            by_client[cid]["hours"] += hours
            by_client[cid]["labor"] += cost
        if source == "default":
            d = defaulted.setdefault(
                agent_id,
                {"agent_id": agent_id, "name": str((agents.get(agent_id) or {}).get("name") or f"Former agent {agent_id}"), "hours": Decimal("0")},
            )
            d["hours"] += hours
    rows: list[dict[str, Any]] = []
    total_rev = total_labor = total_hours = ZERO
    for c in by_client.values():
        after = c["revenue"] - c["labor"]
        rows.append(
            {
                "client_id": c["client_id"],
                "client_name": c["client_name"],
                "revenue": c["revenue"],
                "invoices": c["invoices"],
                "hours": c["hours"].quantize(Decimal("0.01")),
                "labor": c["labor"],
                "after_labor": after,
                "margin_percent": float((after / c["revenue"] * 100).quantize(Decimal("0.1"))) if c["revenue"] > 0 else None,
                "software_per_run": (software_per_run or {}).get(name_key(c["client_name"])),
            }
        )
        total_rev += c["revenue"]
        total_labor += c["labor"]
        total_hours += c["hours"]
    rows.sort(key=lambda r: (-r["revenue"], r["client_name"].lower()))
    total_after = total_rev - total_labor
    return {
        "month": month,
        "rows": rows,
        "totals": {
            "revenue": total_rev,
            "labor": total_labor,
            "after_labor": total_after,
            "hours": total_hours.quantize(Decimal("0.01")),
            "margin_percent": float((total_after / total_rev * 100).quantize(Decimal("0.1"))) if total_rev > 0 else None,
        },
        "unmatched_hours": sorted(
            ({"client": u["client"], "hours": u["hours"].quantize(Decimal("0.01")), "labor": u["labor"]} for u in unmatched.values()),
            key=lambda u: -u["hours"],
        ),
        "agents_on_default_rate": sorted(
            ({"agent_id": d["agent_id"], "name": d["name"], "hours": d["hours"].quantize(Decimal("0.01"))} for d in defaulted.values()),
            key=lambda d: -d["hours"],
        ),
        "default_rate": table["default"],
    }


def software_per_run(halo_snapshot: dict[str, Any] | None) -> dict[str, Decimal]:
    """What each client's recurring invoices cost per invoice run (quantity x unit cost, lines that have a cost), by client-name key. Information only: see the module note."""
    out: dict[str, Decimal] = {}
    for rec in (halo_snapshot or {}).get("recurring") or []:
        key = name_key(rec.get("client_name"))
        if not key:
            continue
        total = sum(
            (money(Decimal(str(ln.get("qty") or 0)) * Decimal(str(ln.get("unit_cost") or 0))) for ln in rec.get("lines") or []), ZERO
        )
        out[key] = out.get(key, ZERO) + total
    return out


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _tickets_behind(rows: Any, month: str, key: str, agents: dict[str, Any], hours_total: Decimal) -> dict[str, Any] | None:
    """The tickets one client's hours in a month went on, most hours first, and the hours not on a listed ticket. None when CORE has not sent ticket-level time (an older CORE)."""
    if rows is None:
        return None
    mine = [t for t in rows if str(t.get("month")) == month and name_key(t.get("client")) == key]
    listed = [
        {
            "ticket_id": str(t.get("ticket_id") or ""),
            "summary": str(t.get("summary") or ""),
            "hours": round(_f(t.get("hours")), 2),
            "entries": int(t.get("entries") or 0),
            "agents": [str((agents.get(str(a)) or {}).get("name") or f"Former agent {a}") for a in (t.get("agent_ids") or [])],
        }
        for t in mine
    ]
    listed.sort(key=lambda t: (-t["hours"], int(t["ticket_id"] or 0)))
    other = round(max(0.0, float(hours_total) - sum(t["hours"] for t in listed)), 2)
    return {"rows": listed, "other_hours": other}


def client_breakdown(
    snapshot: dict[str, Any],
    lines_payload: dict[str, Any] | None,
    halo_snapshot: dict[str, Any] | None,
    rates: list[dict[str, Any]],
    client_id: str,
    month: str,
    month_tickets: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """What one client's Profitability row for a month is made of, or None when the client was not invoiced that month.

    ``revenue`` and ``invoices`` are the invoice totals CORE sent; ``invoice_lines`` are the lines of those invoices (billed, or free when the line cost the client nothing); ``hours`` are the time logged for the
    client by agent with the hourly cost applied and where each rate came from; ``recurring`` are the lines of the client's recurring invoice (what it bills each run, with the unit cost A.C.O.R.N holds). Nothing
    here is a new number: each part adds up to a figure on the row, and the parts that cannot be shown yet say so.
    """
    table = resolve_rates(rates)
    agents = {str(a.get("id")): a for a in snapshot.get("agents") or []}
    revenue = ZERO
    invoices = 0
    name = ""
    for inv in snapshot.get("invoices") or []:
        if str(inv.get("month")) == month and str(inv.get("client_id") or "") == client_id:
            revenue += _dec(inv.get("revenue"))
            invoices += int(inv.get("invoices") or 0)
            name = str(inv.get("client_name") or name)
    if not name and not invoices:
        return None
    key = name_key(name)
    lines = [
        {"item": str(r.get("item") or ""), "category": str(r.get("category") or "Other"), "quantity": _f(r.get("quantity")), "amount": round(_f(r.get("amount")), 2), "free": round(_f(r.get("amount")), 2) == 0}
        for r in (lines_payload or {}).get("rows") or []
        if str(r.get("month")) == month and str(r.get("client_id") or "") == client_id
    ]
    lines.sort(key=lambda ln: (-ln["amount"], ln["item"].lower()))
    by_agent: dict[str, dict[str, Any]] = {}
    by_charge: dict[str, Decimal] = {}
    for h in snapshot.get("hours") or []:
        if str(h.get("month")) != month or name_key(h.get("client")) != key:
            continue
        hours = Decimal(str(h.get("hours") or 0))
        aid = str(h.get("agent_id") or "")
        rate, source = rate_for(aid, agents, table)
        a = by_agent.setdefault(
            aid,
            {"agent_id": aid, "name": str((agents.get(aid) or {}).get("name") or f"Former agent {aid}"), "hours": Decimal("0"), "rate": rate, "rate_source": source, "cost": ZERO},
        )
        a["hours"] += hours
        a["cost"] += money(hours * rate)
        by_charge[str(h.get("charge_type") or "(none)")] = by_charge.get(str(h.get("charge_type") or "(none)"), Decimal("0")) + hours
    labor = sum((a["cost"] for a in by_agent.values()), ZERO)
    hours_total = sum((a["hours"] for a in by_agent.values()), Decimal("0"))
    recurring = [
        {
            "item": str(ln.get("item") or ""),
            "quantity": _f(ln.get("qty")),
            "unit_price": _f(ln.get("unit_price")),
            "unit_cost": _f(ln.get("unit_cost")),
            "free": _f(ln.get("unit_price")) == 0,
            "cost_per_run": round(_f(ln.get("qty")) * _f(ln.get("unit_cost")), 2),
        }
        for rec in (halo_snapshot or {}).get("recurring") or []
        if name_key(rec.get("client_name")) == key
        for ln in rec.get("lines") or []
    ]
    return {
        "client_id": client_id,
        "client_name": name,
        "month": month,
        "revenue": revenue,
        "invoices": invoices,
        "invoice_lines": lines,
        "invoice_lines_total": round(sum(ln["amount"] for ln in lines), 2),
        "free_lines": sum(1 for ln in lines if ln["free"]),
        "hours": hours_total.quantize(Decimal("0.01")),
        "labor": labor,
        "after_labor": revenue - labor,
        "by_agent": sorted(
            ({**a, "hours": a["hours"].quantize(Decimal("0.01"))} for a in by_agent.values()), key=lambda a: (-a["hours"], a["name"].lower())
        ),
        "by_charge_type": sorted(
            ({"charge_type": k, "hours": v.quantize(Decimal("0.01"))} for k, v in by_charge.items()), key=lambda c: (-c["hours"], c["charge_type"])
        ),
        "recurring": sorted(recurring, key=lambda r: (-r["quantity"] * r["unit_price"], r["item"].lower())),
        # The tickets of the month as CORE sends them on their own route; only an older CORE put them in the summary.
        "tickets": _tickets_behind(month_tickets if month_tickets is not None else snapshot.get("tickets"), month, key, agents, hours_total),
    }

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
                {"agent_id": agent_id, "name": str((agents.get(agent_id) or {}).get("name") or f"Agent {agent_id}"), "hours": Decimal("0")},
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

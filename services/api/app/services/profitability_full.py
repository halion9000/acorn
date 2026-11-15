"""The full profitability model, after finance's workbook ("Revenue to Net Income"): per client per month, revenue less direct labor, the labor true-up, software, travel, equipment and hardware (gross
profit), then sales and marketing and overhead (net income). Plus the workbook's other sheets: new clients, the summary by industry, hours by function and utilization, and the twelve-month net income ranking.

Costs come from ``finance_cost_entries`` (typed on the page now; QuickBooks fills them when it is connected). An entry with a client is charged to that client; one without is spread across the month's
clients by revenue (the workbook spreads by MRR; the Halo summary holds invoiced revenue, not recurring revenue, so revenue is the stand-in and the page says so). Spreading is exact to the cent. Nothing
is invented: a category with no entry is zero and listed in ``missing`` so the page can say which parts of the number are not filled in yet.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.finance import money
from app.services.profitability import ZERO, name_key, profit_for_month, rate_for, resolve_rates

CATEGORIES = ("payroll_cogs", "addon_software", "support_software", "travel", "equipment", "hardware", "sales_marketing", "overhead")
DEFAULT_TARGET = Decimal("20")
TIERS = (20, 40, 60, 80, 120)
_ROW_COSTS = ("labor_trueup", "addon_software", "support_software", "travel", "equipment", "hardware", "sales_marketing", "overhead")


def spread(amount: Decimal, weights: dict[str, Decimal]) -> dict[str, Decimal]:
    """``amount`` split in proportion to ``weights`` to the cent, the leftover cents going to the largest remainders, so the parts add up to exactly ``amount``. Nothing when there is no weight."""
    total = sum((w for w in weights.values() if w > 0), Decimal("0"))
    if total <= 0 or amount == 0:
        return {}
    cents = int((amount * 100).to_integral_value())
    exact = {k: Decimal(cents) * w / total for k, w in weights.items() if w > 0}
    floor = {k: int(v) for k, v in exact.items()}
    left = cents - sum(floor.values())
    order = sorted(exact, key=lambda k: (abs(exact[k] - floor[k]), k), reverse=True)
    step = 1 if left > 0 else -1
    for i in range(abs(left)):
        floor[order[i % len(order)]] += step
    return {k: Decimal(v) / 100 for k, v in floor.items()}


def _pct(part: Decimal, whole: Decimal) -> float | None:
    return float((part / whole * 100).quantize(Decimal("0.1"))) if whole > 0 else None


def _blank(key: str, name: str) -> dict[str, Any]:
    return {"client_key": key, "client_name": name, "revenue": ZERO, "hours": Decimal("0.00"), "direct_labor": ZERO} | {
        k: ZERO for k in _ROW_COSTS
    }


def first_months(snapshot: dict[str, Any]) -> dict[str, str]:
    """The first month each client (by name key) has revenue in the summary."""
    first: dict[str, str] = {}
    for inv in snapshot.get("invoices") or []:
        key, month = name_key(inv.get("client_name")), str(inv.get("month"))
        if key and (key not in first or month < first[key]):
            first[key] = month
    return first


def full_month(
    snapshot: dict[str, Any], rates: list[dict[str, Any]], month: str, costs: list[dict[str, Any]], master: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    base = profit_for_month(snapshot, rates, month)
    months = sorted({str(m) for m in snapshot.get("months") or []})
    first = first_months(snapshot)
    rows: dict[str, dict[str, Any]] = {}
    for r in base["rows"]:
        key = name_key(r["client_name"])
        row = rows.setdefault(key, _blank(key, r["client_name"]))
        row["revenue"] += r["revenue"]
        row["hours"] += r["hours"]
        row["direct_labor"] += r["labor"]
    mine = [c for c in costs if str(c.get("month")) == month]
    company: dict[str, Decimal] = {c: ZERO for c in CATEGORIES}
    for c in mine:
        cat, key, amount = str(c["category"]), str(c.get("client_key") or ""), money(c.get("amount"))
        if cat in ("payroll_cogs", "sales_marketing", "overhead") or not key:
            company[cat] += amount
        else:
            rows.setdefault(key, _blank(key, str(c.get("client_name") or key)))[cat] += amount
    weights = {k: r["revenue"] for k, r in rows.items()}
    unplaced: dict[str, Decimal] = {}

    def place(cat: str, column: str, amount: Decimal, by: dict[str, Decimal]) -> None:
        shares = spread(amount, by)
        for key, share in shares.items():
            rows[key][column] += share
        left = amount - sum(shares.values(), ZERO)
        if left != 0:
            unplaced[cat] = unplaced.get(cat, ZERO) + left

    for cat in ("support_software", "travel", "equipment", "hardware", "addon_software"):
        place(cat, cat, company[cat], weights)
    if company["payroll_cogs"] != 0:
        direct_total = sum((r["direct_labor"] for r in rows.values()), ZERO)
        place("payroll_cogs", "labor_trueup", company["payroll_cogs"] - direct_total, weights)
    first_of_all = months[0] if months else month
    new_keys = sorted(k for k, r in rows.items() if first.get(k) == month and month != first_of_all and r["revenue"] > 0)
    place("sales_marketing", "sales_marketing", company["sales_marketing"], {k: Decimal(1) for k in new_keys})
    place("overhead", "overhead", company["overhead"], weights)
    out_rows: list[dict[str, Any]] = []
    for key, r in rows.items():
        cost = sum(
            (r[k] for k in ("direct_labor", "labor_trueup", "addon_software", "support_software", "travel", "equipment", "hardware")), ZERO
        )
        gross = r["revenue"] - cost
        net = gross - r["sales_marketing"] - r["overhead"]
        m = master.get(key) or {}
        out_rows.append(
            r
            | {
                "total_cost": cost,
                "gross_profit": gross,
                "gross_margin": _pct(gross, r["revenue"]),
                "net_income": net,
                "net_margin": _pct(net, r["revenue"]),
                "industry": str(m.get("industry") or ""),
                "non_profit": bool(m.get("non_profit")),
                "new_client": key in new_keys,
            }
        )
    out_rows.sort(key=lambda r: (-r["revenue"], r["client_name"].lower()))
    cols = (
        "revenue",
        "direct_labor",
        "labor_trueup",
        "addon_software",
        "support_software",
        "travel",
        "equipment",
        "hardware",
        "total_cost",
        "gross_profit",
        "sales_marketing",
        "overhead",
        "net_income",
    )
    totals: dict[str, Any] = {c: sum((r[c] for r in out_rows), ZERO) for c in cols}
    totals["hours"] = sum((r["hours"] for r in out_rows), Decimal("0.00"))
    totals["gross_margin"] = _pct(totals["gross_profit"], totals["revenue"])
    totals["net_margin"] = _pct(totals["net_income"], totals["revenue"])
    entered = {str(c["category"]) for c in mine}
    return {
        "month": month,
        "rows": out_rows,
        "totals": totals,
        "missing": [c for c in CATEGORIES if c not in entered],
        "unmatched_hours": base["unmatched_hours"],
        "agents_on_default_rate": base["agents_on_default_rate"],
        "new_clients": [{"client_key": k, "client_name": rows[k]["client_name"], "revenue": rows[k]["revenue"]} for k in new_keys],
        "unplaced": unplaced,
    }


def by_industry(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The month's clients grouped by the industry in the client master ("Unassigned" when none), biggest revenue first."""
    groups: dict[str, dict[str, Any]] = {}
    for r in report["rows"]:
        label = r["industry"] or "Unassigned"
        g = groups.setdefault(
            label, {"industry": label, "clients": 0, "non_profit_clients": 0, "revenue": ZERO, "gross_profit": ZERO, "net_income": ZERO}
        )
        g["clients"] += 1
        g["non_profit_clients"] += 1 if r["non_profit"] else 0
        for k in ("revenue", "gross_profit", "net_income"):
            g[k] += r[k]
    out = list(groups.values())
    for g in out:
        g["gross_margin"], g["net_margin"] = _pct(g["gross_profit"], g["revenue"]), _pct(g["net_income"], g["revenue"])
    return sorted(out, key=lambda g: (-g["revenue"], g["industry"]))


def hours_report(snapshot: dict[str, Any], rates: list[dict[str, Any]], month: str, available_per_person: Decimal) -> dict[str, Any]:
    """Hours by function (the charge type) and by person with utilization: billable hours (everything but "No Charge") over the hours a person can work in a month."""
    table = resolve_rates(rates)
    agents = {str(a.get("id")): a for a in snapshot.get("agents") or []}
    func: dict[str, dict[str, Any]] = {}
    people: dict[str, dict[str, Any]] = {}
    for h in snapshot.get("hours") or []:
        if str(h.get("month")) != month:
            continue
        hours = Decimal(str(h.get("hours") or 0))
        agent_id, charge = str(h.get("agent_id") or ""), str(h.get("charge_type") or "(none)")
        billable = "no charge" not in charge.lower()
        cost = money(hours * rate_for(agent_id, agents, table)[0])
        f = func.setdefault(charge, {"function": charge, "billable": billable, "hours": Decimal("0"), "cost": ZERO})
        f["hours"] += hours
        f["cost"] += cost
        a = agents.get(agent_id) or {}
        p = people.setdefault(
            agent_id,
            {
                "agent_id": agent_id,
                "name": str(a.get("name") or f"Agent {agent_id}"),
                "team": str(a.get("team") or ""),
                "hours": Decimal("0"),
                "billable_hours": Decimal("0"),
            },
        )
        p["hours"] += hours
        if billable:
            p["billable_hours"] += hours
    q = Decimal("0.01")
    total = sum((f["hours"] for f in func.values()), Decimal("0"))
    return {
        "month": month,
        "available_hours_per_person": available_per_person,
        "total_hours": total.quantize(q),
        "by_function": sorted(
            ({**f, "hours": f["hours"].quantize(q), "share_percent": _pct(f["hours"], total)} for f in func.values()),
            key=lambda f: -f["hours"],
        ),
        "by_person": sorted(
            (
                {
                    **p,
                    "hours": p["hours"].quantize(q),
                    "billable_hours": p["billable_hours"].quantize(q),
                    "utilization_percent": _pct(p["billable_hours"], available_per_person),
                }
                for p in people.values()
            ),
            key=lambda p: -p["hours"],
        ),
    }


def annual(
    snapshot: dict[str, Any],
    rates: list[dict[str, Any]],
    costs: list[dict[str, Any]],
    master: dict[str, dict[str, Any]],
    through: str | None = None,
) -> dict[str, Any]:
    """Twelve months (or as many as the summary holds) ending at ``through``: each client's revenue and net income, ranked by net income, with the size tier (Top 20 ... Top 120) and whether it reaches its target net margin (20% unless the client master sets one)."""
    months = sorted({str(m) for m in snapshot.get("months") or []})
    if through and through in months:
        months = [m for m in months if m <= through]
    months = months[-12:]
    acc: dict[str, dict[str, Any]] = {}
    for m in months:
        for r in full_month(snapshot, rates, m, costs, master)["rows"]:
            a = acc.setdefault(
                r["client_key"],
                {
                    "client_key": r["client_key"],
                    "client_name": r["client_name"],
                    "revenue": ZERO,
                    "net_income": ZERO,
                    "industry": r["industry"],
                },
            )
            a["revenue"] += r["revenue"]
            a["net_income"] += r["net_income"]
    ranked = sorted(acc.values(), key=lambda a: (-a["net_income"], a["client_name"].lower()))
    n = len(ranked)
    for i, a in enumerate(ranked, 1):
        a["rank"] = i
        a["net_margin"] = _pct(a["net_income"], a["revenue"])
        a["tier"] = next((f"Top {t}" for t in TIERS if i <= t), "Below Top 120")
        a["bottom_20"] = n > 20 and i > n - 20
        target = (master.get(a["client_key"]) or {}).get("target_margin")
        a["target_margin"] = float(target) if target is not None else float(DEFAULT_TARGET)
        a["meets_target"] = a["net_margin"] is not None and a["net_margin"] >= a["target_margin"]
    return {"months": months, "rows": ranked}

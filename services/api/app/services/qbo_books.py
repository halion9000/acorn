"""QuickBooks' sales by customer, grouped into clients, and the profitability built on it (pure).

Net income's main table starts from what HaloPSA invoiced. The QBO Profitability table starts from what QuickBooks booked per customer (finance's workbook tab "QBO Profitability"): the same costs and the same
allocations, with the revenue taken from the books. A QuickBooks customer belongs to the client its name is filed under in the client groups (``finance_client_groups``), else it is its own client. Customers grouped under "Commissions" are
income that is not a client's revenue: they show in the history but not in the profitability table.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.profitability import name_key

COMMISSIONS = "Commissions"


def group_name(qbo_name: str, groups: dict[str, str]) -> str:
    """The client a QuickBooks customer is counted under (pure): its typed group, else its own name."""
    return groups.get(name_key(qbo_name)) or " ".join(str(qbo_name).split())


def key_groups(typed: dict[str, str]) -> dict[str, str]:
    """The typed groups (customer name to client name) keyed the way names are matched (pure)."""
    return {name_key(k): v for k, v in typed.items() if k and v}


def history_rows(by_month: dict[str, list[dict[str, Any]]], typed: dict[str, str]) -> list[dict[str, Any]]:
    """Every month, customer and amount with the client it is counted under, oldest month first (pure): the history table."""
    groups = key_groups(typed)
    out = []
    for month in sorted(by_month):
        for c in by_month[month]:
            amount = Decimal(str(c.get("amount") or 0))
            if amount == 0:
                continue
            name = " ".join(str(c.get("name") or "").split())
            out.append({"month": month, "qbo_name": name, "group": group_name(name, groups), "total": amount})
    return out


def pivot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The history by client and month (pure): ``months``, and for each client its amount in each month, its total and the customers behind it."""
    months = sorted({r["month"] for r in rows})
    clients: dict[str, dict[str, Any]] = {}
    for r in rows:
        c = clients.setdefault(r["group"], {"client": r["group"], "by_month": {}, "total": Decimal(0), "qbo_names": set()})
        c["by_month"][r["month"]] = c["by_month"].get(r["month"], Decimal(0)) + r["total"]
        c["total"] += r["total"]
        c["qbo_names"].add(r["qbo_name"])
    out = [{**c, "qbo_names": sorted(c["qbo_names"])} for c in clients.values()]
    out.sort(key=lambda c: (-c["total"], c["client"].lower()))
    return {"months": months, "clients": out}


def profit_snapshot(snapshot: dict[str, Any], by_month: dict[str, list[dict[str, Any]]], typed: dict[str, str]) -> dict[str, Any]:
    """The HaloPSA snapshot with its invoices replaced by what QuickBooks booked per client (pure): hours, agents and everything else stay, so the same costs and allocations apply."""
    groups = key_groups(typed)
    revenue: dict[tuple[str, str], Decimal] = {}
    for month, customers in by_month.items():
        for c in customers:
            name = group_name(str(c.get("name") or ""), groups)
            if name == COMMISSIONS:
                continue
            revenue[(month, name)] = revenue.get((month, name), Decimal(0)) + Decimal(str(c.get("amount") or 0))
    invoices = [
        {"month": month, "client_id": f"qbo:{name_key(name)}", "client_name": name, "revenue": float(amount), "invoices": 0}
        for (month, name), amount in sorted(revenue.items())
        if amount != 0
    ]
    return {**snapshot, "invoices": invoices, "months": sorted({m for m, _ in revenue})}


def months_active(by_month: dict[str, list[dict[str, Any]]], typed: dict[str, str], through: str) -> dict[str, int]:
    """For each client (by name key), the number of months up to ``through`` in which QuickBooks booked revenue for it (pure)."""
    groups = key_groups(typed)
    seen: dict[str, set[str]] = {}
    for month, customers in by_month.items():
        if month > through:
            continue
        for c in customers:
            if Decimal(str(c.get("amount") or 0)) > 0:
                seen.setdefault(name_key(group_name(str(c.get("name") or ""), groups)), set()).add(month)
    return {k: len(v) for k, v in seen.items()}

"""Estimated revenue, cost and margin per client from what each client is billed for and what each invoice line sells and costs per unit.

Money is handled in whole cents (``Decimal``), never floats. An estimate says what it is built from: only invoice lines that have a price AND a cost are counted, and the lines billed but not priced are listed
per client so a gap is never hidden as "no cost". Nothing here reads a tool's own price list: the prices are the ones the owner typed in.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")


def money(v: Any) -> Decimal:
    return Decimal(str(v)).quantize(CENT, rounding=ROUND_HALF_UP)


def margin_rows(billed: dict[str, list[dict[str, Any]]], prices: dict[str, tuple[Decimal, Decimal]], names: dict[str, str]) -> dict[str, Any]:
    """``billed``: client id -> [{item, count}] (the invoice lines each client is billed for and how many units). ``prices``: invoice item -> (unit price, unit cost). Returns per-client rows and totals (pure).

    margin_percent is margin / revenue, or None when nothing priced was billed.
    """
    clients: list[dict[str, Any]] = []
    total_rev = total_cost = Decimal("0.00")
    for cid, lines in billed.items():
        rev = cost = Decimal("0.00")
        unpriced: list[str] = []
        for line in lines:
            item, count = str(line.get("item", "")), line.get("count")
            if not item or not isinstance(count, (int, float)) or count <= 0:
                continue
            p = prices.get(item)
            if p is None:
                unpriced.append(item)
                continue
            rev += money(p[0] * Decimal(str(count)))
            cost += money(p[1] * Decimal(str(count)))
        margin = rev - cost
        clients.append(
            {
                "client_id": cid,
                "client_name": names.get(cid, ""),
                "revenue": str(rev),
                "cost": str(cost),
                "margin": str(margin),
                "margin_percent": round(float(margin / rev) * 100, 1) if rev > 0 else None,
                "unpriced_items": sorted(set(unpriced)),
            }
        )
        total_rev += rev
        total_cost += cost
    clients.sort(key=lambda c: (Decimal(c["margin"]), c["client_name"].lower()))
    total_margin = total_rev - total_cost
    return {
        "clients": clients,
        "totals": {"revenue": str(total_rev), "cost": str(total_cost), "margin": str(total_margin), "margin_percent": round(float(total_margin / total_rev) * 100, 1) if total_rev > 0 else None},
    }

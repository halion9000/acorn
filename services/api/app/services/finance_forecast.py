"""A forward-looking margin per client from what HaloPSA bills and what the tools count (roadmap r7-af-38, Hal 2026-11-18: "do what you recommend").

For each client with recurring invoices: revenue and cost as the invoices stand today (quantity x unit price, quantity x unit cost, from the daily HaloPSA snapshot), and the same with every invoice line that a tool
counts set to the COUNTED quantity (what the invoice would say once the Billing sync differences are applied). The change and the lines that differ are shown, so a margin that is about to move is seen before it does.
Lines with no unit cost in HaloPSA add revenue but no cost, as in the margin view, and are named. Pure: the snapshot and the counted quantities go in, rows come out.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.finance import money


def _d(v: Any) -> Decimal:
    try:
        return Decimal(str(v if v not in (None, "") else 0))
    except Exception:  # noqa: BLE001 - a malformed number is read as zero
        return Decimal(0)


def forecast(snapshot: dict[str, Any], counted: dict[tuple[str, str], int]) -> dict[str, Any]:
    """Rows per client (lowest forecast margin first) and totals. ``counted`` is {(HaloPSA client id, invoice item): counted quantity} for the lines whose count differs from what is billed."""
    clients: dict[str, dict[str, Any]] = {}
    for rec in snapshot.get("recurring") or []:
        cid = str(rec.get("client_id") or "")
        if not cid:
            continue
        c = clients.setdefault(
            cid,
            {"client_id": cid, "client_name": str(rec.get("client_name") or ""), "rev": Decimal(0), "cost": Decimal(0), "costed_rev": Decimal(0), "rev2": Decimal(0), "cost2": Decimal(0), "costed_rev2": Decimal(0), "changes": [], "no_cost": set()},
        )
        for line in rec.get("lines") or []:
            item = str(line.get("item") or "")
            qty, price, unit_cost = _d(line.get("qty")), _d(line.get("unit_price")), _d(line.get("unit_cost"))
            qty2 = Decimal(counted[(cid, item)]) if (cid, item) in counted else qty
            c["rev"] += qty * price
            c["rev2"] += qty2 * price
            if unit_cost > 0:
                c["costed_rev"] += qty * price
                c["cost"] += qty * unit_cost
                c["costed_rev2"] += qty2 * price
                c["cost2"] += qty2 * unit_cost
            elif item:
                c["no_cost"].add(item)
            if qty2 != qty:
                c["changes"].append({"item": item, "billed": int(qty), "counted": int(qty2), "revenue_change": str(money((qty2 - qty) * price))})

    def pct(margin: Decimal, base: Decimal) -> float | None:
        return round(float(margin / base) * 100, 1) if base > 0 else None

    rows = []
    for c in clients.values():
        m1, m2 = c["costed_rev"] - c["cost"], c["costed_rev2"] - c["cost2"]
        rows.append(
            {
                "client_id": c["client_id"],
                "client_name": c["client_name"],
                "revenue_now": str(money(c["rev"])),
                "revenue_forecast": str(money(c["rev2"])),
                "revenue_change": str(money(c["rev2"] - c["rev"])),
                "cost_now": str(money(c["cost"])),
                "cost_forecast": str(money(c["cost2"])),
                "margin_percent_now": pct(m1, c["costed_rev"]),
                "margin_percent_forecast": pct(m2, c["costed_rev2"]),
                "changed_lines": sorted(c["changes"], key=lambda x: x["item"].lower()),
                "lines_without_cost": sorted(c["no_cost"]),
            }
        )
    rows.sort(key=lambda r: (r["margin_percent_forecast"] is None, r["margin_percent_forecast"] if r["margin_percent_forecast"] is not None else 0.0, r["client_name"].lower()))
    rev1 = sum((_d(r["revenue_now"]) for r in rows), Decimal(0))
    rev2 = sum((_d(r["revenue_forecast"]) for r in rows), Decimal(0))
    return {"clients": rows, "totals": {"revenue_now": str(money(rev1)), "revenue_forecast": str(money(rev2)), "revenue_change": str(money(rev2 - rev1)), "clients_with_changes": sum(1 for r in rows if r["changed_lines"])}}

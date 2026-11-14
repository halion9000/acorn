"""Margin and ageing worked out from the HaloPSA money snapshot CORE sends (``finance_halo_snapshots``, migration 178). Pure functions over the snapshot; money in whole cents (``Decimal``).

Margin: per client, what its recurring invoices bill per invoice run (quantity x unit price) against what that costs (quantity x unit cost). Only lines that have a cost in HaloPSA are counted for
margin; a line billed with no cost is listed by name, never treated as free. It is per invoice run: HaloPSA's own period code is passed on and not turned into months, because the code is not
documented here and a guess would put the wrong number on a page about money.

Ageing: the invoices still owed, grouped by how long past their due date they are.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.services.finance import money

BUCKETS = ("not_due", "1_30", "31_60", "61_90", "over_90")
BUCKET_LABELS = {
    "not_due": "Not yet due",
    "1_30": "1-30 days late",
    "31_60": "31-60 days late",
    "61_90": "61-90 days late",
    "over_90": "Over 90 days late",
}


def _dec(v: Any) -> Decimal:
    try:
        return money(v)
    except Exception:
        return Decimal("0.00")


def margin_from_halo(snapshot: dict[str, Any]) -> dict[str, Any]:
    clients: dict[str, dict[str, Any]] = {}
    for rec in snapshot.get("recurring") or []:
        cid = str(rec.get("client_id") or "")
        if not cid:
            continue
        c = clients.setdefault(
            cid,
            {
                "client_id": cid,
                "client_name": str(rec.get("client_name") or ""),
                "revenue": Decimal("0.00"),
                "costed_revenue": Decimal("0.00"),
                "cost": Decimal("0.00"),
                "no_cost": set(),
                "recurring_invoices": 0,
            },
        )
        c["recurring_invoices"] += 1
        for line in rec.get("lines") or []:
            qty, price, cost = (
                Decimal(str(line.get("qty") or 0)),
                Decimal(str(line.get("unit_price") or 0)),
                Decimal(str(line.get("unit_cost") or 0)),
            )
            c["revenue"] += money(qty * price)
            if cost > 0:
                c["costed_revenue"] += money(qty * price)
                c["cost"] += money(qty * cost)
            else:
                c["no_cost"].add(str(line.get("item") or ""))
    rows: list[dict[str, Any]] = []
    total_costed = total_cost = total_rev = Decimal("0.00")
    for c in clients.values():
        margin = c["costed_revenue"] - c["cost"]
        rows.append(
            {
                "client_id": c["client_id"],
                "client_name": c["client_name"],
                "recurring_invoices": c["recurring_invoices"],
                "revenue": str(c["revenue"]),
                "costed_revenue": str(c["costed_revenue"]),
                "cost": str(c["cost"]),
                "margin": str(margin),
                "margin_percent": round(float(margin / c["costed_revenue"]) * 100, 1) if c["costed_revenue"] > 0 else None,
                "lines_without_cost": sorted(n for n in c["no_cost"] if n),
            }
        )
        total_rev += c["revenue"]
        total_costed += c["costed_revenue"]
        total_cost += c["cost"]
    # Lowest margin first; a client with nothing costed has no percentage and goes last.
    rows.sort(
        key=lambda r: (
            r["margin_percent"] is None,
            r["margin_percent"] if r["margin_percent"] is not None else 0.0,
            r["client_name"].lower(),
        )
    )
    total_margin = total_costed - total_cost
    return {
        "clients": rows,
        "totals": {
            "revenue": str(total_rev),
            "costed_revenue": str(total_costed),
            "cost": str(total_cost),
            "margin": str(total_margin),
            "margin_percent": round(float(total_margin / total_costed) * 100, 1) if total_costed > 0 else None,
        },
    }


def _day(v: Any) -> date | None:
    if not isinstance(v, str) or len(v) < 10:
        return None
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        return None


def bucket_of(due: date | None, today: date) -> str:
    """How late an invoice is. One with no due date is treated as not yet due (nothing says it is late)."""
    if due is None:
        return "not_due"
    late = (today - due).days
    if late <= 0:
        return "not_due"
    return "1_30" if late <= 30 else "31_60" if late <= 60 else "61_90" if late <= 90 else "over_90"


def aging_from_halo(snapshot: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    today = today or datetime.now(UTC).date()
    totals = {b: Decimal("0.00") for b in BUCKETS}
    per_client: dict[str, dict[str, Any]] = {}
    for inv in snapshot.get("invoices") or []:
        amount = _dec(inv.get("amount_due"))
        cid = str(inv.get("client_id") or "")
        if amount <= 0 or not cid:
            continue
        due = _day(inv.get("due"))
        bucket = bucket_of(due, today)
        c = per_client.setdefault(
            cid,
            {
                "client_id": cid,
                "client_name": str(inv.get("client_name") or ""),
                "owed": Decimal("0.00"),
                "buckets": {b: Decimal("0.00") for b in BUCKETS},
                "invoices": [],
            },
        )
        c["owed"] += amount
        c["buckets"][bucket] += amount
        totals[bucket] += amount
        c["invoices"].append(
            {
                "number": str(inv.get("number") or ""),
                "due": due.isoformat() if due else None,
                "days_late": max((today - due).days, 0) if due else 0,
                "amount_due": str(amount),
                "bucket": bucket,
            }
        )
    clients: list[dict[str, Any]] = []
    for c in per_client.values():
        c["invoices"].sort(key=lambda i: (-i["days_late"], i["number"]))
        clients.append({**c, "owed": str(c["owed"]), "buckets": {b: str(v) for b, v in c["buckets"].items()}})

    # The client with the most money more than 30 days late first.
    def late_money(c: dict[str, Any]) -> Decimal:
        return sum((Decimal(c["buckets"][b]) for b in ("1_30", "31_60", "61_90", "over_90")), Decimal("0.00"))

    clients.sort(key=lambda c: (-late_money(c), -Decimal(c["owed"]), c["client_name"].lower()))
    owed = sum(totals.values(), Decimal("0.00"))
    return {"clients": clients, "totals": {**{b: str(v) for b, v in totals.items()}, "owed": str(owed)}, "labels": BUCKET_LABELS}

"""Add-on software cost per client, from what each vendor billed and how many licenses each client has (pure).

The method is finance's License Database: a vendor's bill for the month (QuickBooks, the Ad-On Software COGS account) divided by all the licenses of that vendor across clients is the cost of one license; a client carries
its own licenses times that. Done exactly, to the cent: a vendor's bill is split in proportion to the clients' counts with the leftover cents going to the largest remainders, so a vendor's parts add up to its bill.

A vendor with no count behind it (nothing is mapped to it, or every mapped count is zero) is not guessed at: its bill is returned as ``unallocated`` and the Net income page spreads it by revenue like any company-wide cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.services.profitability_full import spread

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class CountRow:
    client_key: str
    source: str
    item: str
    count: int


def allocate(
    vendor_costs: dict[str, Decimal],
    vendor_map: dict[str, list[tuple[str, str]]],
    counts: list[CountRow],
) -> dict[str, Any]:
    """Split each vendor's bill across the clients by the counts of the (source, item) pairs mapped to that vendor.

    Returns ``per_client`` (client key to amount), ``per_vendor`` (for each vendor: its bill, how much went to clients, the licenses counted, the cost of one license) and ``unallocated`` (the bills no count stands behind).
    """
    per_client: dict[str, Decimal] = {}
    per_vendor: dict[str, dict[str, Any]] = {}
    unallocated = ZERO
    by_pair: dict[tuple[str, str], dict[str, int]] = {}
    for c in counts:
        if c.count > 0 and c.client_key:
            slot = by_pair.setdefault((c.source, c.item), {})
            slot[c.client_key] = slot.get(c.client_key, 0) + c.count
    for vendor, cost in vendor_costs.items():
        if cost == 0:
            continue
        weights: dict[str, Decimal] = {}
        for pair in vendor_map.get(vendor, []):
            for client, n in by_pair.get(pair, {}).items():
                weights[client] = weights.get(client, Decimal(0)) + n
        licenses = sum(weights.values(), Decimal(0))
        shares = spread(cost, weights)
        given = sum(shares.values(), ZERO)
        for client, share in shares.items():
            per_client[client] = per_client.get(client, ZERO) + share
        unallocated += cost - given
        per_vendor[vendor] = {
            "cost": cost,
            "allocated": given,
            "licenses": int(licenses),
            "per_license": (cost / licenses).quantize(Decimal("0.0001")) if licenses > 0 else None,
        }
    return {"per_client": per_client, "per_vendor": per_vendor, "unallocated": unallocated}


@dataclass(frozen=True)
class Change:
    """One change to a client's count of something (the history the Billing sync keeps)."""

    observed_at: Any  # datetime
    count: int


def count_as_of(history: list[Change], current: int, when: Any) -> int:
    """How many of something a client had at ``when`` (pure): the count after the last change on or before then. Before the first change on record the first count is used (the history only starts when A.C.O.R.N began watching);
    with no history at all, the count it holds now."""
    if not history:
        return current
    ordered = sorted(history, key=lambda c: c.observed_at)
    last = None
    for c in ordered:
        if c.observed_at <= when:
            last = c
        else:
            break
    return (last or ordered[0]).count

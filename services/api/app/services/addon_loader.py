"""Loading what add-on software allocation needs from the database: the vendor bills, the map from a vendor to the counts behind it, and each client's counts as they stood at the end of each month.

Reads the clients' counts across tenants (one read for the counts and one for their history, limited to the counts a vendor is mapped to), so it is cheap enough for a page load.
"""

from __future__ import annotations

import uuid
from calendar import monthrange
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db.rls_scope import cross_tenant_reads
from app.models.client_alias import ClientAlias
from app.models.finance_profit import FinanceVendorCost, FinanceVendorMap
from app.models.signin import ClientLicenseCount, ClientLicenseHistory
from app.models.tenant import Tenant
from app.services.addon_software import Change, CountRow, allocate, count_as_of
from app.services.profitability import name_key

ADDON_ACCOUNT = "5500"


def month_end(month: str) -> datetime:
    y, m = int(month[:4]), int(month[5:7])
    return datetime(y, m, monthrange(y, m)[1], 23, 59, 59, tzinfo=UTC)


async def vendor_map(db: Any, owner: uuid.UUID) -> dict[str, list[tuple[str, str]]]:
    rows = (await db.execute(select(FinanceVendorMap).where(FinanceVendorMap.tenant_id == owner))).scalars().all()
    out: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        out.setdefault(r.vendor, []).append((r.source, r.item))
    return out


async def client_keys(db: Any, owner: uuid.UUID, snapshot: dict[str, Any]) -> dict[uuid.UUID, str]:
    """Each client tenant to the key Net income knows it by (the name key of its HaloPSA client, else of its own name)."""
    halo_name = {str(i.get("client_id")): i.get("client_name") for i in snapshot.get("invoices") or [] if i.get("client_id") and i.get("client_name")}
    tenants = (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == owner))).all()
    aliases = (await db.execute(select(ClientAlias.child_tenant_id, ClientAlias.vendor_client_id).where(ClientAlias.tenant_id == owner, ClientAlias.vendor == "halopsa", ClientAlias.child_tenant_id.is_not(None)))).all()
    by_alias = {tid: halo_name.get(str(cid)) for tid, cid in aliases}
    return {t.id: name_key(by_alias.get(t.id) or t.name) for t in tenants}


async def allocation_by_month(db: Any, owner: uuid.UUID, snapshot: dict[str, Any], months: list[str]) -> dict[str, dict[str, Any]]:
    """For each month with a vendor bill and a map behind it: the allocation (``per_client``, ``per_vendor``, ``unallocated``, see ``allocate``). Months with nothing to go on are left out."""
    costs = (await db.execute(select(FinanceVendorCost).where(FinanceVendorCost.tenant_id == owner, FinanceVendorCost.account == ADDON_ACCOUNT, FinanceVendorCost.month.in_(months)))).scalars().all()
    if not costs:
        return {}
    vmap = await vendor_map(db, owner)
    pairs = {p for ps in vmap.values() for p in ps}
    if not pairs:
        return {}
    keys = await client_keys(db, owner, snapshot)
    if not keys:
        return {}
    ids = list(keys)
    async with cross_tenant_reads(db):
        held = (await db.execute(select(ClientLicenseCount).where(ClientLicenseCount.tenant_id.in_(ids)))).scalars().all()
        hist = (await db.execute(select(ClientLicenseHistory).where(ClientLicenseHistory.tenant_id.in_(ids)))).scalars().all()
    held = [h for h in held if (h.source, h.item) in pairs]
    history: dict[tuple[uuid.UUID, str, str], list[Change]] = {}
    for h in hist:
        if (h.source, h.item) in pairs:
            history.setdefault((h.tenant_id, h.source, h.item), []).append(Change(h.observed_at, h.count))
    current = {(h.tenant_id, h.source, h.item): h.count for h in held}
    # A count that has since been removed has no current row but still counted in the months it was there.
    universe = sorted(set(current) | set(history), key=str)
    out: dict[str, dict[str, Any]] = {}
    for month in sorted({c.month for c in costs}):
        when = month_end(month)
        bills: dict[str, Decimal] = {}
        for c in costs:
            if c.month == month:
                bills[c.vendor] = bills.get(c.vendor, Decimal(0)) + c.amount
        counts = [CountRow(keys[t], src, item, count_as_of(history.get((t, src, item), []), current.get((t, src, item), 0), when)) for (t, src, item) in universe]
        got = allocate(bills, vmap, counts)
        if got["per_client"]:
            out[month] = got
    return out


async def add_on_by_month(db: Any, owner: uuid.UUID, snapshot: dict[str, Any], months: list[str]) -> dict[str, dict[str, Decimal]]:
    """For each month with a vendor bill and a map behind it: the add-on software cost of each client by key. Months with nothing to go on are left out (Net income then spreads the whole add-on cost by revenue)."""
    return {m: a["per_client"] for m, a in (await allocation_by_month(db, owner, snapshot, months)).items()}

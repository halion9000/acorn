"""Estimated margin per client, from what each invoice line sells and costs per unit and what each client is billed for.

Read with ``finance:view``, change prices with ``finance:write``: neither is held by anyone who only holds the licence-count permissions, so the owner decides (through roles) who sees money. The billed
quantities are the HaloPSA counts A.C.O.R.N already holds; the prices and costs are typed in here by a person.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.billing import BILLED_SOURCE, _all_client_counts
from app.models.finance_halo_snapshot import FinanceHaloSnapshot
from app.models.metric_dataset import MetricDataset
from app.models.finance_price import FinanceItemPrice
from app.models.finance_profit import (
    FinanceClientGroup,
    FinanceClientMaster,
    FinanceCostEntry,
    FinanceLaborRate,
    FinancePnlMonth,
    FinanceProfitSnapshot,
    FinanceProfitTickets,
    FinanceQboSales,
    FinanceSettings,
    FinanceVendorCost,
    FinanceVendorMap,
)
from app.services import csv_export
from app.services import finance as fin
from app.services import finance_halo as fh
from app.services import profitability as profit
from app.services import profitability_full as pf
from app.services import qbo_books as qb
from app.services.audit import emit_audit

router = APIRouter(prefix="/finance", tags=["finance"])


class PriceIn(BaseModel):
    invoice_item: str = Field(min_length=1, max_length=120)
    unit_price: Decimal = Field(ge=0, le=1_000_000, max_digits=12, decimal_places=2)
    unit_cost: Decimal = Field(ge=0, le=1_000_000, max_digits=12, decimal_places=2)


class PriceOut(BaseModel):
    invoice_item: str
    unit_price: str
    unit_cost: str
    updated_at: datetime


class PricesOut(BaseModel):
    prices: list[PriceOut]
    # The invoice lines some client is billed for, so a price can be set for each (priced or not).
    billed_items: list[str]


def _out(r: FinanceItemPrice) -> PriceOut:
    return PriceOut(
        invoice_item=r.invoice_item, unit_price=str(fin.money(r.unit_price)), unit_cost=str(fin.money(r.unit_cost)), updated_at=r.updated_at
    )


async def _billed(db: Any, owner: uuid.UUID) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    per_client, names = await _all_client_counts(db, owner)
    billed = {
        str(cid): [{"item": r["item"], "count": r["count"]} for r in rows if r["source"] == BILLED_SOURCE and r.get("unit") != "ticket"]
        for cid, rows in per_client.items()
    }
    return billed, {str(k): v for k, v in names.items()}


@router.get("/prices", response_model=PricesOut, dependencies=[Depends(require_permission("finance:view"))])
async def list_prices(user: AuthUser, db: DBSession) -> PricesOut:
    rows = (
        (
            await db.execute(
                select(FinanceItemPrice).where(FinanceItemPrice.tenant_id == user.tenant_id).order_by(FinanceItemPrice.invoice_item)
            )
        )
        .scalars()
        .all()
    )
    billed, _ = await _billed(db, user.tenant_id)
    items = sorted({line["item"] for lines in billed.values() for line in lines})
    return PricesOut(prices=[_out(r) for r in rows], billed_items=items)


@router.put("/prices", response_model=PriceOut)
async def save_price(
    body: PriceIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("finance:write"))], db: DBSession
) -> PriceOut:
    item = " ".join(body.invoice_item.split())
    if not item:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name the invoice line")
    row = (
        await db.execute(
            select(FinanceItemPrice).where(FinanceItemPrice.tenant_id == user.tenant_id, FinanceItemPrice.invoice_item == item)
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None:
        row = FinanceItemPrice(
            tenant_id=user.tenant_id,
            invoice_item=item,
            unit_price=body.unit_price,
            unit_cost=body.unit_cost,
            updated_by=user.user_id,
            updated_at=now,
        )
        db.add(row)
    else:
        row.unit_price, row.unit_cost, row.updated_by, row.updated_at = body.unit_price, body.unit_cost, user.user_id, now
    await db.flush()
    # The audit entry names the line and who changed it, not the amounts (money stays out of the log).
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="finance_price:saved",
        resource="finance_item_price",
        resource_id=str(row.id),
        changes={"invoice_item": item},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.delete("/prices", status_code=status.HTTP_204_NO_CONTENT)
async def delete_price(
    invoice_item: str, request: Request, user: Annotated[AuthUser, Depends(require_permission("finance:write"))], db: DBSession
) -> None:
    item = " ".join(invoice_item.split())
    await db.execute(delete(FinanceItemPrice).where(FinanceItemPrice.tenant_id == user.tenant_id, FinanceItemPrice.invoice_item == item))
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="finance_price:deleted",
        resource="finance_item_price",
        resource_id=item,
        changes={"invoice_item": item},
        request=request,
    )
    await db.commit()


@router.get("/halo", dependencies=[Depends(require_permission("finance:view"))])
async def halo_finance(user: AuthUser, db: DBSession) -> dict[str, Any]:
    """Margin per client from HaloPSA's recurring invoices, and the invoices still owed grouped by how late they are: all from the snapshot CORE sends about once a day. ``received_at`` is None until the first one arrives."""
    row = (await db.execute(select(FinanceHaloSnapshot).where(FinanceHaloSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    if row is None:
        return {"received_at": None, "margin": None, "aging": None}
    return {"received_at": row.received_at, "margin": fh.margin_from_halo(row.payload), "aging": fh.aging_from_halo(row.payload)}


@router.get("/margin", dependencies=[Depends(require_permission("finance:view"))])
async def margin(user: AuthUser, db: DBSession) -> dict[str, Any]:
    """Estimated revenue, cost and margin per client, lowest margin first, and what each estimate is missing (invoice lines billed but not priced)."""
    rows = (await db.execute(select(FinanceItemPrice).where(FinanceItemPrice.tenant_id == user.tenant_id))).scalars().all()
    prices = {r.invoice_item: (Decimal(r.unit_price), Decimal(r.unit_cost)) for r in rows}
    billed, names = await _billed(db, user.tenant_id)
    out = fin.margin_rows(billed, prices, names)
    out["priced_items"] = len(prices)
    out["note"] = (
        "An estimate: only invoice lines with both a price and a cost are counted, using the quantities each client is billed for. Lines billed but not priced are listed per client."
    )
    return out


# ---- Profitability --------------------------------------------------------------------------------------------------------------------------------------


class RateIn(BaseModel):
    scope: str = Field(pattern="^(agent|team|default)$")
    key: str = Field(default="", max_length=120)
    hourly_rate: Decimal = Field(ge=0, le=10000, max_digits=10, decimal_places=2)


async def _rates(db: DBSession, tenant: Any) -> list[dict[str, Any]]:
    rows = (await db.execute(select(FinanceLaborRate).where(FinanceLaborRate.tenant_id == tenant))).scalars().all()
    return [{"scope": r.scope, "key": r.key, "hourly_rate": r.hourly_rate} for r in rows]


@router.get("/profitability", dependencies=[Depends(require_permission("finance:view"))])
async def profitability(user: AuthUser, db: DBSession, month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$")) -> dict[str, Any]:
    """Revenue, hours, labor cost and what is left after labor per client for one month, from the summary CORE sends about once a day. ``received_at`` is None until the first one arrives."""
    row = (await db.execute(select(FinanceProfitSnapshot).where(FinanceProfitSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    if row is None:
        return {"received_at": None, "months": [], "report": None, "rates": await _rates(db, user.tenant_id)}
    months = profit.available_months(row.payload)
    chosen = month if month in months else (months[-2] if len(months) > 1 else (months[-1] if months else None))
    halo = (await db.execute(select(FinanceHaloSnapshot).where(FinanceHaloSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    rates = await _rates(db, user.tenant_id)
    report = (
        profit.profit_for_month(row.payload, rates, chosen, profit.software_per_run(halo.payload if halo else None)) if chosen else None
    )
    return {
        "received_at": row.received_at,
        "months": months,
        "report": report,
        "rates": rates,
        "agents": row.payload.get("agents") or [],
        "note": (
            "Revenue is what HaloPSA invoiced in the month, before tax. Labor is the hours worked on tickets times each agent's hourly cost (set below; 65.00 until you set one). Software, hardware, travel, "
            "equipment, sales and marketing and overhead are not in this number. Software per invoice run comes from the recurring invoices and is shown for information only."
        ),
    }


@router.get("/profitability/client", dependencies=[Depends(require_permission("finance:view"))])
async def profitability_client(
    user: AuthUser,
    db: DBSession,
    client_id: str = Query(max_length=40),
    month: str = Query(pattern=r"^\d{4}-\d{2}$"),
) -> dict[str, Any]:
    """What one client's row on the Profitability page is made of for a month: the invoice lines (billed and free), the recurring invoice lines, and the hours by agent with the rate used. Nothing new is worked out; each part adds up to a figure on the row."""
    snap = (await db.execute(select(FinanceProfitSnapshot).where(FinanceProfitSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    if snap is None:
        raise HTTPException(status_code=404, detail="No profitability data has arrived yet")
    lines = (
        await db.execute(select(MetricDataset).where(MetricDataset.tenant_id == user.tenant_id, MetricDataset.key == "invoice-lines"))
    ).scalar_one_or_none()
    halo = (await db.execute(select(FinanceHaloSnapshot).where(FinanceHaloSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    tickets = (await db.execute(select(FinanceProfitTickets).where(FinanceProfitTickets.tenant_id == user.tenant_id, FinanceProfitTickets.month == month))).scalar_one_or_none()
    out = profit.client_breakdown(
        snap.payload,
        lines.payload if lines else None,
        halo.payload if halo else None,
        await _rates(db, user.tenant_id),
        client_id,
        month,
        tickets.payload if tickets else None,
    )
    if out is None:
        raise HTTPException(status_code=404, detail="That client was not invoiced in that month")
    return {**out, "invoice_lines_received_at": lines.received_at if lines else None, "received_at": snap.received_at}


@router.get("/profitability/export.csv", dependencies=[Depends(require_permission("finance:view"))])
async def profitability_csv(user: AuthUser, db: DBSession, month: str = Query(pattern=r"^\d{4}-\d{2}$")) -> Response:
    row = (await db.execute(select(FinanceProfitSnapshot).where(FinanceProfitSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    if row is None or month not in profit.available_months(row.payload):
        raise HTTPException(status_code=404, detail="No profitability data for that month yet")
    report = profit.profit_for_month(row.payload, await _rates(db, user.tenant_id), month)
    body = csv_export.to_csv(
        ["Client", "Revenue", "Invoices", "Hours", "Labor cost", "After labor", "Margin after labor %"],
        [
            [r["client_name"], r["revenue"], r["invoices"], r["hours"], r["labor"], r["after_labor"], r["margin_percent"]]
            for r in report["rows"]
        ],
    )
    return Response(
        content=body, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="profitability-{month}.csv"'}
    )


@router.put("/labor-rates", status_code=status.HTTP_204_NO_CONTENT)
async def save_labor_rate(
    body: RateIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("finance:write"))], db: DBSession
) -> None:
    key = " ".join(body.key.split())
    if body.scope != "default" and not key:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name the agent or team")
    if body.scope == "default":
        key = ""
    row = (
        await db.execute(
            select(FinanceLaborRate).where(
                FinanceLaborRate.tenant_id == user.tenant_id, FinanceLaborRate.scope == body.scope, FinanceLaborRate.key == key
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None:
        db.add(
            FinanceLaborRate(
                tenant_id=user.tenant_id,
                scope=body.scope,
                key=key,
                hourly_rate=body.hourly_rate,
                updated_by=str(user.user_id) if user.user_id else None,
                updated_at=now,
            )
        )
    else:
        row.hourly_rate, row.updated_by, row.updated_at = body.hourly_rate, (str(user.user_id) if user.user_id else None), now
    await db.flush()
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="finance_labor_rate:saved",
        resource="finance_labor_rate",
        resource_id=f"{body.scope}:{key}",
        changes={"scope": body.scope, "key": key},
        request=request,
    )
    await db.commit()


@router.delete("/labor-rates", status_code=status.HTTP_204_NO_CONTENT)
async def delete_labor_rate(
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("finance:write"))],
    db: DBSession,
    scope: str = Query(pattern="^(agent|team|default)$"),
    key: str = Query(default="", max_length=120),
) -> None:
    key = "" if scope == "default" else " ".join(key.split())
    result = await db.execute(
        delete(FinanceLaborRate).where(
            FinanceLaborRate.tenant_id == user.tenant_id, FinanceLaborRate.scope == scope, FinanceLaborRate.key == key
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="No such rate")
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="finance_labor_rate:deleted",
        resource="finance_labor_rate",
        resource_id=f"{scope}:{key}",
        changes={"scope": scope, "key": key},
        request=request,
    )
    await db.commit()


class RateRowIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    hourly_rate: str | float | int = Field(description="The hourly cost: a number or text such as 72.24 or $72.24.")


class RatesImportIn(BaseModel):
    rows: list[RateRowIn] = Field(min_length=1, max_length=500)


async def _snapshot_agents(db: DBSession, tenant: Any) -> list[dict[str, Any]]:
    row = (await db.execute(select(FinanceProfitSnapshot).where(FinanceProfitSnapshot.tenant_id == tenant))).scalar_one_or_none()
    return [a for a in ((row.payload or {}).get("agents") or []) if isinstance(a, dict)] if row else []


@router.get("/labor-rates/overview", dependencies=[Depends(require_permission("finance:view"))])
async def labor_rates_overview(user: AuthUser, db: DBSession) -> dict[str, Any]:
    """The hourly cost A.C.O.R.N prices time with: the default, each team's, and every HaloPSA agent with the rate that applies to them and where it comes from (their own, their team's, the default)."""
    rates = await _rates(db, user.tenant_id)
    table = profit.resolve_rates(rates)
    agents = await _snapshot_agents(db, user.tenant_id)
    by_id = {str(a.get("id")): a for a in agents}
    out = []
    for a in agents:
        aid = str(a.get("id") or "")
        rate, source = profit.rate_for(aid, by_id, table)
        out.append(
            {
                "agent_id": aid,
                "name": str(a.get("name") or ""),
                "team": str(a.get("team") or ""),
                "active": bool(a.get("active", True)),
                "rate": rate,
                "source": source,
                "own_rate": table["agent"].get(aid),
            }
        )
    out.sort(key=lambda r: (not r["active"], r["name"].lower()))
    return {
        "default_rate": table["default"],
        "teams": [{"team": k, "rate": v} for k, v in sorted(table["team"].items())],
        "agents": out,
        "have_agents": bool(agents),
    }


@router.put("/labor-rates/import")
async def import_labor_rates(
    body: RatesImportIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("finance:write"))], db: DBSession
) -> dict[str, Any]:
    """Set agents' own hourly rates from a list of names and rates (a pasted sheet). Names are matched to HaloPSA agents; one that fits none or several is returned in ``unmatched`` and nothing is guessed."""
    agents = await _snapshot_agents(db, user.tenant_id)
    if not agents:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="CORE has not sent the HaloPSA agents yet, so names cannot be matched. Try again after its next daily read.")
    from app.services.labor_rate_import import match_rates

    matched, unmatched = match_rates(agents, [(r.name, r.hourly_rate) for r in body.rows])
    count = await save_agent_rates(db, user.tenant_id, [(m.agent_id, m.rate) for m in matched], str(user.user_id) if user.user_id else None)
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="finance_labor_rate:imported",
        resource="finance_labor_rate",
        resource_id="agent",
        changes={"saved": count, "unmatched": len(unmatched)},
        request=request,
    )
    await db.commit()
    return {"saved": count, "unmatched": unmatched}


async def save_agent_rates(db: DBSession, tenant: Any, rates: list[tuple[str, Decimal]], by: str | None) -> int:
    """Set each agent's own hourly rate (insert or replace); returns how many. The caller commits."""
    now = datetime.now(UTC)
    saved = 0
    for agent_id, rate in rates:
        row = (
            await db.execute(select(FinanceLaborRate).where(FinanceLaborRate.tenant_id == tenant, FinanceLaborRate.scope == "agent", FinanceLaborRate.key == agent_id))
        ).scalar_one_or_none()
        if row is None:
            db.add(FinanceLaborRate(tenant_id=tenant, scope="agent", key=agent_id, hourly_rate=rate, updated_by=by, updated_at=now))
        else:
            row.hourly_rate, row.updated_by, row.updated_at = rate, by, now
        saved += 1
    await db.flush()
    return saved


async def _groups(db: DBSession, tenant: Any) -> dict[str, str]:
    """Each client name key to the Primary Name it is filed under."""
    rows = (await db.execute(select(FinanceClientGroup).where(FinanceClientGroup.tenant_id == tenant))).scalars().all()
    return {r.member_key: r.primary_name for r in rows}


class GroupRowIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    primary: str = Field(default="", max_length=200)


class GroupsImportIn(BaseModel):
    rows: list[GroupRowIn] = Field(min_length=1, max_length=2000)


@router.get("/client-groups", dependencies=[Depends(require_permission("finance:view"))])
async def client_groups(user: AuthUser, db: DBSession) -> dict[str, Any]:
    """The client names filed under a Primary Name, by group: each group with the names in it (only groups of more than one name, or one whose name differs from its Primary Name, are listed)."""
    rows = (await db.execute(select(FinanceClientGroup).where(FinanceClientGroup.tenant_id == user.tenant_id))).scalars().all()
    by: dict[str, list[str]] = {}
    for r in rows:
        by.setdefault(r.primary_name, []).append(r.member_name)
    return {"groups": [{"primary": p, "members": sorted(m, key=str.lower)} for p, m in sorted(by.items(), key=lambda kv: kv[0].lower())]}


@router.put("/client-groups/import")
async def import_client_groups(
    body: GroupsImportIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("finance:write"))], db: DBSession
) -> dict[str, int]:
    """File client names under Primary Names (a pasted sheet of name and Primary Name). A name with no Primary Name, or the same as its own, is taken out of any group. The last row for a name wins."""
    existing = {r.member_key: r for r in (await db.execute(select(FinanceClientGroup).where(FinanceClientGroup.tenant_id == user.tenant_id))).scalars().all()}
    wanted: dict[str, GroupRowIn] = {}
    skipped = 0
    for row in body.rows:
        key = profit.name_key(row.name)
        if not key:
            skipped += 1
            continue
        wanted[key] = row
    saved = removed = 0
    now = datetime.now(UTC)
    for key, row in wanted.items():
        name, primary = " ".join(row.name.split()), " ".join(row.primary.split())
        found = existing.get(key)
        if not primary or profit.name_key(primary) == key:
            if found is not None:
                await db.delete(found)
                removed += 1
            continue
        if found is None:
            db.add(FinanceClientGroup(tenant_id=user.tenant_id, member_key=key, member_name=name, primary_name=primary, updated_at=now))
        else:
            found.member_name, found.primary_name, found.updated_at = name, primary, now
        saved += 1
    await db.flush()
    await emit_audit(db=db, tenant_id=user.tenant_id, actor_id=user.user_id, action="finance_client_groups:imported", resource="finance_client_group", resource_id="import", changes={"saved": saved, "removed": removed, "skipped": skipped}, request=request)
    await db.commit()
    return {"saved": saved, "removed": removed, "skipped": skipped}


class CountedRefIn(BaseModel):
    source: str = Field(min_length=1, max_length=40)
    item: str = Field(min_length=1, max_length=80)


class VendorMapIn(BaseModel):
    vendor: str = Field(min_length=1, max_length=120)
    counted: list[CountedRefIn] = Field(max_length=30)


@router.get("/software", dependencies=[Depends(require_permission("finance:view"))])
async def software_costs(user: AuthUser, db: DBSession) -> dict[str, Any]:
    """The software vendors QuickBooks booked costs to (add-on and support), what each billed lately, which counts say how many licenses of it each client has, and what one license costs on that basis. ``counted_items`` are the counts that can be chosen."""
    from app.api.v1.endpoints.devices import _scope
    from app.db.rls_scope import cross_tenant_reads
    from app.models.signin import ClientLicenseCount
    from app.services.addon_loader import allocation_by_month, vendor_map

    costs = (await db.execute(select(FinanceVendorCost).where(FinanceVendorCost.tenant_id == user.tenant_id).order_by(FinanceVendorCost.month.desc()))).scalars().all()
    vmap = await vendor_map(db, user.tenant_id)
    snap = (await db.execute(select(FinanceProfitSnapshot).where(FinanceProfitSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    latest: dict[tuple[str, str], FinanceVendorCost] = {}
    for c in costs:
        latest.setdefault((c.account, c.vendor), c)
    newest = max((c.month for c in costs), default=None)
    # Each vendor is shown for the month of ITS latest bill (a vendor not billed in the newest month overall would otherwise show no licenses at all).
    detail: dict[str, Any] = {}
    if snap:
        for account in ("5500", "5100"):
            wanted = sorted({c.month for (a, _v), c in latest.items() if a == account})
            by_month = await allocation_by_month(db, user.tenant_id, snap.payload, wanted, account) if wanted else {}
            for (a, v), c in latest.items():
                if a == account and v in ((by_month.get(c.month) or {}).get("per_vendor") or {}):
                    detail[v] = by_month[c.month]["per_vendor"][v]
    ids, _ = await _scope(db, user.tenant_id, None)
    items: set[tuple[str, str]] = set()
    if ids[1:]:
        async with cross_tenant_reads(db):
            for source, item in (await db.execute(select(ClientLicenseCount.source, ClientLicenseCount.item).where(ClientLicenseCount.tenant_id.in_(ids[1:])).distinct())).all():
                items.add((source, item))
    vendors = [
        {
            "vendor": v,
            "account": a,
            "latest_month": c.month,
            "latest_amount": c.amount,
            "mapped": [{"source": s, "item": i} for s, i in sorted(vmap.get(v, []))],
            "licenses": (detail.get(v) or {}).get("licenses"),
            "per_license": (detail.get(v) or {}).get("per_license"),
        }
        for (a, v), c in sorted(latest.items(), key=lambda kv: (kv[0][0] != "5500", -float(kv[1].amount)))
    ]
    return {
        "have_costs": bool(costs),
        "latest_month": newest,
        "vendors": vendors,
        "counted_items": [{"source": s, "item": i} for s, i in sorted(items)],
    }


@router.put("/software/map", status_code=status.HTTP_204_NO_CONTENT)
async def save_vendor_map(
    body: VendorMapIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("finance:write"))], db: DBSession
) -> None:
    """Say which counts stand behind a vendor (replacing what was there). An empty list takes the vendor out of the allocation: its bill is then spread by revenue."""
    vendor = " ".join(body.vendor.split())
    await db.execute(delete(FinanceVendorMap).where(FinanceVendorMap.tenant_id == user.tenant_id, FinanceVendorMap.vendor == vendor))
    now = datetime.now(UTC)
    for ref in {(c.source, c.item) for c in body.counted}:
        db.add(FinanceVendorMap(tenant_id=user.tenant_id, vendor=vendor, source=ref[0], item=ref[1], updated_by=str(user.user_id) if user.user_id else None, updated_at=now))
    await db.flush()
    await emit_audit(db=db, tenant_id=user.tenant_id, actor_id=user.user_id, action="finance_vendor_map:saved", resource="finance_vendor_map", resource_id=vendor, changes={"counts": len(body.counted)}, request=request)
    await db.commit()


# ---- The full model: cost inputs, client master, analysis ----------------------------------------------------------------------------------------------------


class CostIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    category: str = Field(pattern="^(payroll_cogs|addon_software|support_software|travel|equipment|hardware|sales_marketing|overhead)$")
    client_name: str = Field(default="", max_length=200)
    amount: Decimal = Field(ge=-100_000_000, le=100_000_000, max_digits=14, decimal_places=2)
    note: str = Field(default="", max_length=300)


class ClientMasterIn(BaseModel):
    client_name: str = Field(min_length=1, max_length=200)
    industry: str = Field(default="", max_length=120)
    non_profit: bool = False
    target_margin: Decimal | None = Field(default=None, ge=-100, le=100, max_digits=5, decimal_places=2)


class SettingsIn(BaseModel):
    available_hours_per_month: Decimal = Field(gt=0, le=744, max_digits=6, decimal_places=2)


async def _costs(db: DBSession, tenant: Any) -> list[dict[str, Any]]:
    rows = (await db.execute(select(FinanceCostEntry).where(FinanceCostEntry.tenant_id == tenant))).scalars().all()
    return [
        {
            "month": r.month,
            "category": r.category,
            "client_key": r.client_key,
            "client_name": r.client_name,
            "source": r.source,
            "amount": r.amount,
            "note": r.note,
        }
        for r in sorted(rows, key=lambda r: (r.month, r.category, r.client_key))
    ]


async def _master(db: DBSession, tenant: Any) -> dict[str, dict[str, Any]]:
    rows = (await db.execute(select(FinanceClientMaster).where(FinanceClientMaster.tenant_id == tenant))).scalars().all()
    return {
        r.client_key: {
            "client_key": r.client_key,
            "client_name": r.client_name,
            "industry": r.industry,
            "non_profit": r.non_profit,
            "target_margin": r.target_margin,
        }
        for r in rows
    }


async def _available_hours(db: DBSession, tenant: Any) -> Decimal:
    row = (await db.execute(select(FinanceSettings).where(FinanceSettings.tenant_id == tenant))).scalar_one_or_none()
    return Decimal(row.available_hours_per_month) if row else Decimal("160")


@router.get("/profitability/analysis", dependencies=[Depends(require_permission("finance:view"))])
async def profitability_analysis(
    user: AuthUser, db: DBSession, month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$")
) -> dict[str, Any]:
    """Everything beyond revenue less labor for one month: the full cost-to-net-income table, new clients, the summary by industry, hours by function and utilization, and the twelve-month ranking. Costs that
    have not been entered are zero and named in ``report.missing``. ``received_at`` is None until CORE has sent the first Halo summary."""
    row = (await db.execute(select(FinanceProfitSnapshot).where(FinanceProfitSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    if row is None:
        return {"received_at": None, "months": [], "report": None, "industries": [], "hours": None, "annual": None}
    months = profit.available_months(row.payload)
    chosen = month if month in months else (months[-2] if len(months) > 1 else (months[-1] if months else None))
    if chosen is None:
        return {"received_at": row.received_at, "months": months, "report": None, "industries": [], "hours": None, "annual": None}
    rates, costs, master = await _rates(db, user.tenant_id), await _costs(db, user.tenant_id), await _master(db, user.tenant_id)
    from app.services.addon_loader import add_on_by_month, support_by_month

    annual_months = [m for m in months if m <= chosen][-12:]
    addon_direct_months = await add_on_by_month(db, user.tenant_id, row.payload, annual_months)
    support_direct_months = await support_by_month(db, user.tenant_id, row.payload, annual_months)
    groups = await _groups(db, user.tenant_id)
    report = pf.full_month(row.payload, rates, chosen, costs, master, addon_direct_months.get(chosen), groups, support_direct_months.get(chosen))
    return {
        "received_at": row.received_at,
        "months": months,
        "report": report,
        "industries": pf.by_industry(report),
        "hours": pf.hours_report(row.payload, rates, chosen, await _available_hours(db, user.tenant_id)),
        "annual": pf.annual(row.payload, rates, costs, master, chosen, addon_direct_months, groups, support_direct_months),
        "note": (
            "Costs are shared out to the cent: an entry with a client goes to that client, one without is spread by each client's revenue for the month (the workbook spreads by monthly recurring revenue; the Halo summary "
            "holds invoiced revenue). Sales and marketing is split evenly across clients whose first revenue is this month."
        ),
    }


@router.get("/profitability/pnl", dependencies=[Depends(require_permission("finance:view"))])
async def profit_and_loss(user: AuthUser, db: DBSession, month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$")) -> dict[str, Any]:
    """QuickBooks' profit and loss for a month (the newest complete one unless asked), line by line as QuickBooks shows it. ``months`` lists the months held."""
    rows = (await db.execute(select(FinancePnlMonth).where(FinancePnlMonth.tenant_id == user.tenant_id))).scalars().all()
    held = {r.month: r for r in rows}
    months = sorted(held)
    if not months:
        return {"months": [], "month": None, "lines": [], "received_at": None}
    chosen = month if month in held else (months[-2] if len(months) > 1 else months[-1])
    return {"months": months, "month": chosen, "lines": held[chosen].payload, "received_at": held[chosen].received_at}


async def _qbo_sales(db: DBSession, tenant: Any) -> dict[str, list[dict[str, Any]]]:
    rows = (await db.execute(select(FinanceQboSales).where(FinanceQboSales.tenant_id == tenant))).scalars().all()
    return {r.month: list(r.payload or []) for r in rows}


@router.get("/profitability/qbo-history", dependencies=[Depends(require_permission("finance:view"))])
async def qbo_history(user: AuthUser, db: DBSession) -> dict[str, Any]:
    """What QuickBooks invoiced each client in each month it holds (sales by customer, accrual): every client with its amount per month and total, and the QuickBooks customers behind it."""
    by_month = await _qbo_sales(db, user.tenant_id)
    groups = await _groups(db, user.tenant_id)
    out = qb.pivot(qb.history_rows(by_month, groups))
    return {
        "months": out["months"],
        "clients": [{"client": c["client"], "total": c["total"], "by_month": c["by_month"], "qbo_names": c["qbo_names"]} for c in out["clients"]],
    }


@router.get("/profitability/qbo", dependencies=[Depends(require_permission("finance:view"))])
async def qbo_profitability(
    user: AuthUser, db: DBSession, month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$")
) -> dict[str, Any]:
    """Profit by client for a month with the revenue taken from QuickBooks (sales by customer) instead of HaloPSA's invoices; hours, labor and the cost allocations are the same as on the main table."""
    row = (await db.execute(select(FinanceProfitSnapshot).where(FinanceProfitSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    by_month = await _qbo_sales(db, user.tenant_id)
    months = sorted(by_month)
    if row is None or not months:
        return {"months": months, "report": None, "received_at": row.received_at if row else None}
    chosen = month if month in by_month else (months[-2] if len(months) > 1 else months[-1])
    groups = await _groups(db, user.tenant_id)
    snapshot = qb.profit_snapshot(row.payload, by_month, groups)
    rates, costs, master = await _rates(db, user.tenant_id), await _costs(db, user.tenant_id), await _master(db, user.tenant_id)
    from app.services.addon_loader import add_on_by_month, support_by_month

    addon = await add_on_by_month(db, user.tenant_id, row.payload, [chosen])
    support = await support_by_month(db, user.tenant_id, row.payload, [chosen])
    report = pf.full_month(snapshot, rates, chosen, costs, master, addon.get(chosen), groups, support.get(chosen))
    active = qb.months_active(by_month, groups, chosen)
    for r in report["rows"]:
        r["months_active"] = active.get(profit.name_key(r["client_name"]), 0)
    return {"months": months, "report": report, "received_at": row.received_at}


@router.get("/client-names", dependencies=[Depends(require_permission("finance:view"))])
async def client_names(user: AuthUser, db: DBSession) -> dict[str, Any]:
    """Every client name Net income has seen, from HaloPSA (invoices and hours) and from QuickBooks (sales by customer), each with the Primary Name it is filed under (None when it is on its own): what the client groups are chosen from."""
    row = (await db.execute(select(FinanceProfitSnapshot).where(FinanceProfitSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    groups = await _groups(db, user.tenant_id)
    names: dict[str, str] = {}
    snap = row.payload if row is not None else {}
    for inv in snap.get("invoices") or []:
        if inv.get("client_name"):
            names.setdefault(profit.name_key(inv["client_name"]), " ".join(str(inv["client_name"]).split()))
    for h in snap.get("hours") or []:
        if h.get("client"):
            names.setdefault(profit.name_key(h["client"]), " ".join(str(h["client"]).split()))
    for customers in (await _qbo_sales(db, user.tenant_id)).values():
        for c in customers:
            if c.get("name"):
                names.setdefault(profit.name_key(c["name"]), " ".join(str(c["name"]).split()))
    members = {r.member_key: r.member_name for r in (await db.execute(select(FinanceClientGroup).where(FinanceClientGroup.tenant_id == user.tenant_id))).scalars().all()}
    for k, n in members.items():
        names.setdefault(k, n)
    out = [{"name": n, "group": groups.get(k)} for k, n in names.items() if k]
    out.sort(key=lambda x: x["name"].lower())
    return {"names": out}


@router.get("/profitability/inputs", dependencies=[Depends(require_permission("finance:view"))])
async def profitability_inputs(user: AuthUser, db: DBSession) -> dict[str, Any]:
    """The typed or synced cost entries, the client master and the settings."""
    return {
        "costs": await _costs(db, user.tenant_id),
        "master": sorted((await _master(db, user.tenant_id)).values(), key=lambda m: m["client_name"].lower()),
        "available_hours_per_month": await _available_hours(db, user.tenant_id),
        "categories": list(pf.CATEGORIES),
    }


@router.put("/profitability/costs", status_code=status.HTTP_204_NO_CONTENT)
async def save_cost(
    body: CostIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("finance:write"))], db: DBSession
) -> None:
    name = " ".join(body.client_name.split())
    key = profit.name_key(name)
    if body.category in ("payroll_cogs", "sales_marketing", "overhead"):
        name, key = "", ""
    row = (
        await db.execute(
            select(FinanceCostEntry).where(
                FinanceCostEntry.tenant_id == user.tenant_id,
                FinanceCostEntry.month == body.month,
                FinanceCostEntry.category == body.category,
                FinanceCostEntry.client_key == key,
                FinanceCostEntry.source == "manual",
            )
        )
    ).scalar_one_or_none()
    now, by = datetime.now(UTC), (str(user.user_id) if user.user_id else None)
    if row is None:
        db.add(
            FinanceCostEntry(
                tenant_id=user.tenant_id,
                month=body.month,
                category=body.category,
                client_key=key,
                client_name=name,
                source="manual",
                amount=body.amount,
                note=body.note,
                updated_by=by,
                updated_at=now,
            )
        )
    else:
        row.amount, row.note, row.client_name, row.updated_by, row.updated_at = body.amount, body.note, name, by, now
    await db.flush()
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="finance_cost:saved",
        resource="finance_cost_entry",
        resource_id=f"{body.month}:{body.category}:{key}",
        changes={"month": body.month, "category": body.category, "client_key": key},
        request=request,
    )
    await db.commit()


@router.delete("/profitability/costs", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cost(
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("finance:write"))],
    db: DBSession,
    month: str = Query(pattern=r"^\d{4}-\d{2}$"),
    category: str = Query(max_length=40),
    client_name: str = Query(default="", max_length=200),
) -> None:
    key = profit.name_key(client_name)
    result = await db.execute(
        delete(FinanceCostEntry).where(
            FinanceCostEntry.tenant_id == user.tenant_id,
            FinanceCostEntry.month == month,
            FinanceCostEntry.category == category,
            FinanceCostEntry.client_key == key,
            FinanceCostEntry.source == "manual",
        )
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="No such cost entry")
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="finance_cost:deleted",
        resource="finance_cost_entry",
        resource_id=f"{month}:{category}:{key}",
        changes={"month": month, "category": category, "client_key": key},
        request=request,
    )
    await db.commit()


@router.put("/profitability/clients", status_code=status.HTTP_204_NO_CONTENT)
async def save_client_master(
    body: ClientMasterIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("finance:write"))], db: DBSession
) -> None:
    name = " ".join(body.client_name.split())
    key = profit.name_key(name)
    if not key:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name the client")
    row = (
        await db.execute(
            select(FinanceClientMaster).where(FinanceClientMaster.tenant_id == user.tenant_id, FinanceClientMaster.client_key == key)
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    industry = " ".join(body.industry.split())
    if row is None:
        db.add(
            FinanceClientMaster(
                tenant_id=user.tenant_id,
                client_key=key,
                client_name=name,
                industry=industry,
                non_profit=body.non_profit,
                target_margin=body.target_margin,
                updated_at=now,
            )
        )
    else:
        row.client_name, row.industry, row.non_profit, row.target_margin, row.updated_at = (
            name,
            industry,
            body.non_profit,
            body.target_margin,
            now,
        )
    await db.flush()
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="finance_client_master:saved",
        resource="finance_client_master",
        resource_id=key,
        changes={"client_key": key, "industry": industry},
        request=request,
    )
    await db.commit()


@router.delete("/profitability/clients", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client_master(
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("finance:write"))],
    db: DBSession,
    client_name: str = Query(min_length=1, max_length=200),
) -> None:
    key = profit.name_key(client_name)
    result = await db.execute(
        delete(FinanceClientMaster).where(FinanceClientMaster.tenant_id == user.tenant_id, FinanceClientMaster.client_key == key)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="No such client in the master")
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="finance_client_master:deleted",
        resource="finance_client_master",
        resource_id=key,
        changes={"client_key": key},
        request=request,
    )
    await db.commit()


@router.put("/profitability/settings", status_code=status.HTTP_204_NO_CONTENT)
async def save_finance_settings(
    body: SettingsIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("finance:write"))], db: DBSession
) -> None:
    row = (await db.execute(select(FinanceSettings).where(FinanceSettings.tenant_id == user.tenant_id))).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None:
        db.add(FinanceSettings(tenant_id=user.tenant_id, available_hours_per_month=body.available_hours_per_month, updated_at=now))
    else:
        row.available_hours_per_month, row.updated_at = body.available_hours_per_month, now
    await db.flush()
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="finance_settings:saved",
        resource="finance_settings",
        resource_id="available_hours_per_month",
        changes={"available_hours_per_month": str(body.available_hours_per_month)},
        request=request,
    )
    await db.commit()


class ClientMasterImportIn(BaseModel):
    rows: list[ClientMasterIn] = Field(max_length=2000)


@router.put("/profitability/clients/import")
async def import_client_master(
    body: ClientMasterImportIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("finance:write"))], db: DBSession
) -> dict[str, int]:
    """Add or update many clients at once (the master sheet pasted or uploaded as a CSV on the page). A row with no usable name is skipped; the last row wins when a name repeats. One audit line."""
    existing = (await db.execute(select(FinanceClientMaster).where(FinanceClientMaster.tenant_id == user.tenant_id))).scalars().all()
    by_key = {r.client_key: r for r in existing}
    now = datetime.now(UTC)
    wanted: dict[str, ClientMasterIn] = {}
    skipped = 0
    for row in body.rows:
        key = profit.name_key(row.client_name)
        if not key:
            skipped += 1
            continue
        wanted[key] = row
    for key, row in wanted.items():
        name, industry = " ".join(row.client_name.split()), " ".join(row.industry.split())
        found = by_key.get(key)
        if found is None:
            db.add(
                FinanceClientMaster(
                    tenant_id=user.tenant_id,
                    client_key=key,
                    client_name=name,
                    industry=industry,
                    non_profit=row.non_profit,
                    target_margin=row.target_margin,
                    updated_at=now,
                )
            )
        else:
            found.client_name, found.industry, found.non_profit, found.target_margin, found.updated_at = (
                name,
                industry,
                row.non_profit,
                row.target_margin,
                now,
            )
    await db.flush()
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="finance_client_master:imported",
        resource="finance_client_master",
        resource_id="import",
        changes={"saved": len(wanted), "skipped": skipped},
        request=request,
    )
    await db.commit()
    return {"saved": len(wanted), "skipped": skipped}

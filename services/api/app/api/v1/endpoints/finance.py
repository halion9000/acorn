"""Estimated margin per client, from what each invoice line sells and costs per unit and what each client is billed for.

Read with ``finance:view``, change prices with ``finance:write``: neither is held by anyone who only holds the licence-count permissions, so the owner decides (through roles) who sees money. The billed
quantities are the HaloPSA counts A.C.O.R.N already holds; the prices and costs are typed in here by a person.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.billing import BILLED_SOURCE, _all_client_counts
from app.models.finance_price import FinanceItemPrice
from app.services import finance as fin
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
    return PriceOut(invoice_item=r.invoice_item, unit_price=str(fin.money(r.unit_price)), unit_cost=str(fin.money(r.unit_cost)), updated_at=r.updated_at)


async def _billed(db: Any, owner: uuid.UUID) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    per_client, names = await _all_client_counts(db, owner)
    billed = {
        str(cid): [{"item": r["item"], "count": r["count"]} for r in rows if r["source"] == BILLED_SOURCE and r.get("unit") != "ticket"]
        for cid, rows in per_client.items()
    }
    return billed, {str(k): v for k, v in names.items()}


@router.get("/prices", response_model=PricesOut, dependencies=[Depends(require_permission("finance:view"))])
async def list_prices(user: AuthUser, db: DBSession) -> PricesOut:
    rows = (await db.execute(select(FinanceItemPrice).where(FinanceItemPrice.tenant_id == user.tenant_id).order_by(FinanceItemPrice.invoice_item))).scalars().all()
    billed, _ = await _billed(db, user.tenant_id)
    items = sorted({line["item"] for lines in billed.values() for line in lines})
    return PricesOut(prices=[_out(r) for r in rows], billed_items=items)


@router.put("/prices", response_model=PriceOut)
async def save_price(body: PriceIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("finance:write"))], db: DBSession) -> PriceOut:
    item = " ".join(body.invoice_item.split())
    if not item:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name the invoice line")
    row = (await db.execute(select(FinanceItemPrice).where(FinanceItemPrice.tenant_id == user.tenant_id, FinanceItemPrice.invoice_item == item))).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None:
        row = FinanceItemPrice(tenant_id=user.tenant_id, invoice_item=item, unit_price=body.unit_price, unit_cost=body.unit_cost, updated_by=user.user_id, updated_at=now)
        db.add(row)
    else:
        row.unit_price, row.unit_cost, row.updated_by, row.updated_at = body.unit_price, body.unit_cost, user.user_id, now
    await db.flush()
    # The audit entry names the line and who changed it, not the amounts (money stays out of the log).
    await emit_audit(db=db, tenant_id=user.tenant_id, actor_id=user.user_id, action="finance_price:saved", resource="finance_item_price", resource_id=str(row.id), changes={"invoice_item": item}, request=request)
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.delete("/prices", status_code=status.HTTP_204_NO_CONTENT)
async def delete_price(invoice_item: str, request: Request, user: Annotated[AuthUser, Depends(require_permission("finance:write"))], db: DBSession) -> None:
    item = " ".join(invoice_item.split())
    await db.execute(delete(FinanceItemPrice).where(FinanceItemPrice.tenant_id == user.tenant_id, FinanceItemPrice.invoice_item == item))
    await emit_audit(db=db, tenant_id=user.tenant_id, actor_id=user.user_id, action="finance_price:deleted", resource="finance_item_price", resource_id=item, changes={"invoice_item": item}, request=request)
    await db.commit()


@router.get("/margin", dependencies=[Depends(require_permission("finance:view"))])
async def margin(user: AuthUser, db: DBSession) -> dict[str, Any]:
    """Estimated revenue, cost and margin per client, lowest margin first, and what each estimate is missing (invoice lines billed but not priced)."""
    rows = (await db.execute(select(FinanceItemPrice).where(FinanceItemPrice.tenant_id == user.tenant_id))).scalars().all()
    prices = {r.invoice_item: (Decimal(r.unit_price), Decimal(r.unit_cost)) for r in rows}
    billed, names = await _billed(db, user.tenant_id)
    out = fin.margin_rows(billed, prices, names)
    out["priced_items"] = len(prices)
    out["note"] = "An estimate: only invoice lines with both a price and a cost are counted, using the quantities each client is billed for. Lines billed but not priced are listed per client."
    return out

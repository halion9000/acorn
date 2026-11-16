"""Billing sync: the approve-and-push page (Sales and Finance), after the Rewst saas-billing app.

Each row is a license-count difference: what HaloPSA bills a client for an invoice line against what the tools count (the same differences ``/billing/reconcile`` finds). A person with ``billing:push`` (the
built-in billing role has it) can approve one or several: A.C.O.R.N queues a ``halo_billing_update`` action for CORE (vendor ``core``; A.C.O.R.N holds no HaloPSA key), which sets the client's recurring
invoice line to the counted quantity and reads it back. Approving needs no second approval. Rows can be hidden (and brought back); a hidden row is kept out of the list, and a row whose count changed since it
was hidden stays hidden until a person unhides it. Reading needs ``billing:view``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.billing import reconcile_billing
from app.models.billing_sync import BillingSyncItem
from app.models.client_alias import ClientAlias
from app.models.vendor_action import VendorAction
from app.services.audit import emit_audit

router = APIRouter(prefix="/billing/sync", tags=["billing"])

ACTION = "halo_billing_update"
VENDOR = "core"
# A push still waiting or running for a line is not asked again.
OPEN = ("pending", "claimed")


class PushOut(BaseModel):
    status: str  # none, pending, claimed, done or failed
    quantity: int | None = None
    message: str | None = None
    by: str | None = None
    at: datetime | None = None


class SyncRow(BaseModel):
    client_id: uuid.UUID
    client_name: str
    invoice_item: str
    billed: int
    counted: int
    difference: int
    hidden: bool
    # False when the client is not mapped to a HaloPSA client, so there is nothing to push to.
    can_push: bool
    push: PushOut


class SyncOut(BaseModel):
    generated_at: datetime
    rows: list[SyncRow]
    hidden: int
    can_push: bool


class ItemIn(BaseModel):
    client_id: uuid.UUID
    invoice_item: str = Field(min_length=1, max_length=200)


class ApproveIn(BaseModel):
    items: list[ItemIn] = Field(min_length=1, max_length=200)


class HideIn(BaseModel):
    items: list[ItemIn] = Field(min_length=1, max_length=500)
    hidden: bool = True


class ApproveResult(BaseModel):
    client_id: uuid.UUID
    invoice_item: str
    ok: bool
    detail: str


async def _rows(user: AuthUser, db: DBSession) -> list[Any]:
    out = await reconcile_billing(user, db, include_matches=True, limit=2000, min_days=None)
    return out.rows


async def _halo_ids(db: DBSession, owner: uuid.UUID, client_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
    """{client tenant id: (HaloPSA client id, name)} for the clients that are mapped to HaloPSA."""
    if not client_ids:
        return {}
    rows = (
        (
            await db.execute(
                select(ClientAlias).where(
                    ClientAlias.tenant_id == owner, ClientAlias.vendor == "halopsa", ClientAlias.child_tenant_id.in_(client_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    return {r.child_tenant_id: (r.vendor_client_id, r.vendor_client_name) for r in rows if r.child_tenant_id}


@router.get("", response_model=SyncOut, dependencies=[Depends(require_permission("billing:view"))])
async def list_sync(user: AuthUser, db: DBSession, show_hidden: bool = False) -> SyncOut:
    """The differences between what is billed and what is counted, with what has been hidden and the last push of each line."""
    rows = await _rows(user, db)
    state = {
        (s.client_id, s.invoice_item): s
        for s in (await db.execute(select(BillingSyncItem).where(BillingSyncItem.tenant_id == user.tenant_id))).scalars().all()
    }
    actions = {}
    ids = [s.action_id for s in state.values() if s.action_id]
    if ids:
        actions = {
            a.id: a
            for a in (await db.execute(select(VendorAction).where(VendorAction.tenant_id == user.tenant_id, VendorAction.id.in_(ids))))
            .scalars()
            .all()
        }
    halo = await _halo_ids(db, user.tenant_id, list({r.client_id for r in rows}))
    out: list[SyncRow] = []
    hidden = 0
    for r in rows:
        if r.difference == 0:
            continue
        s = state.get((r.client_id, r.invoice_item))
        is_hidden = bool(s and s.hidden)
        if is_hidden:
            hidden += 1
            if not show_hidden:
                continue
        a = actions.get(s.action_id) if s and s.action_id else None
        push = (
            PushOut(status=a.status, quantity=s.pushed_quantity, message=a.result_message, by=s.pushed_by, at=s.pushed_at)
            if a is not None and s is not None
            else PushOut(status="none")
        )
        out.append(
            SyncRow(
                client_id=r.client_id,
                client_name=r.client_name,
                invoice_item=r.invoice_item,
                billed=r.billed,
                counted=r.counted,
                difference=r.difference,
                hidden=is_hidden,
                can_push=r.client_id in halo,
                push=push,
            )
        )
    return SyncOut(generated_at=datetime.now(UTC), rows=out, hidden=hidden, can_push=True)


async def _state(db: DBSession, tenant: uuid.UUID, client_id: uuid.UUID, item: str) -> BillingSyncItem:
    row = (
        await db.execute(
            select(BillingSyncItem).where(
                BillingSyncItem.tenant_id == tenant, BillingSyncItem.client_id == client_id, BillingSyncItem.invoice_item == item
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = BillingSyncItem(tenant_id=tenant, client_id=client_id, invoice_item=item, hidden=False)
        db.add(row)
    return row


@router.post("/approve", response_model=list[ApproveResult])
async def approve(
    body: ApproveIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("billing:push"))], db: DBSession
) -> list[ApproveResult]:
    """Queue the push of the counted quantity to HaloPSA for each line. The quantity is the one A.C.O.R.N counts NOW (never one the caller sends), so an approval cannot set an arbitrary number."""
    current = {(r.client_id, r.invoice_item): r for r in await _rows(user, db)}
    halo = await _halo_ids(db, user.tenant_id, list({i.client_id for i in body.items}))
    now = datetime.now(UTC)
    results: list[ApproveResult] = []
    for item in body.items:
        r = current.get((item.client_id, item.invoice_item))
        if r is None or r.difference == 0:
            results.append(
                ApproveResult(client_id=item.client_id, invoice_item=item.invoice_item, ok=False, detail="This line no longer differs.")
            )
            continue
        if item.client_id not in halo:
            results.append(
                ApproveResult(
                    client_id=item.client_id,
                    invoice_item=item.invoice_item,
                    ok=False,
                    detail="This client is not mapped to a HaloPSA client.",
                )
            )
            continue
        s = await _state(db, user.tenant_id, item.client_id, item.invoice_item)
        if s.action_id:
            open_action = (
                await db.execute(select(VendorAction).where(VendorAction.id == s.action_id, VendorAction.status.in_(OPEN)))
            ).scalar_one_or_none()
            if open_action is not None:
                results.append(
                    ApproveResult(
                        client_id=item.client_id, invoice_item=item.invoice_item, ok=False, detail="A push for this line is still waiting."
                    )
                )
                continue
        halo_id, halo_name = halo[item.client_id]
        action = VendorAction(
            id=uuid.uuid4(),
            tenant_id=user.tenant_id,
            alert_id=None,
            incident_uid=f"billing:{item.client_id}:{uuid.uuid4().hex[:8]}",
            vendor=VENDOR,
            action=ACTION,
            params={
                "halo_client_id": halo_id,
                "halo_client_name": halo_name[:200],
                "invoice_item": item.invoice_item[:200],
                "quantity": int(r.counted),
                "previous": int(r.billed),
            },
            status="pending",
            requested_by=user.user_id,
            created_at=now,
        )
        db.add(action)
        s.action_id, s.pushed_quantity, s.pushed_by, s.pushed_at, s.updated_at = action.id, int(r.counted), user.email, now, now
        s.hidden = False
        results.append(
            ApproveResult(
                client_id=item.client_id,
                invoice_item=item.invoice_item,
                ok=True,
                detail=f"Queued: set to {int(r.counted)} (was {int(r.billed)}).",
            )
        )
    await db.flush()
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="billing_sync:approved",
        resource="billing_sync",
        resource_id="approve",
        changes={"requested": len(body.items), "queued": sum(1 for x in results if x.ok)},
        request=request,
    )
    await db.commit()
    return results


@router.post("/hide")
async def hide(
    body: HideIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("billing:push"))], db: DBSession
) -> dict[str, int]:
    """Hide lines from the list (or bring them back). Hiding changes nothing at HaloPSA."""
    for item in body.items:
        s = await _state(db, user.tenant_id, item.client_id, item.invoice_item)
        s.hidden, s.updated_at = body.hidden, datetime.now(UTC)
    await db.flush()
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="billing_sync:hidden" if body.hidden else "billing_sync:unhidden",
        resource="billing_sync",
        resource_id="hide",
        changes={"lines": len(body.items)},
        request=request,
    )
    await db.commit()
    return {"changed": len(body.items)}

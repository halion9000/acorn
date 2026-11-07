"""Add a person who has a cloud account but no HaloPSA user to HaloPSA, from the Identities page: POST /identities/halo-user.

A.C.O.R.N holds no HaloPSA key. A click queues one row for CORE (the ``vendor_actions`` queue, vendor ``core``, action ``create_halo_user``) with the person's name and address and the HaloPSA client the client is mapped
to; CORE creates the user under that client's main site and reports the outcome, which the page reads back. So a click is a request, never proof: "done" is only what CORE reported. Needs ``identities:respond``
and the page's confirmation; every request is audited with who asked. The client must be mapped to a HaloPSA client (Settings, Client mapping).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import _as, _scope
from app.api.v1.endpoints.identity_actions import clean_email, shown_status
from app.models.client_alias import ClientAlias
from app.models.vendor_action import VendorAction
from app.services.audit import emit_audit
from app.services.vendor_actions import PENDING_TTL

router = APIRouter(prefix="/identities/halo-user", tags=["identities"])

ACTION = "create_halo_user"
RECENT_DAYS = 7
NAME_MAX = 120


class HaloUserBody(BaseModel):
    client_id: uuid.UUID
    email: str = Field(max_length=320)
    name: str = Field(default="", max_length=200)
    confirm: bool = Field(default=False, description="True only when the person pressed Yes in the confirmation window.")


class HaloUserItem(BaseModel):
    id: uuid.UUID
    email: str
    status: str
    message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


def display_name(name: str, email: str) -> str:
    """The name the HaloPSA user gets: the one given (one line, trimmed), else the part of the address before the @ with dots and underscores as spaces, capitalised (pure)."""
    given = " ".join((name or "").split())[:NAME_MAX]
    if given:
        return given
    local = email.split("@", 1)[0].replace(".", " ").replace("_", " ").replace("-", " ")
    return " ".join(w.capitalize() for w in local.split())[:NAME_MAX] or email[:NAME_MAX]


def item_of(row: VendorAction) -> HaloUserItem:
    return HaloUserItem(
        id=row.id,
        email=str((row.params or {}).get("email") or ""),
        status=shown_status(row.status),
        message=row.result_message,
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


async def halo_client(db: DBSession, owner: uuid.UUID, client: uuid.UUID) -> str | None:
    """The HaloPSA client id this client is mapped to (digits), or None."""
    row = (
        await db.execute(
            select(ClientAlias.vendor_client_id)
            .where(
                ClientAlias.tenant_id == owner,
                ClientAlias.child_tenant_id == client,
                ClientAlias.vendor == "halopsa",
                ClientAlias.ignored.is_(False),
            )
            .order_by(ClientAlias.updated_at.desc())
            .limit(1)
        )
    ).first()
    value = str(row[0]) if row else ""
    return value if value.isdigit() else None


@router.post("", response_model=HaloUserItem, status_code=status.HTTP_202_ACCEPTED)
async def request_halo_user(
    body: HaloUserBody,
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("identities:respond"))],
    db: DBSession,
) -> HaloUserItem:
    """Queue the creation of one HaloPSA user for CORE. Returns 202: nothing has happened in HaloPSA yet."""
    if not body.confirm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Confirm the action first.")
    email = clean_email(body.email)
    owner = user.tenant_id
    await _scope(db, owner, body.client_id)
    if body.client_id == owner:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Pick a client: HaloPSA users belong to a client.")
    halo = await halo_client(db, owner, body.client_id)
    if not halo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This client is not linked to a HaloPSA client (Settings, Client mapping), so there is nowhere to add the user.",
        )
    now = datetime.now(UTC)
    uid = f"halo-user:{email.lower()}"
    async with _as(db, owner, body.client_id):
        waiting = (
            await db.execute(
                select(VendorAction.id).where(
                    VendorAction.tenant_id == body.client_id,
                    VendorAction.vendor == "core",
                    VendorAction.incident_uid == uid,
                    VendorAction.action == ACTION,
                    VendorAction.status.in_(("pending", "claimed")),
                    VendorAction.created_at > now - PENDING_TTL,
                )
            )
        ).first()
        if waiting:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="The same request for this person is already waiting for CORE."
            )
        row = VendorAction(
            id=uuid.uuid4(),
            tenant_id=body.client_id,
            alert_id=None,
            vendor="core",
            incident_uid=uid,
            action=ACTION,
            params={
                "halo_client_id": halo,
                "email": email,
                "name": display_name(body.name, email),
                "requested_by_name": (getattr(user, "email", None) or "")[:200] or None,
            },
            status="pending",
            requested_by=user.user_id,
            created_at=now,
        )
        db.add(row)
        await db.flush()
        await emit_audit(
            db=db,
            tenant_id=body.client_id,
            actor_id=user.user_id,
            action="identities:halo_user_requested",
            resource="identity",
            resource_id=email,
            changes={"email": email, "halo_client_id": halo, "vendor_action_id": str(row.id)},
            request=request,
        )
        await db.commit()
        return item_of(row)


@router.get("", response_model=list[HaloUserItem])
async def recent_halo_user_requests(
    user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    client_id: uuid.UUID,
    email: Annotated[str, Query(max_length=320)],
) -> list[HaloUserItem]:
    """What was asked for this person in the last week and how each went (read only)."""
    owner = user.tenant_id
    await _scope(db, owner, client_id)
    address = email.strip().lower()
    if not address or client_id == owner:
        return []
    since = datetime.now(UTC) - timedelta(days=RECENT_DAYS)
    async with _as(db, owner, client_id):
        rows = (
            (
                await db.execute(
                    select(VendorAction)
                    .where(
                        VendorAction.tenant_id == client_id,
                        VendorAction.vendor == "core",
                        VendorAction.incident_uid == f"halo-user:{address}",
                        VendorAction.action == ACTION,
                        VendorAction.created_at > since,
                    )
                    .order_by(VendorAction.created_at.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
    return [item_of(r) for r in rows]

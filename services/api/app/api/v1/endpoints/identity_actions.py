"""Account actions on the Identities page: sign a person out of Microsoft 365 everywhere, block their sign-in, or let it back.

A.C.O.R.N never holds the Microsoft 365 or CIPP credentials. A click here queues one row for CORE (the ``vendor_actions`` queue, vendor ``core``); CORE collects it, carries it out through CIPP under its
own rules (its switch ``CIPP_ACTIONS_LIVE``, the clients opted in, the protected accounts, the hourly cap) and reports the outcome, which the page reads back. So a click is a request, never proof that
something happened: the row says pending, running, done or failed, and "done" is only ever what CORE reported.

The route needs the permission ``identities:respond``, which no other permission implies (an administrator holds it through ``*``; anyone else only through a custom role that ticks it). The caller must
say they confirmed (``confirm: true``, the page's "Are you sure?" window), and every request is written to the audit log with who asked.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import _as, _scope
from app.models.client_alias import ClientAlias
from app.models.vendor_action import VendorAction
from app.services.audit import emit_audit
from app.services.vendor_actions import PENDING_TTL

router = APIRouter(prefix="/identities/actions", tags=["identities"])

ACTIONS: dict[str, str] = {
    "revoke_sessions": "Sign out everywhere",
    "disable_user": "Block sign-in",
    "enable_user": "Allow sign-in",
}
# A plain mailbox address: what the page shows and what CIPP is asked about. Anything else (a space, a quote, a second address) is refused before it can reach CORE.
_EMAIL = re.compile(r"^[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,24}$")
RECENT_DAYS = 7


class ActionBody(BaseModel):
    client_id: uuid.UUID
    email: str = Field(max_length=320)
    action: Literal["revoke_sessions", "disable_user", "enable_user"]
    confirm: bool = Field(default=False, description="True only when the person pressed Yes in the confirmation window.")


class ActionItem(BaseModel):
    id: uuid.UUID
    action: str
    label: str
    email: str
    status: Literal["pending", "running", "done", "failed"]
    message: str | None = None
    requested_by: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class ActionList(BaseModel):
    items: list[ActionItem]


def shown_status(row_status: str) -> str:
    """The queue calls a collected row ``claimed``; the page says it is running."""
    return "running" if row_status == "claimed" else row_status


def item_of(row: VendorAction) -> ActionItem:
    params: dict[str, Any] = row.params or {}
    return ActionItem(
        id=row.id,
        action=row.action,
        label=ACTIONS.get(row.action, row.action),
        email=str(params.get("user") or ""),
        status=shown_status(row.status),  # type: ignore[arg-type]
        message=row.result_message,
        requested_by=params.get("requested_by_name"),
        created_at=row.created_at,
        finished_at=row.finished_at,
    )


def clean_email(value: str) -> str:
    email = (value or "").strip()
    if not _EMAIL.match(email):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That is not a plain e-mail address.")
    return email


def build_row(
    *,
    tenant_id: uuid.UUID,
    cipp_client: str,
    email: str,
    action: str,
    requested_by: uuid.UUID | None,
    requested_by_name: str | None,
    now: datetime,
) -> VendorAction:
    """The queue row CORE will collect. ``params.client_id`` is the CIPP customer id and ``params.user`` the sign-in name, as CORE's CIPP route reads them."""
    return VendorAction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        alert_id=None,
        vendor="core",
        incident_uid=f"identity:{email.lower()}",
        action=action,
        params={"client_id": cipp_client, "user": email, "requested_by_name": (requested_by_name or "")[:200] or None},
        status="pending",
        requested_by=requested_by,
        created_at=now,
    )


async def cipp_customer(db: Any, owner: uuid.UUID, client: uuid.UUID) -> str | None:
    """The CIPP customer id this client is mapped to, or None."""
    row = (
        await db.execute(
            select(ClientAlias.vendor_client_id)
            .where(
                ClientAlias.tenant_id == owner,
                ClientAlias.child_tenant_id == client,
                ClientAlias.vendor == "cipp",
                ClientAlias.ignored.is_(False),
            )
            .order_by(ClientAlias.updated_at.desc())
            .limit(1)
        )
    ).first()
    return str(row[0]) if row else None


@router.post("", response_model=ActionItem, status_code=status.HTTP_202_ACCEPTED)
async def request_identity_action(
    body: ActionBody,
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("identities:respond"))],
    db: DBSession,
) -> ActionItem:
    """Queue one account action for CORE. Returns 202: nothing has happened in Microsoft 365 yet."""
    if not body.confirm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Confirm the action first.")
    email = clean_email(body.email)
    owner = user.tenant_id
    await _scope(db, owner, body.client_id)  # 404 for a client that is not this company's
    if body.client_id == owner:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Pick a client: account actions are for a client's people."
        )
    cipp = await cipp_customer(db, owner, body.client_id)
    if not cipp:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This client is not linked to CIPP (Settings, Client mapping), so there is no Microsoft 365 account to act on.",
        )
    now = datetime.now(UTC)
    async with _as(db, owner, body.client_id):
        waiting = (
            (
                await db.execute(
                    select(VendorAction).where(
                        VendorAction.tenant_id == body.client_id,
                        VendorAction.vendor == "core",
                        VendorAction.incident_uid == f"identity:{email.lower()}",
                        VendorAction.action == body.action,
                        VendorAction.status.in_(("pending", "claimed")),
                        VendorAction.created_at > now - PENDING_TTL,
                    )
                )
            )
            .scalars()
            .all()
        )
        if waiting:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="The same request for this person is already waiting for CORE."
            )
        row = build_row(
            tenant_id=body.client_id,
            cipp_client=cipp,
            email=email,
            action=body.action,
            requested_by=user.user_id,
            requested_by_name=getattr(user, "email", None),
            now=now,
        )
        db.add(row)
        await db.flush()
        await emit_audit(
            db=db,
            tenant_id=body.client_id,
            actor_id=user.user_id,
            action="identities:account_action_requested",
            resource="identity",
            resource_id=email,
            changes={"action": body.action, "email": email, "vendor_action_id": str(row.id)},
            request=request,
        )
        await db.commit()
        return item_of(row)


@router.get("", response_model=ActionList)
async def recent_identity_actions(
    user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    client_id: uuid.UUID,
    email: Annotated[str, Query(max_length=320)],
) -> ActionList:
    """What was asked for this person in the last week and how each went (read only; anyone who can read alerts can see it)."""
    owner = user.tenant_id
    await _scope(db, owner, client_id)
    address = email.strip().lower()
    if not address or client_id == owner:
        return ActionList(items=[])
    since = datetime.now(UTC) - timedelta(days=RECENT_DAYS)
    async with _as(db, owner, client_id):
        rows = (
            (
                await db.execute(
                    select(VendorAction)
                    .where(
                        VendorAction.tenant_id == client_id,
                        VendorAction.vendor == "core",
                        VendorAction.incident_uid == f"identity:{address}",
                        VendorAction.action.in_(tuple(ACTIONS)),
                        VendorAction.created_at > since,
                    )
                    .order_by(VendorAction.created_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
    return ActionList(items=[item_of(r) for r in rows])

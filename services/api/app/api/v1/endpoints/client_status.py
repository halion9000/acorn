"""A read-only status page a client can open through a private link, no sign-in.

Two halves. The ADMIN half (``/client-status-links``): a person with ``settings:write`` on a signed-in session makes a link for one of their clients (the secret is returned ONCE and only its hash is
kept), previews exactly what the client will see, reviews the wording (a link does nothing until this is done), and revokes it. The PUBLIC half (``GET /public/client-status/{token}``): checks the secret's hash,
that the link is not revoked, expired or unreviewed, then returns the client-safe summary from ``app.services.client_status`` (counts and plain labels, never raw alerts, names, devices or tickets).
Any problem with a link gets the same 404, so a caller cannot tell a wrong secret from a revoked one.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.v1.deps import AuthUser, DBSession, require_permission, require_signed_in_session
from app.api.v1.endpoints.client_posture import client_posture
from app.db.rls_scope import cross_tenant_reads
from app.db.rls_sessions import adopt_tenant
from app.models.client_status_link import ClientStatusLink
from app.models.tenant import Tenant
from app.services import client_status as cs
from app.services.audit import emit_audit

router = APIRouter(prefix="/client-status-links", tags=["client-status"])
public_router = APIRouter(prefix="/public/client-status", tags=["client-status"])

MAX_ACTIVE = 200
DEFAULT_DAYS = 90
MAX_DAYS = 365


class LinkIn(BaseModel):
    client_id: uuid.UUID
    label: str = Field(default="", max_length=80)
    days: int = Field(default=DEFAULT_DAYS, ge=1, le=MAX_DAYS)


class LinkOut(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    client_name: str | None
    label: str
    created_at: datetime
    expires_at: datetime
    reviewed_at: datetime | None
    revoked_at: datetime | None
    last_opened_at: datetime | None
    state: str  # live / not reviewed / expired / revoked


class LinkCreated(LinkOut):
    # The secret address part, shown ONCE. Put it after /status/ on the console's address; it cannot be shown again.
    token: str


def _state(row: ClientStatusLink, now: datetime) -> str:
    problem = cs.link_problem({"revoked_at": row.revoked_at, "expires_at": row.expires_at, "reviewed_at": row.reviewed_at}, now)
    return problem or "live"


def _out(row: ClientStatusLink, names: dict[uuid.UUID, str], now: datetime) -> LinkOut:
    return LinkOut(
        id=row.id,
        client_id=row.client_id,
        client_name=names.get(row.client_id),
        label=row.label,
        created_at=row.created_at,
        expires_at=row.expires_at,
        reviewed_at=row.reviewed_at,
        revoked_at=row.revoked_at,
        last_opened_at=row.last_opened_at,
        state=_state(row, now),
    )


async def _names(db: Any, owner: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == owner))).all()
    return dict(rows)


async def _own_link(db: Any, owner: uuid.UUID, link_id: uuid.UUID) -> ClientStatusLink:
    row = (
        await db.execute(select(ClientStatusLink).where(ClientStatusLink.id == link_id, ClientStatusLink.tenant_id == owner))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such link")
    return row


async def summary_for(db: Any, owner: uuid.UUID, client_id: uuid.UUID) -> dict[str, Any]:
    """The client-safe page for one client, built from the client's posture (the same numbers the console shows)."""
    posture = await client_posture(client_id, SimpleNamespace(tenant_id=owner), db)  # type: ignore[arg-type]
    return cs.project(posture.model_dump())


class ClientChoice(BaseModel):
    id: uuid.UUID
    name: str


class LinksOut(BaseModel):
    links: list[LinkOut]
    # The clients a link can be made for, for the picker.
    clients: list[ClientChoice]
    default_days: int


@router.get("", response_model=LinksOut, dependencies=[Depends(require_permission("settings_clients:view"))])
async def list_links(user: AuthUser, db: DBSession) -> LinksOut:
    now = datetime.now(UTC)
    rows = (
        (
            await db.execute(
                select(ClientStatusLink)
                .where(ClientStatusLink.tenant_id == user.tenant_id)
                .order_by(ClientStatusLink.created_at.desc())
                .limit(300)
            )
        )
        .scalars()
        .all()
    )
    names = await _names(db, user.tenant_id)
    return LinksOut(
        links=[_out(r, names, now) for r in rows],
        clients=[ClientChoice(id=i, name=n) for i, n in sorted(names.items(), key=lambda kv: kv[1].lower())],
        default_days=DEFAULT_DAYS,
    )


@router.post("", response_model=LinkCreated, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_signed_in_session)])
async def create_link(
    body: LinkIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("settings_clients:manage"))], db: DBSession
) -> LinkCreated:
    names = await _names(db, user.tenant_id)
    if body.client_id not in names:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    now = datetime.now(UTC)
    active = (
        await db.execute(
            select(func.count())
            .select_from(ClientStatusLink)
            .where(ClientStatusLink.tenant_id == user.tenant_id, ClientStatusLink.revoked_at.is_(None), ClientStatusLink.expires_at > now)
        )
    ).scalar_one()
    if active >= MAX_ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"There are already {MAX_ACTIVE} active links; revoke some first.")
    token = cs.new_token()
    row = ClientStatusLink(
        tenant_id=user.tenant_id,
        client_id=body.client_id,
        token_hash=cs.hash_token(token),
        label=body.label.strip(),
        created_by=user.user_id,
        expires_at=now + timedelta(days=body.days),
    )
    db.add(row)
    await db.flush()
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="client_status_link:created",
        resource="client_status_link",
        resource_id=str(row.id),
        changes={"client_id": str(body.client_id), "days": body.days},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return LinkCreated(**_out(row, names, now).model_dump(), token=token)


@router.get("/{link_id}/preview", dependencies=[Depends(require_permission("settings_clients:view"))])
async def preview_link(link_id: uuid.UUID, user: AuthUser, db: DBSession) -> dict[str, Any]:
    """Exactly what the client would see for this link (the same function the public page uses), so the wording can be reviewed before the link is switched on."""
    row = await _own_link(db, user.tenant_id, link_id)
    return await summary_for(db, user.tenant_id, row.client_id)


@router.post("/{link_id}/review", response_model=LinkOut, dependencies=[Depends(require_signed_in_session)])
async def review_link(
    link_id: uuid.UUID, request: Request, user: Annotated[AuthUser, Depends(require_permission("settings_clients:manage"))], db: DBSession
) -> LinkOut:
    """A person has read the preview and is happy with what the client will see: the link starts to work."""
    row = await _own_link(db, user.tenant_id, link_id)
    now = datetime.now(UTC)
    if row.reviewed_at is None:
        row.reviewed_at = now
        row.reviewed_by = user.user_id
        await emit_audit(
            db=db,
            tenant_id=user.tenant_id,
            actor_id=user.user_id,
            action="client_status_link:reviewed",
            resource="client_status_link",
            resource_id=str(row.id),
            changes={"client_id": str(row.client_id)},
            request=request,
        )
        await db.commit()
        await db.refresh(row)
    return _out(row, await _names(db, user.tenant_id), now)


@router.post("/{link_id}/revoke", response_model=LinkOut, dependencies=[Depends(require_signed_in_session)])
async def revoke_link(
    link_id: uuid.UUID, request: Request, user: Annotated[AuthUser, Depends(require_permission("settings_clients:manage"))], db: DBSession
) -> LinkOut:
    row = await _own_link(db, user.tenant_id, link_id)
    now = datetime.now(UTC)
    if row.revoked_at is None:
        row.revoked_at = now
        await emit_audit(
            db=db,
            tenant_id=user.tenant_id,
            actor_id=user.user_id,
            action="client_status_link:revoked",
            resource="client_status_link",
            resource_id=str(row.id),
            changes={"client_id": str(row.client_id)},
            request=request,
        )
        await db.commit()
        await db.refresh(row)
    return _out(row, await _names(db, user.tenant_id), now)


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_signed_in_session)])
async def delete_link(
    link_id: uuid.UUID, request: Request, user: Annotated[AuthUser, Depends(require_permission("settings_clients:manage"))], db: DBSession
) -> Response:
    """Remove a link from the list for good. Only a link that is already revoked or has run out can be deleted: a live link must be revoked first, so a click cannot silently take a client's page away."""
    row = await _own_link(db, user.tenant_id, link_id)
    now = datetime.now(UTC)
    if row.revoked_at is None and row.expires_at > now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Revoke the link first; only a revoked or expired link can be deleted."
        )
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="client_status_link:deleted",
        resource="client_status_link",
        resource_id=str(row.id),
        changes={"client_id": str(row.client_id)},
        request=request,
    )
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@public_router.get("/{token}")
async def public_status(token: str, response: Response, db: DBSession) -> dict[str, Any]:
    """The client's page. No sign-in: the secret in the address is the credential, and every failure is the same 404."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    gone = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This link is not available.")
    if not cs.well_formed(token):
        raise gone
    # The owner is learned FROM the link, so this one lookup is a read across tenants by nature.
    async with cross_tenant_reads(db):
        row = (await db.execute(select(ClientStatusLink).where(ClientStatusLink.token_hash == cs.hash_token(token)))).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None or cs.link_problem({"revoked_at": row.revoked_at, "expires_at": row.expires_at, "reviewed_at": row.reviewed_at}, now):
        raise gone
    owner, client_id, link_id = row.tenant_id, row.client_id, row.id
    await adopt_tenant(db, owner)
    page = await summary_for(db, owner, client_id)
    with contextlib.suppress(Exception):
        fresh = await db.get(ClientStatusLink, link_id)
        if fresh is not None:
            fresh.last_opened_at = now
            await db.commit()
    return page

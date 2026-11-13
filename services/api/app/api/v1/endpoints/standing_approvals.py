"""Standing approvals: a person says "always allow this kind of agent action (for this client, or for all) until this date".

A new approval card that matches an active one is approved when it is created (see ``approvals.create_approval``) and says which standing approval did it. Only reversible kinds of action are
allowed (``app.services.standing_approvals.ALLOWED``). Making or revoking one is a person's act: a signed-in session with ``settings:write``, never an API key (an agent must not be able to grant itself
permission). Both are audited. Reading the list needs ``settings:read``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.v1.deps import AuthUser, require_permission, require_signed_in_session
from app.db.rls import TenantDBSession
from app.models.standing_approval import StandingApproval
from app.services import standing_approvals as sa
from app.services.audit import emit_audit

router = APIRouter(prefix="/standing-approvals", tags=["autonomy-policy"])

MAX_ACTIVE = 100


class StandingIn(BaseModel):
    action_type: str = Field(min_length=1, max_length=80)
    client_id: str | None = Field(default=None, max_length=80)
    days: int = Field(default=sa.DEFAULT_DAYS, ge=1, le=sa.MAX_DAYS)
    note: str = Field(default="", max_length=300)


class StandingManyIn(BaseModel):
    action_type: str = Field(min_length=1, max_length=80)
    client_ids: list[str] = Field(min_length=1, max_length=sa.MAX_CLIENTS_AT_ONCE)
    days: int = Field(default=sa.DEFAULT_DAYS, ge=1, le=sa.MAX_DAYS)
    note: str = Field(default="", max_length=300)


class StandingManyOut(BaseModel):
    created: list[StandingOut]
    # Clients that already had an active standing approval of this kind (their own, or one for all clients): nothing was added for them.
    already_covered: list[str]


class StandingOut(BaseModel):
    id: uuid.UUID
    action_type: str
    client_id: str | None
    note: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    state: str  # active / expired / revoked


class StandingList(BaseModel):
    items: list[StandingOut]
    allowed_types: list[str]
    default_days: int


def state_of(row: StandingApproval, now: datetime) -> str:
    if row.revoked_at is not None:
        return "revoked"
    return "expired" if row.expires_at <= now else "active"


def _out(row: StandingApproval, now: datetime) -> StandingOut:
    return StandingOut(
        id=row.id,
        action_type=row.action_type,
        client_id=row.client_id,
        note=row.note,
        created_at=row.created_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        state=state_of(row, now),
    )


@router.get("", response_model=StandingList, dependencies=[Depends(require_permission("settings_automation:view"))])
async def list_standing(user: AuthUser, db: TenantDBSession) -> StandingList:
    now = datetime.now(UTC)
    rows = (
        (
            await db.execute(
                select(StandingApproval)
                .where(StandingApproval.tenant_id == user.tenant_id)
                .order_by(StandingApproval.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    return StandingList(items=[_out(r, now) for r in rows], allowed_types=sorted(sa.ALLOWED), default_days=sa.DEFAULT_DAYS)


@router.post("", response_model=StandingOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_signed_in_session)])
async def create_standing(
    body: StandingIn,
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("settings_automation:manage"))],
    db: TenantDBSession,
) -> StandingOut:
    action_type = body.action_type.strip().lower()
    problem = sa.refusal(action_type)
    if problem:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)
    now = datetime.now(UTC)
    active = (
        await db.execute(
            select(func.count())
            .select_from(StandingApproval)
            .where(StandingApproval.tenant_id == user.tenant_id, StandingApproval.revoked_at.is_(None), StandingApproval.expires_at > now)
        )
    ).scalar_one()
    if active >= MAX_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"There are already {MAX_ACTIVE} active standing approvals; revoke some first."
        )
    row = StandingApproval(
        tenant_id=user.tenant_id,
        action_type=action_type,
        client_id=(body.client_id or "").strip() or None,
        note=body.note.strip(),
        created_by=user.user_id,
        expires_at=now + timedelta(days=body.days),
    )
    db.add(row)
    await db.flush()
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="standing_approval:created",
        resource="standing_approval",
        resource_id=str(row.id),
        changes={"action_type": row.action_type, "client_id": row.client_id, "days": body.days},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return _out(row, now)


@router.post(
    "/many", response_model=StandingManyOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_signed_in_session)]
)
async def create_standing_for_clients(
    body: StandingManyIn,
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("settings_automation:manage"))],
    db: TenantDBSession,
) -> StandingManyOut:
    """One standing approval for each of several clients at once (the same kind, the same number of days). Clients that are already covered are skipped and named. All or nothing: when
    adding them would pass the limit of active approvals, none is added."""
    action_type = body.action_type.strip().lower()
    problem = sa.refusal(action_type)
    if problem:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)
    targets = sa.client_targets(body.client_ids)
    if not targets:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choose at least one client.")
    now = datetime.now(UTC)
    active_rows = (
        (
            await db.execute(
                select(StandingApproval).where(
                    StandingApproval.tenant_id == user.tenant_id, StandingApproval.revoked_at.is_(None), StandingApproval.expires_at > now
                )
            )
        )
        .scalars()
        .all()
    )
    needed, covered = sa.clients_still_to_cover(
        targets, [{"action_type": r.action_type, "client_id": r.client_id} for r in active_rows], action_type
    )
    if len(active_rows) + len(needed) > MAX_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"That would pass the limit of {MAX_ACTIVE} active standing approvals ({len(active_rows)} now, {len(needed)} to add); revoke some first.",
        )
    rows = [
        StandingApproval(
            tenant_id=user.tenant_id,
            action_type=action_type,
            client_id=c,
            note=body.note.strip(),
            created_by=user.user_id,
            expires_at=now + timedelta(days=body.days),
        )
        for c in needed
    ]
    db.add_all(rows)
    await db.flush()
    for row in rows:
        await emit_audit(
            db=db,
            tenant_id=user.tenant_id,
            actor_id=user.user_id,
            action="standing_approval:created",
            resource="standing_approval",
            resource_id=str(row.id),
            changes={"action_type": row.action_type, "client_id": row.client_id, "days": body.days, "together_with": len(rows)},
            request=request,
        )
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return StandingManyOut(created=[_out(r, now) for r in rows], already_covered=covered)


@router.post("/{standing_id}/revoke", response_model=StandingOut, dependencies=[Depends(require_signed_in_session)])
async def revoke_standing(
    standing_id: uuid.UUID,
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("settings_automation:manage"))],
    db: TenantDBSession,
) -> StandingOut:
    row = (
        await db.execute(select(StandingApproval).where(StandingApproval.id == standing_id, StandingApproval.tenant_id == user.tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such standing approval")
    now = datetime.now(UTC)
    if row.revoked_at is None:
        row.revoked_at = now
        row.revoked_by = user.user_id
        await emit_audit(
            db=db,
            tenant_id=user.tenant_id,
            actor_id=user.user_id,
            action="standing_approval:revoked",
            resource="standing_approval",
            resource_id=str(row.id),
            changes={"action_type": row.action_type, "client_id": row.client_id},
            request=request,
        )
        await db.commit()
        await db.refresh(row)
    return _out(row, now)

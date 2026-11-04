"""Reviewing stale alerts: how many there are, and restoring or closing them in bulk.

An alert nobody touched for a month (see ``app/services/alert_stale.py``) is set aside as ``stale``, not deleted. The list shows them under the Stale filter; these routes are the bulk actions. Restoring
puts each back as it was; closing finishes them. Both need ``alerts:write`` and are audited. The prefix is ``/alert-stale`` and not under ``/alerts`` so it can never be read as an alert id.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import _scope
from app.core.config import settings
from app.db.rls_scope import cross_tenant_reads
from app.models.alert import Alert
from app.services.alert_stale import close_stale, exempt_severities, restore_stale
from app.services.alert_status import STALE
from app.services.audit import emit_audit

router = APIRouter(prefix="/alert-stale", tags=["alerts"])


class ClientCount(BaseModel):
    client_id: uuid.UUID
    count: int


class StaleSummary(BaseModel):
    days: int
    exempt_severities: list[str]
    total: int
    by_client: list[ClientCount]
    by_severity: dict[str, int]


class Selection(BaseModel):
    client_id: uuid.UUID | None = Field(default=None, description="Only this client's stale alerts; none given means every client's.")
    alert_ids: list[uuid.UUID] | None = Field(default=None, max_length=500, description="Only these alerts; none given means all in the client scope.")
    confirm: bool = Field(default=False, description="True only when the person pressed Yes in the confirmation window.")


class Changed(BaseModel):
    changed: int


@router.get("", response_model=StaleSummary)
async def stale_summary(user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, client_id: uuid.UUID | None = None) -> StaleSummary:
    """How many alerts are set aside as stale, by client and severity, and the rule that sets them aside."""
    scope, _ = await _scope(db, user.tenant_id, client_id)
    async with cross_tenant_reads(db):
        per_client = (await db.execute(select(Alert.tenant_id, func.count()).where(Alert.tenant_id.in_(scope), Alert.status == STALE).group_by(Alert.tenant_id))).all()
        per_severity = (await db.execute(select(Alert.severity, func.count()).where(Alert.tenant_id.in_(scope), Alert.status == STALE).group_by(Alert.severity))).all()
    return StaleSummary(
        days=settings.ALERT_STALE_DAYS,
        exempt_severities=list(exempt_severities(settings.ALERT_STALE_EXEMPT_SEVERITIES)),
        total=sum(n for _, n in per_client),
        by_client=sorted((ClientCount(client_id=t, count=n) for t, n in per_client), key=lambda c: -c.count)[:50],
        by_severity={str(s): int(n) for s, n in per_severity},
    )


async def _act(body: Selection, request: Request, user: AuthUser, db: DBSession, what: str) -> Changed:
    if not body.confirm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Confirm first.")
    scope, _ = await _scope(db, user.tenant_id, body.client_id)
    action = restore_stale if what == "restore" else close_stale
    async with cross_tenant_reads(db):
        n = await action(db, list(scope), body.alert_ids, datetime.now(UTC))
        await emit_audit(
            db=db,
            tenant_id=user.tenant_id,
            actor_id=user.user_id,
            action=f"alerts:stale_{what}d" if what == "restore" else "alerts:stale_closed",
            resource="alert",
            resource_id=str(body.client_id or "all"),
            changes={"count": n, "client": str(body.client_id) if body.client_id else None, "alert_ids": len(body.alert_ids) if body.alert_ids is not None else None},
            request=request,
        )
        await db.commit()
    return Changed(changed=n)


@router.post("/restore", response_model=Changed)
async def restore(body: Selection, request: Request, user: Annotated[AuthUser, Depends(require_permission("alerts:write"))], db: DBSession) -> Changed:
    """Put stale alerts back as they were."""
    return await _act(body, request, user, db, "restore")


@router.post("/close", response_model=Changed)
async def close(body: Selection, request: Request, user: Annotated[AuthUser, Depends(require_permission("alerts:write"))], db: DBSession) -> Changed:
    """Close stale alerts for good."""
    return await _act(body, request, user, db, "close")

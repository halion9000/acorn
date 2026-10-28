"""Playbook dry runs: which playbooks WOULD have run for an alert, and what they would have done. Nothing was run (see ``app.services.playbook_dry_runs``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.db.rls_scope import cross_tenant_reads
from app.models.alert import Alert
from app.models.playbook_dry_run import PlaybookDryRun
from app.models.tenant import Tenant

router = APIRouter(prefix="/playbook-dry-runs", tags=["playbooks"])

DEFAULT_LIMIT = 50


class DryRunStep(BaseModel):
    id: str
    type: str
    name: str


class DryRunOut(BaseModel):
    alert_id: uuid.UUID
    alert_title: str | None = None
    client_id: uuid.UUID
    client_name: str | None = None
    playbook_id: str
    playbook_name: str
    matched_on: list[str]
    steps: list[DryRunStep]
    created_at: datetime


class DryRunList(BaseModel):
    # Always true: this version records and shows, it takes no action.
    nothing_was_run: bool = True
    items: list[DryRunOut]


def to_out(run: Any, alert_title: str | None, client_name: str | None) -> DryRunOut:
    return DryRunOut(
        alert_id=run.alert_id,
        alert_title=alert_title,
        client_id=run.tenant_id,
        client_name=client_name,
        playbook_id=run.playbook_id,
        playbook_name=run.playbook_name,
        matched_on=[str(m) for m in run.matched_on or []],
        steps=[
            DryRunStep(id=str(s.get("id", "")), type=str(s.get("type", "step")), name=str(s.get("name", "")))
            for s in run.steps or []
            if isinstance(s, dict)
        ],
        created_at=run.created_at,
    )


@router.get(
    "",
    response_model=DryRunList,
    dependencies=[Depends(require_permission("alerts:read"))],
    summary="Playbooks that would have run (a dry run: nothing was run)",
)
async def list_dry_runs(
    user: AuthUser,
    db: DBSession,
    alert_id: Annotated[uuid.UUID | None, Query(description="Only this alert's dry runs.")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = DEFAULT_LIMIT,
) -> DryRunList:
    """The newest dry runs for this organization and its clients, or for one alert. Each says which playbook, why it matched and the steps it would have taken."""
    owner = user.tenant_id
    clients = {r.id: r.name for r in (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == owner))).all()}
    scope = [owner, *clients]
    names = {**clients}
    async with cross_tenant_reads(db):
        stmt = (
            select(PlaybookDryRun, Alert.title)
            .join(Alert, Alert.id == PlaybookDryRun.alert_id, isouter=True)
            .where(PlaybookDryRun.tenant_id.in_(scope))
            .order_by(PlaybookDryRun.created_at.desc())
            .limit(limit)
        )
        if alert_id is not None:
            stmt = stmt.where(PlaybookDryRun.alert_id == alert_id)
        rows = (await db.execute(stmt)).all()
    return DryRunList(items=[to_out(run, title, names.get(run.tenant_id)) for run, title in rows])

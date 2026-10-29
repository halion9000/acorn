"""What CORE can do to client Microsoft 365 tenants through CIPP, shown read only (backlog C38, C39).

CORE holds the rules (its saved settings): real actions are off unless a switch is on, only listed clients are opted in, some accounts are protected, there is an hourly cap, and every request, executed, dry run or
refused, is written to an audit file. ``POST /core-feed/{token}/cipp-actions`` is CORE's report of all that (no secret in it, ever); ``GET /cipp-actions`` shows it. Nothing here can change a rule or run an action.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.inbox_core_feed import _verify_core_feed_token
from app.db.rls_sessions import adopt_tenant
from app.models.cipp_actions_report import CippActionsReport
from app.models.client_alias import ClientAlias

router = APIRouter(prefix="/cipp-actions", tags=["cipp-actions"])
ingest_router = APIRouter(prefix="/inbox", tags=["cipp-actions"])

MAX_AUDIT = 100


class ActionInfo(BaseModel):
    action: str = Field(min_length=1, max_length=60)
    risk: Literal["low", "medium", "high"]
    reversible: bool
    summary: str = Field(max_length=300)


class AuditEntry(BaseModel):
    at: datetime
    action: str = Field(max_length=60)
    client_id: str = Field(max_length=80)
    user: str | None = Field(default=None, max_length=320)
    actor: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=300)
    result: Literal["executed", "dry_run", "refused", "failed"]
    code: str | None = Field(default=None, max_length=40)
    detail: str | None = Field(default=None, max_length=300)
    would_refuse: str | None = Field(default=None, max_length=40)


class ActionsReport(BaseModel):
    live: bool
    all_clients: bool
    clients: list[Annotated[str, Field(max_length=80)]] = Field(default_factory=list, max_length=500)
    protected_users: int = Field(ge=0, le=100_000)
    protected_domains: int = Field(ge=0, le=100_000)
    max_per_hour: int = Field(ge=1, le=100)
    actions: list[ActionInfo] = Field(max_length=30)
    audit: list[AuditEntry] = Field(default_factory=list, max_length=MAX_AUDIT)


class ReportResponse(BaseModel):
    stored: bool = True


class ActionsView(BaseModel):
    """What the Settings page shows. ``report`` is None until CORE has sent one."""

    report: ActionsReport | None
    received_at: datetime | None
    # CIPP customer id -> the client's name as CIPP knows it (from the client mapping), for the ids that are mapped.
    client_names: dict[str, str] = Field(default_factory=dict)


@ingest_router.post("/core-feed/{tenant_token}/cipp-actions", response_model=ReportResponse)
async def report_core_feed_cipp_actions(tenant_token: str, body: ActionsReport, db: DBSession) -> ReportResponse:
    """Keep CORE's latest report about its CIPP actions (replacing the one before)."""
    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    values = {"tenant_id": owner, "report": body.model_dump(mode="json")}
    stmt = pg_insert(CippActionsReport).values(values)
    await db.execute(
        stmt.on_conflict_do_update(index_elements=["tenant_id"], set_={"report": stmt.excluded.report, "received_at": func.now()})
    )
    await db.commit()
    return ReportResponse()


@router.get("", response_model=ActionsView, summary="What CORE can do through CIPP, its rules, and the last requests")
async def cipp_actions_view(user: Annotated[AuthUser, Depends(require_permission("connectors:read"))], db: DBSession) -> ActionsView:
    row = (await db.execute(select(CippActionsReport).where(CippActionsReport.tenant_id == user.tenant_id))).scalar_one_or_none()
    if row is None:
        return ActionsView(report=None, received_at=None)
    report = ActionsReport.model_validate(row.report)
    ids = {*report.clients, *(e.client_id for e in report.audit)}
    names: dict[str, str] = {}
    if ids:
        found = (
            await db.execute(
                select(ClientAlias.vendor_client_id, ClientAlias.vendor_client_name).where(
                    ClientAlias.tenant_id == user.tenant_id, ClientAlias.vendor == "cipp", ClientAlias.vendor_client_id.in_(ids)
                )
            )
        ).all()
        names = dict(found)
    return ActionsView(report=report, received_at=row.received_at, client_names=names)

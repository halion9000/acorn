"""Ticket metrics (the Rewst metric dashboards, rebuilt): created and resolved tickets, first response, tickets by type and by agent, and what is open, for all clients or one, from the HaloPSA summary CORE
sends about once a day. Read with ``metrics:view`` (``reports:read`` includes it)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.models.finance_profit import FinanceProfitSnapshot
from app.models.ticket_stats import CsatSnapshot, TicketStatsSnapshot
from app.services import ticket_metrics as tm

router = APIRouter(prefix="/reports/ticket-metrics", tags=["reports"])


@router.get("", dependencies=[Depends(require_permission("metrics:view"))])
async def ticket_metrics(
    user: AuthUser,
    db: DBSession,
    months: Annotated[int, Query(ge=1, le=36)] = 3,
    client_id: Annotated[str | None, Query(max_length=20)] = None,
) -> dict[str, Any]:
    """The summary for the newest ``months`` months (up to 36), for one HaloPSA client (``client_id``) or all. ``received_at`` is None until CORE has sent the first one."""
    row = (await db.execute(select(TicketStatsSnapshot).where(TicketStatsSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    if row is None:
        return {"received_at": None, "clients": [], "available_months": 0, "summary": None}
    profit = (await db.execute(select(FinanceProfitSnapshot).where(FinanceProfitSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    names = {str(a.get("id")): str(a.get("name") or "") for a in ((profit.payload if profit else {}).get("agents") or [])}
    return {
        "received_at": row.received_at,
        "clients": tm.clients_in(row.payload),
        "available_months": len(tm.months_in(row.payload)),
        "summary": tm.summarize(row.payload, months, client_id, names),
    }


@router.get("/csat", dependencies=[Depends(require_permission("metrics:view"))])
async def csat(
    user: AuthUser,
    db: DBSession,
    months: Annotated[int, Query(ge=1, le=12)] = 3,
    company: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    """Customer satisfaction from SimpleSat for the newest ``months`` months, for one company (by name) or all. ``received_at`` is None until CORE has sent the first summary."""
    row = (await db.execute(select(CsatSnapshot).where(CsatSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    if row is None:
        return {"received_at": None, "companies": [], "summary": None}
    companies = sorted({str(r.get("company") or "") for r in row.payload.get("rows") or []} - {""}, key=str.lower)
    return {"received_at": row.received_at, "companies": companies, "summary": tm.csat_for(row.payload, months, company)}


@router.get("/labor-hours", dependencies=[Depends(require_permission("metrics:view"))])
async def labor_hours(
    user: AuthUser,
    db: DBSession,
    months: Annotated[int, Query(ge=1, le=12)] = 3,
    client: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    """Hours worked on tickets for the newest ``months`` months, by month, engineer, client and ticket type, for one client (by name) or all. Hours only, no rates or money. ``received_at`` is None until CORE has sent the first HaloPSA summary."""
    row = (await db.execute(select(FinanceProfitSnapshot).where(FinanceProfitSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    if row is None:
        return {"received_at": None, "summary": None}
    return {"received_at": row.received_at, "summary": tm.labor_hours(row.payload, months, client)}

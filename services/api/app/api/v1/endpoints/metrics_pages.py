"""The pages of Metrics beyond tickets and satisfaction (Rewst's metric dashboards, rebuilt): Staff (Staff Metrics, Pods, Ticket Updates, DialPad, Staff Hours Distribution, Scorecard), Tickets (Ticket Resolution,
Ticket Volume Analysis, the open-ticket breakdown), Finance (Monthly Invoicing) and Customer Insights (Customer Experience, Monthly Licensing, User Roles).

Every page is worked out from what CORE sent (``metric_datasets``, the HaloPSA hours summary, the SimpleSat summary, the license counts), never from HaloPSA or Dialpad live. Reading needs ``metrics:view``.
``received_at`` is None until CORE has sent the dataset a page needs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.billing import _all_count_rows
from app.api.v1.endpoints.devices import _scope
from app.db.rls_scope import cross_tenant_reads
from app.models.finance_profit import FinanceProfitSnapshot
from app.models.metric_dataset import MetricDataset
from app.models.signin import ClientLicenseHistory
from app.models.tenant import Tenant
from app.models.ticket_stats import CsatSnapshot, TicketStatsSnapshot
from app.services import metrics_customers as mc
from app.services import metrics_staff as ms
from app.services import metrics_tickets as mt
from app.services.month_window import month_window

router = APIRouter(prefix="/reports/metrics", tags=["reports"], dependencies=[Depends(month_window)])

Months = Annotated[int, Query(ge=1, le=36)]


async def _dataset(db: DBSession, user: AuthUser, key: str) -> tuple[dict[str, Any] | None, datetime | None]:
    row = (
        await db.execute(select(MetricDataset).where(MetricDataset.tenant_id == user.tenant_id, MetricDataset.key == key))
    ).scalar_one_or_none()
    if row is None:
        return None, None
    # People marked excluded under Settings are left out of what the pages show (their tickets still count everywhere else).
    return ms.without_excluded(key, row.payload, await _excluded(db, user.tenant_id)), row.received_at


async def _excluded(db: DBSession, tenant_id: uuid.UUID) -> list[str]:
    tenant = await db.get(Tenant, tenant_id)
    names = ((tenant.settings if tenant else None) or {}).get("metrics", {}).get("excluded_engineers") or []
    return [str(n) for n in names if isinstance(n, str)]


class ExcludedIn(BaseModel):
    excluded: list[str] = Field(max_length=500)


@router.get("/excluded", dependencies=[Depends(require_permission("metrics:view"))])
async def get_excluded(user: AuthUser, db: DBSession) -> dict[str, Any]:
    """The engineers marked excluded from the metrics pages, and every engineer name CORE has sent (to choose from)."""
    row = (
        await db.execute(select(MetricDataset).where(MetricDataset.tenant_id == user.tenant_id, MetricDataset.key == "staff-weekly"))
    ).scalar_one_or_none()
    return {"excluded": await _excluded(db, user.tenant_id), "engineers": ms.engineers_of(row.payload if row else None)}


@router.put("/excluded", dependencies=[Depends(require_permission("mssp:manage"))])
async def put_excluded(body: ExcludedIn, user: AuthUser, db: DBSession) -> dict[str, Any]:
    """Replace the list of engineers left out of what the metrics pages show. Nothing is deleted: the tickets, hours and calls stay in the data and in every client total."""
    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    names = sorted({" ".join(n.split())[:120].lower(): " ".join(n.split())[:120] for n in body.excluded if n.strip()}.values(), key=str.lower)
    settings = dict(tenant.settings or {})
    metrics = dict(settings.get("metrics") or {})
    metrics["excluded_engineers"] = names
    settings["metrics"] = metrics
    tenant.settings = settings
    await db.commit()
    return {"excluded": names}


@router.get("/staff-metrics", dependencies=[Depends(require_permission("metrics:view"))])
async def staff_metrics(
    user: AuthUser, db: DBSession, months: Months = 3, team: Annotated[str | None, Query(max_length=120)] = None
) -> dict[str, Any]:
    """Utilization by week, tickets closed by week and utilization by team member, for all teams or one."""
    data, at = await _dataset(db, user, "staff-weekly")
    return {"received_at": at, **ms.staff_metrics(data, months, team)}


@router.get("/pods", dependencies=[Depends(require_permission("metrics:view"))])
async def pods(user: AuthUser, db: DBSession, months: Months = 3) -> dict[str, Any]:
    """Metrics by pod (a HaloPSA team): engineers, utilization, tickets resolved and created, days off and holidays."""
    data, at = await _dataset(db, user, "staff-weekly")
    return {"received_at": at, **ms.pods(data, months)}


@router.get("/weekly-comparison", dependencies=[Depends(require_permission("metrics:view"))])
async def weekly_comparison(user: AuthUser, db: DBSession, week: Annotated[str | None, Query(max_length=10, pattern=r"^\d{4}-\d{2}-\d{2}$")] = None) -> dict[str, Any]:
    """The Weekly Tech Comparison: per engineer for one week (the newest when none is asked for), days worked, new, opened and closed, older closed, net, per day, and Dialpad call tickets left out."""
    data, at = await _dataset(db, user, "staff-weekly")
    return {"received_at": at, **ms.weekly_comparison(data, week)}


@router.get("/ticket-updates", dependencies=[Depends(require_permission("metrics:view"))])
async def ticket_updates(
    user: AuthUser, db: DBSession, months: Months = 3, members: Annotated[list[str] | None, Query(max_length=200)] = None
) -> dict[str, Any]:
    """Ticket updates per team member per week, for the members chosen (all when none)."""
    data, at = await _dataset(db, user, "staff-weekly")
    return {"received_at": at, **ms.ticket_updates(data, months, members)}


@router.get("/dialpad", dependencies=[Depends(require_permission("metrics:view"))])
async def dialpad(
    user: AuthUser, db: DBSession, months: Months = 3, engineer: Annotated[str | None, Query(max_length=120)] = None
) -> dict[str, Any]:
    """Triage inbound calls and hours on call by week, and calls and hours per team member per week."""
    data, at = await _dataset(db, user, "dialpad-weekly")
    return {"received_at": at, **ms.dialpad(data, months, engineer)}


@router.get("/staff-hours", dependencies=[Depends(require_permission("metrics:view"))])
async def staff_hours(user: AuthUser, db: DBSession, months: Months = 3) -> dict[str, Any]:
    """Hours worked per person by ticket type, from the HaloPSA hours summary (hours only, no rates)."""
    row = (await db.execute(select(FinanceProfitSnapshot).where(FinanceProfitSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    return {"received_at": row.received_at if row else None, **ms.hours_distribution(row.payload if row else None, months)}


@router.get("/meetings", dependencies=[Depends(require_permission("metrics:view"))])
async def meetings(user: AuthUser, db: DBSession, months: Months = 3, team: Annotated[str | None, Query(max_length=120)] = None) -> dict[str, Any]:
    """Meeting hours per team member per week, by week and by team, from the calendars CORE reads through CIPP."""
    data, at = await _dataset(db, user, "meetings-weekly")
    return {"received_at": at, **ms.meetings(data, months, team)}


@router.get("/halo-user-roles", dependencies=[Depends(require_permission("metrics:view"))])
async def halo_user_roles(user: AuthUser, db: DBSession, client: Annotated[list[str] | None, Query(max_length=300)] = None) -> dict[str, Any]:
    """How many HaloPSA users each client has in each user role (Accountants, C-Suite, Computer User, Primary POC...)."""
    data, at = await _dataset(db, user, "halo-user-roles")
    return {"received_at": at, **ms.halo_user_roles(data, client)}


@router.get("/scorecard-template", dependencies=[Depends(require_permission("metrics:view"))])
async def scorecard_template() -> dict[str, Any]:
    """The weights, brackets and grade cut-offs the scorecard is worked out with (read only)."""
    return ms.scoring_template()


@router.get("/scorecard", dependencies=[Depends(require_permission("metrics:view"))])
async def scorecard(
    user: AuthUser, db: DBSession, months: Months = 2, member: Annotated[str | None, Query(max_length=120)] = None
) -> dict[str, Any]:
    """The Service Desk Scorecard: every team member's average week score and grade, and one member's weeks in detail."""
    data, at = await _dataset(db, user, "staff-weekly")
    return {"received_at": at, **ms.scorecard(data, months, member)}


@router.get("/ticket-resolution", dependencies=[Depends(require_permission("metrics:view"))])
async def ticket_resolution(user: AuthUser, db: DBSession, months: Months = 12) -> dict[str, Any]:
    """Resolved tickets per team member per month, and the average hours to resolve by client."""
    stats = (await db.execute(select(TicketStatsSnapshot).where(TicketStatsSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    # From the statistics CORE reads through the HaloPSA report call when it has sent them (counted as the Rewst dashboard counts, back to May 2023); otherwise from the older weekly facts.
    held = mt.resolution_from_report((stats.payload if stats else {}).get("resolution"), months)
    if held is not None:
        return {"received_at": stats.received_at, **held}
    detail, at = await _dataset(db, user, "ticket-detail")
    staff, _ = await _dataset(db, user, "staff-weekly")
    return {"received_at": at, "source": "weekly", **mt.ticket_resolution(detail, staff, months)}


@router.get("/ticket-volume", dependencies=[Depends(require_permission("metrics:view"))])
async def ticket_volume(
    user: AuthUser, db: DBSession, months: Months = 6, tech: Annotated[str | None, Query(max_length=120)] = None
) -> dict[str, Any]:
    """Tickets created by type, category, month and client; the priority mix of the last 60 days; stale tickets by tech."""
    detail, at = await _dataset(db, user, "ticket-detail")
    out = {"received_at": at, **mt.ticket_volume(detail, months, tech)}
    stats = (await db.execute(select(TicketStatsSnapshot).where(TicketStatsSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    held = mt.volume_from_stats(stats.payload if stats else None, months)
    if held is not None:  # the monthly counts CORE read through the report call: the same ones the Ticket Summary shows, for as many months as are held
        out = {**out, **held, "source": "report", "received_at": at or stats.received_at}  # type: ignore[union-attr]
    return out


@router.get("/open-tickets", dependencies=[Depends(require_permission("metrics:view"))])
async def open_tickets(user: AuthUser, db: DBSession, client_id: Annotated[str | None, Query(max_length=20)] = None) -> dict[str, Any]:
    """What is open now by status and priority, for all clients or one (by HaloPSA client id)."""
    detail, at = await _dataset(db, user, "ticket-detail")
    return {"received_at": at, **mt.open_breakdown(detail, client_id)}


@router.get("/monthly-invoicing", dependencies=[Depends(require_permission("metrics:view"))])
async def monthly_invoicing(user: AuthUser, db: DBSession, months: Months = 12) -> dict[str, Any]:
    """The monthly revenue trend, the total billed by billing category and each client's revenue by invoice line."""
    data, at = await _dataset(db, user, "invoice-lines")
    return {"received_at": at, **mt.monthly_invoicing(data, months)}


@router.get("/customer-experience", dependencies=[Depends(require_permission("metrics:view"))])
async def customer_experience(
    user: AuthUser,
    db: DBSession,
    months: Months = 12,
    sentiment: Annotated[str, Query(pattern="^(all|positive|neutral|negative)$")] = "all",
) -> dict[str, Any]:
    """Customer satisfaction by company, by team member and by month, and the newest written responses."""
    snap = (await db.execute(select(CsatSnapshot).where(CsatSnapshot.tenant_id == user.tenant_id))).scalar_one_or_none()
    staff, _ = await _dataset(db, user, "staff-weekly")
    return {
        "received_at": snap.received_at if snap else None,
        **mc.customer_experience(snap.payload if snap else None, staff, months, sentiment),
    }


@router.get("/user-roles", dependencies=[Depends(require_permission("metrics:view"))])
async def user_roles(user: AuthUser, db: DBSession) -> dict[str, Any]:
    """A client by Microsoft 365 directory role table: how many people hold each role, and who."""
    data, at = await _dataset(db, user, "m365-roles")
    return {"received_at": at, **mc.user_roles(data)}


@router.get("/licensing-apps", dependencies=[Depends(require_permission("metrics:view"))])
async def licensing_apps(user: AuthUser, db: DBSession, month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None) -> dict[str, Any]:
    """Which apps each client is billed for in a month (the Rewst Monthly Licensing page), from the invoice lines CORE sends."""
    data, at = await _dataset(db, user, "invoice-lines")
    return {"received_at": at, **mt.licensing_apps(data, month)}


@router.get("/monthly-licensing", dependencies=[Depends(require_permission("metrics:view"))])
async def monthly_licensing(
    user: AuthUser, db: DBSession, month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None
) -> dict[str, Any]:
    """A client by license-item table for a month: what is counted now for the current month, or as of the end of an earlier month from the history of counts."""
    now = datetime.now(UTC)
    chosen = month or f"{now.year}-{now.month:02d}"
    ids, names = await _scope(db, user.tenant_id, None)
    client_ids: list[uuid.UUID] = ids[1:]
    current = [
        {"client_id": str(r.tenant_id), "source": r.source, "item": r.item, "unit": r.unit, "count": r.count}
        for r in await _all_count_rows(db, client_ids)
    ]
    history: list[dict[str, Any]] = []
    if client_ids and mc.month_end(chosen) <= now:
        async with cross_tenant_reads(db):
            rows = (
                (
                    await db.execute(
                        select(ClientLicenseHistory).where(
                            ClientLicenseHistory.tenant_id.in_(client_ids), ClientLicenseHistory.observed_at < mc.month_end(chosen)
                        )
                    )
                )
                .scalars()
                .all()
            )
        history = [
            {"client_id": str(r.tenant_id), "source": r.source, "item": r.item, "count": r.count, "observed_at": r.observed_at}
            for r in rows
        ]
    return {"received_at": now, **mc.licensing_matrix(current, history, {str(k): v for k, v in names.items()}, chosen, now)}

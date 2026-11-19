"""The Compliance dashboard: which frameworks are on, how healthy their controls are, the risk levels and what needs doing.

``client_id`` reads or writes one of the caller's clients, as the other compliance routes do. Frameworks are switched on and off per organization or client; more than one can be on. Nothing is
invented: control health is worked out from the evidence held (see ``services/compliance_health.py``), risks come from the risk register and action items are expired evidence and open risk tasks.

Permission: ``reports:read`` to see, ``reports:write`` to switch frameworks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import FRAMEWORKS, ScopeTenant
from app.models.access_review import AccessReview
from app.models.compliance_enabled_framework import ComplianceEnabledFramework
from app.models.risk_register import RiskRegisterItem, RiskRegisterTask
from app.models.trust_audit import Audit, AuditRequest
from app.models.vendor_management import Vendor, VendorReview
from app.services import compliance_crosswalk, compliance_health, evidence_age, vendor_management
from app.services.audit import emit_audit
from app.services import risk_register
from app.services.risk_register import level

router = APIRouter(prefix="/compliance", tags=["compliance"])

MAX_ITEMS = 200


class EnabledOut(BaseModel):
    enabled: list[str]
    available: list[str]


class OverlapRow(BaseModel):
    framework: str
    name: str
    total_controls: int
    overlapping_controls: int
    unmapped_controls: int
    percent_overlapping: int
    shared_topics: list[str]
    new_topics: list[str]
    by_framework: dict[str, int]


class OverlapOut(BaseModel):
    enabled: list[str]
    candidates: list[OverlapRow]


class EnabledIn(BaseModel):
    frameworks: list[str] = Field(default_factory=list, max_length=20)


class Health(BaseModel):
    healthy: int
    at_risk: int
    unhealthy: int
    not_tested: int
    total: int
    percent_healthy: int | None


class FrameworkHealth(BaseModel):
    framework: str
    health: Health


class RiskLevels(BaseModel):
    critical: int
    high: int
    medium: int
    low: int
    total: int


class VendorLevels(BaseModel):
    critical: int
    high: int
    medium: int
    low: int
    unassessed: int
    total: int


class ActionItem(BaseModel):
    kind: Literal["evidence_expired", "risk_task", "vendor_review", "access_review", "audit_request", "vendor_contract", "risk_acceptance"]
    name: str
    event: str
    owner: str | None = None
    due: datetime | None = None
    link: str | None = None


class DashboardOut(BaseModel):
    enabled: list[str]
    health: Health | None
    by_framework: list[FrameworkHealth]
    risks: RiskLevels
    vendors: VendorLevels
    action_items: list[ActionItem]
    generated_at: datetime


def _health(counts: dict[str, int], total: int) -> Health:
    return Health(**counts, total=total, percent_healthy=compliance_health.percent_healthy(counts))


async def _enabled(db: Any, tenant: uuid.UUID) -> list[str]:
    rows = (
        (await db.execute(select(ComplianceEnabledFramework.framework).where(ComplianceEnabledFramework.tenant_id == tenant)))
        .scalars()
        .all()
    )
    return sorted(f for f in rows if f in FRAMEWORKS)


@router.get("/frameworks/enabled", response_model=EnabledOut, summary="The frameworks turned on for this organization or client")
async def enabled_frameworks(
    tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> EnabledOut:
    return EnabledOut(enabled=await _enabled(db, tenant), available=sorted(FRAMEWORKS))


@router.get(
    "/frameworks/overlap",
    response_model=OverlapOut,
    summary="For each framework that is off: how many of its controls the frameworks that are on already cover",
)
async def framework_overlap(
    tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> OverlapOut:
    """Read only. A planning aid from the topic crosswalk: adding a framework whose controls mostly sit on topics already covered costs little extra work."""
    on = await _enabled(db, tenant)
    return OverlapOut(enabled=on, candidates=[OverlapRow(**r) for r in compliance_crosswalk.overlap(on)])


@router.put(
    "/frameworks/enabled", response_model=EnabledOut, summary="Turn frameworks on or off (the list given is the whole set that is on)"
)
async def set_enabled_frameworks(
    body: EnabledIn,
    request: Request,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> EnabledOut:
    wanted = sorted(set(body.frameworks))
    unknown = [f for f in wanted if f not in FRAMEWORKS]
    if unknown:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Not a framework A.C.O.R.N has: {', '.join(unknown)}")
    before = await _enabled(db, tenant)
    await db.execute(
        delete(ComplianceEnabledFramework).where(
            ComplianceEnabledFramework.tenant_id == tenant, ComplianceEnabledFramework.framework.not_in(wanted) if wanted else True
        )
    )
    who = getattr(user, "email", None)
    if wanted:
        await db.execute(
            pg_insert(ComplianceEnabledFramework)
            .values([{"tenant_id": tenant, "framework": f, "enabled_by": who} for f in wanted])
            .on_conflict_do_nothing(index_elements=["tenant_id", "framework"])
        )
    if before != wanted:
        await emit_audit(
            db=db,
            tenant_id=tenant,
            actor_id=user.user_id,
            action="compliance:frameworks_changed",
            resource="compliance",
            resource_id=str(tenant),
            changes={"before": before, "after": wanted},
            request=request,
        )
    await db.commit()
    return EnabledOut(enabled=wanted, available=sorted(FRAMEWORKS))


@router.get(
    "/dashboard", response_model=DashboardOut, summary="Control health, risk levels and action items for the frameworks that are on"
)
async def dashboard(
    tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> DashboardOut:
    return await build_dashboard(db, tenant)


async def build_dashboard(db: Any, tenant: uuid.UUID) -> DashboardOut:
    """The dashboard for one organization or client (also what the weekly notice sends its action items from)."""
    now = datetime.now(UTC)
    enabled = await _enabled(db, tenant)
    by_framework: list[FrameworkHealth] = []
    action_items: list[ActionItem] = []
    totals = dict.fromkeys(compliance_health.STATES, 0)
    total_controls = 0
    if enabled:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT framework, control_id,
                           COUNT(*) FILTER (WHERE status = 'accepted') AS accepted,
                           COUNT(*) FILTER (WHERE status = 'pending')  AS pending,
                           COUNT(*) FILTER (WHERE status = 'rejected') AS rejected,
                           MAX(collected_at) FILTER (WHERE status = 'accepted') AS newest
                    FROM aisoc_compliance_evidence
                    WHERE tenant_id = :t AND framework = ANY(CAST(:fws AS TEXT[]))
                    GROUP BY framework, control_id
                    """
                ).bindparams(t=tenant, fws=enabled)
            )
        ).all()
        evidence: dict[str, dict[str, dict[str, Any]]] = {}
        for r in rows:
            evidence.setdefault(r.framework, {})[r.control_id] = {
                "accepted": r.accepted,
                "pending": r.pending,
                "rejected": r.rejected,
                "newest": r.newest,
            }
        for fw in enabled:
            known = FRAMEWORKS[fw]
            result = compliance_health.framework_health(known, evidence.get(fw, {}), now)
            by_framework.append(FrameworkHealth(framework=fw, health=_health(result["counts"], result["total"])))
            for state, n in result["counts"].items():
                totals[state] += n
            total_controls += result["total"]
            for control in result["expired"]:
                newest = evidence.get(fw, {}).get(control, {}).get("newest")
                action_items.append(
                    ActionItem(
                        kind="evidence_expired",
                        name=f"{fw} {control}: {known.get(control, '')}".strip(),
                        event="Evidence expired",
                        due=(newest + timedelta(days=evidence_age.MAX_AGE_DAYS)) if newest else None,
                        link=f"/compliance/{fw.lower().replace('-', '_')}",
                    )
                )
    risks = (
        (await db.execute(select(RiskRegisterItem).where(RiskRegisterItem.tenant_id == tenant, RiskRegisterItem.status != "archived")))
        .scalars()
        .all()
    )
    levels = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for r in risks:
        levels[level(r.likelihood * r.impact) or "low"] += 1
    refs = {r.id: r for r in risks}
    for r in risks:
        state = risk_register.acceptance_state(r.treatment, r.accepted_until, now.date())
        if state in ("expired", "expiring") and r.accepted_until is not None:
            action_items.append(
                ActionItem(
                    kind="risk_acceptance",
                    name=f"Risk R-{r.ref_no}: {r.title}",
                    event="Acceptance ended" if state == "expired" else "Acceptance ends soon",
                    owner=r.owner,
                    due=datetime(r.accepted_until.year, r.accepted_until.month, r.accepted_until.day, tzinfo=UTC),
                    link="/compliance/risk-register",
                )
            )
    tasks = (
        (
            await db.execute(
                select(RiskRegisterTask).where(
                    RiskRegisterTask.tenant_id == tenant, RiskRegisterTask.done.is_(False), RiskRegisterTask.due_date.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )
    today = now.date()
    for t in tasks:
        risk = refs.get(t.risk_id)
        if risk is None or t.due_date is None:
            continue
        action_items.append(
            ActionItem(
                kind="risk_task",
                name=f"Risk R-{risk.ref_no}: {t.title}",
                event="Task overdue" if t.due_date < today else "Task due",
                owner=t.owner,
                due=datetime(t.due_date.year, t.due_date.month, t.due_date.day, tzinfo=UTC),
                link="/compliance/risk-register",
            )
        )
    vendors = (await db.execute(select(Vendor).where(Vendor.tenant_id == tenant, Vendor.status != "archived"))).scalars().all()
    vendor_levels = dict.fromkeys(("critical", "high", "medium", "low", "unassessed"), 0)
    reviews_by_vendor: dict[uuid.UUID, list[VendorReview]] = {}
    for r in (await db.execute(select(VendorReview).where(VendorReview.tenant_id == tenant))).scalars():
        reviews_by_vendor.setdefault(r.vendor_id, []).append(r)
    for v in vendors:
        vendor_levels[v.risk_level if v.risk_level in vendor_levels else "unassessed"] += 1
        if v.contract_end is not None and v.contract_end <= today + timedelta(days=vendor_management.CONTRACT_NOTICE_DAYS):
            action_items.append(
                ActionItem(
                    kind="vendor_contract",
                    name=f"Vendor {v.name}: contract",
                    event="Contract ended" if v.contract_end < today else "Contract ends soon",
                    owner=v.owner,
                    due=datetime(v.contract_end.year, v.contract_end.month, v.contract_end.day, tzinfo=UTC),
                    link="/compliance/vendors",
                )
            )
        st = vendor_management.review_state(v.review_interval_months, reviews_by_vendor.get(v.id, []), v.created_at.date(), today)
        if st["state"] in ("overdue", "due") and st["next_due"] is not None:
            action_items.append(
                ActionItem(
                    kind="vendor_review",
                    name=f"Vendor {v.name}: security review",
                    event="Review overdue" if st["state"] == "overdue" else "Review due soon",
                    owner=v.owner,
                    due=datetime(st["next_due"].year, st["next_due"].month, st["next_due"].day, tzinfo=UTC),
                    link="/compliance/vendors",
                )
            )
    for rev in (
        await db.execute(
            select(AccessReview).where(AccessReview.tenant_id == tenant, AccessReview.status == "open", AccessReview.due_date.is_not(None))
        )
    ).scalars():
        assert rev.due_date is not None
        action_items.append(
            ActionItem(
                kind="access_review",
                name=f"Access review: {rev.name}",
                event="Review overdue" if rev.due_date < today else "Review due",
                owner=rev.reviewer,
                due=datetime(rev.due_date.year, rev.due_date.month, rev.due_date.day, tzinfo=UTC),
                link="/compliance/access-reviews",
            )
        )
    for req, audit in (
        await db.execute(
            select(AuditRequest, Audit)
            .join(Audit, Audit.id == AuditRequest.audit_id)
            .where(
                AuditRequest.tenant_id == tenant,
                AuditRequest.status == "open",
                AuditRequest.due_date.is_not(None),
                Audit.status != "complete",
            )
        )
    ).all():
        assert req.due_date is not None
        action_items.append(
            ActionItem(
                kind="audit_request",
                name=f"Audit {audit.name}: {req.title}",
                event="Request overdue" if req.due_date < today else "Request due",
                owner=req.owner,
                due=datetime(req.due_date.year, req.due_date.month, req.due_date.day, tzinfo=UTC),
                link="/compliance/audits",
            )
        )
    action_items.sort(key=lambda a: (a.due is None, a.due or now))
    return DashboardOut(
        enabled=enabled,
        health=_health(totals, total_controls) if enabled else None,
        by_framework=by_framework,
        risks=RiskLevels(**levels, total=len(risks)),
        vendors=VendorLevels(**vendor_levels, total=len(vendors)),
        action_items=action_items[:MAX_ITEMS],
        generated_at=now,
    )

"""The risk register of an organization or of one of its clients (Secureframe parity plan, step 1).

Each risk has a category, an owner, a likelihood and an impact (1 to 5 each, scored as their product) before treatment, a treatment decision and, once treated, the likelihood and impact that remain. Tasks
carry out the treatment. Every change is a line in the risk's history, and a risk is archived, never deleted. ``client_id`` reads or writes one of the caller's clients, exactly as the compliance pages do.

Permission: ``reports:read`` to see, ``reports:write`` to change.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import FRAMEWORKS, ScopeTenant
from app.models.risk_register import RiskRegisterHistory, RiskRegisterItem, RiskRegisterLevel, RiskRegisterLink, RiskRegisterTask
from app.models.vendor_management import Vendor
from app.services import risk_heatmap as hm
from app.services import csv_export
from app.services.audit import emit_audit
from app.services.risk_register import CATEGORIES, LIBRARY, TREATMENTS, acceptance_state, describe_changes, level, library_item, matrix, score

router = APIRouter(prefix="/risk-register", tags=["risk-register"])

Scale = Annotated[int, Field(ge=1, le=5)]
Treatment = Literal["mitigate", "accept", "transfer", "avoid", "undecided"]


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    owner: str | None
    due_date: date | None
    done: bool
    done_at: datetime | None
    overdue: bool


class RiskOut(BaseModel):
    id: uuid.UUID
    ref: str
    title: str
    description: str
    category: str
    owner: str | None
    likelihood: int
    impact: int
    inherent_score: int
    inherent_level: str
    treatment: str
    treatment_note: str
    residual_likelihood: int | None
    residual_impact: int | None
    residual_score: int | None
    residual_level: str | None
    accepted_until: date | None = None
    # none, current, expiring (within 30 days) or expired; only a risk whose treatment is accept can have one.
    acceptance_state: str = "none"
    status: str
    open_tasks: int
    updated_at: datetime
    archived_at: datetime | None


class HistoryOut(BaseModel):
    actor: str | None
    action: str
    detail: str
    created_at: datetime


class LinkOut(BaseModel):
    id: uuid.UUID
    kind: Literal["control", "vendor"]
    framework: str | None  # for a control
    ref: str  # the control id, or the vendor id
    label: str  # the control title or the vendor name; empty when what it pointed at is gone


class LinkIn(BaseModel):
    kind: Literal["control", "vendor"]
    framework: str | None = Field(default=None, max_length=20)
    ref: str = Field(min_length=1, max_length=80)


class RiskDetail(RiskOut):
    tasks: list[TaskOut]
    history: list[HistoryOut]
    links: list[LinkOut] = []


class Summary(BaseModel):
    total: int
    by_level: dict[str, int]
    # Rows are likelihood 5 down to 1, columns impact 1 up to 5: how many active risks sit in each cell, by inherent rating.
    matrix: list[list[int]]
    open_tasks: int
    overdue_tasks: int
    untreated: int
    acceptance_expiring: int = 0
    acceptance_expired: int = 0


class RegisterOut(BaseModel):
    risks: list[RiskOut]
    summary: Summary
    categories: list[str]


class RiskIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    description: str = Field(default="", max_length=4000)
    category: str = Field(default="Other", max_length=60)
    owner: str | None = Field(default=None, max_length=200)
    likelihood: Scale
    impact: Scale
    treatment: Treatment = "undecided"
    treatment_note: str = Field(default="", max_length=4000)
    residual_likelihood: Scale | None = None
    residual_impact: Scale | None = None
    accepted_until: date | None = None

    @model_validator(mode="after")
    def _expiry_needs_acceptance(self) -> "RiskIn":
        if self.accepted_until is not None and self.treatment != "accept":
            raise ValueError("An end date for the acceptance only applies to a risk whose treatment is accept.")
        return self


class RiskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=60)
    owner: str | None = Field(default=None, max_length=200)
    likelihood: Scale | None = None
    impact: Scale | None = None
    treatment: Treatment | None = None
    treatment_note: str | None = Field(default=None, max_length=4000)
    residual_likelihood: Scale | None = None
    residual_impact: Scale | None = None
    accepted_until: date | None = None
    clear_accepted_until: bool = False
    clear_residual: bool = False


class TaskIn(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    owner: str | None = Field(default=None, max_length=200)
    due_date: date | None = None


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=300)
    owner: str | None = Field(default=None, max_length=200)
    due_date: date | None = None
    done: bool | None = None


class LibraryItem(BaseModel):
    id: str
    title: str
    category: str
    likelihood: int
    impact: int
    description: str
    added: bool


class LibraryPick(BaseModel):
    library_id: str = Field(min_length=1, max_length=60)


def _risk(row: RiskRegisterItem, open_tasks: int = 0) -> RiskOut:
    inherent = score(row.likelihood, row.impact) or 0
    residual = score(row.residual_likelihood, row.residual_impact)
    return RiskOut(
        id=row.id,
        ref=f"R-{row.ref_no}",
        title=row.title,
        description=row.description,
        category=row.category,
        owner=row.owner,
        likelihood=row.likelihood,
        impact=row.impact,
        inherent_score=inherent,
        inherent_level=level(inherent) or "low",
        treatment=row.treatment,
        treatment_note=row.treatment_note,
        residual_likelihood=row.residual_likelihood,
        residual_impact=row.residual_impact,
        residual_score=residual,
        residual_level=level(residual),
        accepted_until=row.accepted_until,
        acceptance_state=acceptance_state(row.treatment, row.accepted_until, datetime.now(UTC).date()),
        status=row.status,
        open_tasks=open_tasks,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
    )


def _task(row: RiskRegisterTask, today: date) -> TaskOut:
    return TaskOut(
        id=row.id,
        title=row.title,
        owner=row.owner,
        due_date=row.due_date,
        done=row.done,
        done_at=row.done_at,
        overdue=bool(row.due_date and not row.done and row.due_date < today),
    )


def _snapshot(row: RiskRegisterItem) -> dict[str, Any]:
    return {
        k: getattr(row, k)
        for k in (
            "title",
            "description",
            "category",
            "owner",
            "likelihood",
            "impact",
            "treatment",
            "treatment_note",
            "residual_likelihood",
            "residual_impact",
            "accepted_until",
        )
    }


def _actor(user: Any) -> str | None:
    return getattr(user, "email", None)


async def _note(db: Any, tenant: uuid.UUID, risk_id: uuid.UUID, user: Any, action: str, detail: str = "") -> None:
    db.add(RiskRegisterHistory(id=uuid.uuid4(), tenant_id=tenant, risk_id=risk_id, actor=_actor(user), action=action, detail=detail[:2000]))


async def _levels(db: Any, tenant: uuid.UUID, row: RiskRegisterItem, at: datetime, active: bool = True) -> None:
    """Keep the levels the risk has from ``at`` on, for the heat map over time."""
    db.add(
        RiskRegisterLevel(
            id=uuid.uuid4(),
            tenant_id=tenant,
            risk_id=row.id,
            at=at,
            likelihood=row.likelihood,
            impact=row.impact,
            residual_likelihood=row.residual_likelihood,
            residual_impact=row.residual_impact,
            active=active,
        )
    )


async def _next_ref(db: Any, tenant: uuid.UUID) -> int:
    # One writer at a time per organization, so two people adding a risk at once do not get the same number.
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"risk-register:{tenant}"))))
    return int(
        (
            await db.execute(select(func.coalesce(func.max(RiskRegisterItem.ref_no), 0) + 1).where(RiskRegisterItem.tenant_id == tenant))
        ).scalar_one()
    )


async def _get(db: Any, tenant: uuid.UUID, risk_id: uuid.UUID) -> RiskRegisterItem:
    row = (
        await db.execute(select(RiskRegisterItem).where(RiskRegisterItem.id == risk_id, RiskRegisterItem.tenant_id == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Risk not found")
    return row


async def _audit(
    db: Any, tenant: uuid.UUID, user: AuthUser, request: Request, action: str, risk: RiskRegisterItem, changes: dict[str, Any] | None = None
) -> None:
    await emit_audit(
        db=db,
        tenant_id=tenant,
        actor_id=user.user_id,
        action=f"risk_register:{action}",
        resource="risk",
        resource_id=str(risk.id),
        changes={"ref": f"R-{risk.ref_no}", "title": risk.title, **(changes or {})},
        request=request,
    )


@router.get("", response_model=RegisterOut, summary="The risks of this organization or client, with the dashboard figures")
async def list_risks(
    tenant: ScopeTenant,
    db: DBSession,
    _user: Annotated[AuthUser, Depends(require_permission("reports:read"))],
    archived: bool = Query(False, description="True lists the archived risks instead of the active ones."),
) -> RegisterOut:
    today = datetime.now(UTC).date()
    rows = (
        (
            await db.execute(
                select(RiskRegisterItem)
                .where(
                    RiskRegisterItem.tenant_id == tenant,
                    (RiskRegisterItem.status == "archived") if archived else (RiskRegisterItem.status != "archived"),
                )
                .order_by(RiskRegisterItem.ref_no)
            )
        )
        .scalars()
        .all()
    )
    tasks = (
        (await db.execute(select(RiskRegisterTask).where(RiskRegisterTask.tenant_id == tenant, RiskRegisterTask.done.is_(False))))
        .scalars()
        .all()
    )
    open_by_risk: dict[uuid.UUID, int] = {}
    for t in tasks:
        open_by_risk[t.risk_id] = open_by_risk.get(t.risk_id, 0) + 1
    out = [_risk(r, open_by_risk.get(r.id, 0)) for r in rows]
    by_level = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for r in out:
        by_level[r.inherent_level] += 1
    active_ids = {r.id for r in rows}
    return RegisterOut(
        risks=out,
        summary=Summary(
            total=len(out),
            by_level=by_level,
            matrix=matrix(rows),
            open_tasks=sum(1 for t in tasks if t.risk_id in active_ids),
            overdue_tasks=sum(1 for t in tasks if t.risk_id in active_ids and t.due_date and t.due_date < today),
            untreated=sum(1 for r in rows if r.treatment == "undecided"),
            acceptance_expiring=sum(1 for r in out if r.acceptance_state == "expiring"),
            acceptance_expired=sum(1 for r in out if r.acceptance_state == "expired"),
        ),
        categories=list(CATEGORIES),
    )


# The day the register began keeping each risk's levels as they changed; a risk older than this is shown at the levels it had then, whatever they were before.
LEVELS_RECORDED_FROM = date(2026, 11, 18)


class HeatCell(BaseModel):
    likelihood: int
    impact: int
    count: int
    level: str | None
    titles: list[str]  # the risks in the cell (up to a few), so a person can see what they are


class HeatMap(BaseModel):
    as_of: date
    kind: Literal["inherent", "residual"]
    total: int
    by_level: dict[str, int]
    cells: list[HeatCell]
    trend: list[dict[str, Any]]  # for each of the last twelve month ends and today: the total and the count at each level
    approximate_before: date | None  # levels before this day were not recorded as they changed, so the map for an earlier date is approximate


async def _level_rows(db: Any, tenant: uuid.UUID) -> list[hm.Levels]:
    rows = (await db.execute(select(RiskRegisterLevel).where(RiskRegisterLevel.tenant_id == tenant))).scalars().all()
    return [hm.Levels(r.risk_id, r.at, r.likelihood, r.impact, r.residual_likelihood, r.residual_impact, r.active) for r in rows]


@router.get("/heatmap", response_model=HeatMap, summary="The risk heat map for a date (today unless asked), before or after treatment, and how the levels moved month by month")
async def heat_map(
    tenant: ScopeTenant,
    db: DBSession,
    _user: Annotated[AuthUser, Depends(require_permission("reports:read"))],
    as_of: date | None = Query(default=None),
    kind: Literal["inherent", "residual"] = Query(default="inherent"),
) -> HeatMap:
    today = datetime.now(UTC).date()
    day = min(as_of or today, today)
    rows = await _level_rows(db, tenant)
    titles = {r.id: r.title for r in (await db.execute(select(RiskRegisterItem).where(RiskRegisterItem.tenant_id == tenant))).scalars().all()}
    h = hm.heatmap(rows, hm.end_of_day(day), kind)
    return HeatMap(
        as_of=day,
        kind=kind,
        total=h["total"],
        by_level=h["by_level"],
        cells=[HeatCell(likelihood=c["likelihood"], impact=c["impact"], count=c["count"], level=c["level"], titles=[titles.get(i, "") for i in c["risk_ids"]][:6]) for c in h["cells"]],
        trend=hm.monthly(rows, today, kind),
        approximate_before=LEVELS_RECORDED_FROM,
    )


@router.get("/library", response_model=list[LibraryItem], summary="Common risks to start from")
async def library(
    tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> list[LibraryItem]:
    have = {t for (t,) in (await db.execute(select(RiskRegisterItem.title).where(RiskRegisterItem.tenant_id == tenant))).all()}
    return [
        LibraryItem(**{k: i[k] for k in ("id", "title", "category", "likelihood", "impact", "description")}, added=i["title"] in have)
        for i in LIBRARY
    ]


@router.post("", response_model=RiskDetail, status_code=status.HTTP_201_CREATED, summary="Add a risk")
async def create_risk(
    body: RiskIn,
    request: Request,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> RiskDetail:
    return await _create(db, tenant, user, request, body.model_dump())


async def _create(db: Any, tenant: uuid.UUID, user: AuthUser, request: Request, data: dict[str, Any], source: str = "added") -> RiskDetail:
    if data.get("category") not in CATEGORIES:
        data["category"] = "Other"
    if (data.get("residual_likelihood") is None) != (data.get("residual_impact") is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Give both the residual likelihood and the residual impact, or neither.",
        )
    now = datetime.now(UTC)
    row = RiskRegisterItem(
        id=uuid.uuid4(),
        tenant_id=tenant,
        ref_no=await _next_ref(db, tenant),
        created_by=_actor(user),
        created_at=now,
        updated_at=now,
        **data,
    )
    if row.residual_likelihood is not None:
        row.status = "assessed"
    db.add(row)
    await db.flush()
    await _levels(db, tenant, row, now)
    await _note(db, tenant, row.id, user, "created", f"{source}; inherent {score(row.likelihood, row.impact)}")
    await _audit(db, tenant, user, request, "created", row)
    await db.commit()
    return await _detail(db, tenant, row.id)


@router.post("/from-library", response_model=RiskDetail, status_code=status.HTTP_201_CREATED, summary="Add a risk from the starter library")
async def from_library(
    body: LibraryPick,
    request: Request,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> RiskDetail:
    item = library_item(body.library_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such library risk")
    exists = (
        await db.execute(select(RiskRegisterItem.id).where(RiskRegisterItem.tenant_id == tenant, RiskRegisterItem.title == item["title"]))
    ).first()
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This risk is already in the register.")
    data = {k: item[k] for k in ("title", "description", "category", "likelihood", "impact")}
    return await _create(db, tenant, user, request, data, source="from the library")


def link_out(k: RiskRegisterLink, vendor_names: dict[Any, str]) -> LinkOut:
    """One link as shown: a control carries its title from the catalog, a vendor its name (pure)."""
    if k.kind == "control":
        label = FRAMEWORKS.get(k.framework or "", {}).get(k.ref, "")
    else:
        try:
            label = vendor_names.get(uuid.UUID(k.ref), "")
        except ValueError:
            label = ""
    return LinkOut(id=k.id, kind=k.kind, framework=k.framework, ref=k.ref, label=label)


async def _detail(db: Any, tenant: uuid.UUID, risk_id: uuid.UUID) -> RiskDetail:
    row = await _get(db, tenant, risk_id)
    today = datetime.now(UTC).date()
    tasks = (
        (
            await db.execute(
                select(RiskRegisterTask)
                .where(RiskRegisterTask.risk_id == risk_id, RiskRegisterTask.tenant_id == tenant)
                .order_by(RiskRegisterTask.created_at)
            )
        )
        .scalars()
        .all()
    )
    history = (
        (
            await db.execute(
                select(RiskRegisterHistory)
                .where(RiskRegisterHistory.risk_id == risk_id, RiskRegisterHistory.tenant_id == tenant)
                .order_by(RiskRegisterHistory.created_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    base = _risk(row, sum(1 for t in tasks if not t.done))
    links = (
        (await db.execute(select(RiskRegisterLink).where(RiskRegisterLink.risk_id == risk_id, RiskRegisterLink.tenant_id == tenant).order_by(RiskRegisterLink.created_at)))
        .scalars()
        .all()
    )
    names = {v.id: v.name for v in (await db.execute(select(Vendor).where(Vendor.tenant_id == tenant))).scalars().all()} if any(k.kind == "vendor" for k in links) else {}
    return RiskDetail(
        **base.model_dump(),
        links=[link_out(k, names) for k in links],
        tasks=[_task(t, today) for t in tasks],
        history=[HistoryOut(actor=h.actor, action=h.action, detail=h.detail, created_at=h.created_at) for h in history],
    )


@router.get("/export.csv", summary="The risks as a CSV file")
async def export_risks(
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:read"))],
    archived: bool = Query(False),
) -> Response:
    out = await list_risks(tenant, db, user, archived)
    return csv_export.response(
        "risks.csv",
        [
            "Ref",
            "Risk",
            "Category",
            "Owner",
            "Likelihood",
            "Impact",
            "Score before",
            "Level before",
            "Treatment",
            "Residual score",
            "Residual level",
            "Status",
            "Open tasks",
            "Updated",
        ],
        [
            [
                r.ref,
                r.title,
                r.category,
                r.owner,
                r.likelihood,
                r.impact,
                r.inherent_score,
                r.inherent_level,
                r.treatment,
                r.residual_score,
                r.residual_level,
                r.status,
                r.open_tasks,
                r.updated_at,
            ]
            for r in out.risks
        ],
    )


@router.get("/{risk_id}", response_model=RiskDetail, summary="One risk with its tasks and history")
async def get_risk(
    risk_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> RiskDetail:
    return await _detail(db, tenant, risk_id)


@router.patch("/{risk_id}", response_model=RiskDetail, summary="Change a risk")
async def update_risk(
    risk_id: uuid.UUID,
    body: RiskPatch,
    request: Request,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> RiskDetail:
    row = await _get(db, tenant, risk_id)
    if row.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An archived risk cannot be changed. Restore it first.")
    before = _snapshot(row)
    changes = body.model_dump(exclude_unset=True, exclude={"clear_residual", "clear_accepted_until"})
    if "category" in changes and changes["category"] not in CATEGORIES:
        changes["category"] = "Other"
    for key, value in changes.items():
        if value is None and key in ("title", "likelihood", "impact", "treatment"):
            continue
        setattr(row, key, value)
    if body.clear_residual:
        row.residual_likelihood = None
        row.residual_impact = None
    if body.clear_accepted_until or row.treatment != "accept":
        # An end date belongs to an acceptance: it goes when the treatment is no longer accept.
        row.accepted_until = None
    if (row.residual_likelihood is None) != (row.residual_impact is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Give both the residual likelihood and the residual impact, or neither.",
        )
    row.status = "assessed" if row.residual_likelihood is not None else "open"
    row.updated_at = datetime.now(UTC)
    lines = describe_changes(before, _snapshot(row))
    if any(before[k] != getattr(row, k) for k in ("likelihood", "impact", "residual_likelihood", "residual_impact")):
        await _levels(db, tenant, row, row.updated_at)
    if lines:
        await _note(db, tenant, row.id, user, "changed", "; ".join(lines))
        await _audit(db, tenant, user, request, "changed", row, {"changes": lines})
    await db.commit()
    return await _detail(db, tenant, risk_id)


@router.post("/{risk_id}/archive", response_model=RiskDetail, summary="Archive a risk (it stays in the history and can be restored)")
async def archive_risk(
    risk_id: uuid.UUID,
    request: Request,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> RiskDetail:
    row = await _get(db, tenant, risk_id)
    if row.status != "archived":
        row.status = "archived"
        row.archived_at = datetime.now(UTC)
        row.updated_at = row.archived_at
        await _levels(db, tenant, row, row.archived_at, active=False)
        await _note(db, tenant, row.id, user, "archived")
        await _audit(db, tenant, user, request, "archived", row)
        await db.commit()
    return await _detail(db, tenant, risk_id)


@router.post("/{risk_id}/restore", response_model=RiskDetail, summary="Bring an archived risk back")
async def restore_risk(
    risk_id: uuid.UUID,
    request: Request,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> RiskDetail:
    row = await _get(db, tenant, risk_id)
    if row.status == "archived":
        row.status = "assessed" if row.residual_likelihood is not None else "open"
        row.archived_at = None
        row.updated_at = datetime.now(UTC)
        await _levels(db, tenant, row, row.updated_at)
        await _note(db, tenant, row.id, user, "restored")
        await _audit(db, tenant, user, request, "restored", row)
        await db.commit()
    return await _detail(db, tenant, risk_id)


@router.post("/{risk_id}/tasks", response_model=RiskDetail, status_code=status.HTTP_201_CREATED, summary="Add a task that treats this risk")
async def add_task(
    risk_id: uuid.UUID,
    body: TaskIn,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> RiskDetail:
    row = await _get(db, tenant, risk_id)
    if row.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An archived risk cannot take new tasks. Restore it first.")
    db.add(
        RiskRegisterTask(
            id=uuid.uuid4(), tenant_id=tenant, risk_id=risk_id, title=body.title.strip(), owner=body.owner, due_date=body.due_date
        )
    )
    await _note(db, tenant, risk_id, user, "task_added", body.title.strip())
    await db.commit()
    return await _detail(db, tenant, risk_id)


@router.post("/{risk_id}/links", response_model=RiskDetail, status_code=status.HTTP_201_CREATED, summary="Link this risk to a control or a vendor it concerns")
async def add_link(
    risk_id: uuid.UUID,
    body: LinkIn,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> RiskDetail:
    row = await _get(db, tenant, risk_id)
    if row.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An archived risk cannot take new links. Restore it first.")
    ref, framework = body.ref.strip(), None
    if body.kind == "control":
        framework = body.framework or ""
        if ref not in FRAMEWORKS.get(framework, {}):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That control is not in the list for that framework.")
        label = FRAMEWORKS[framework][ref]
    else:
        try:
            vendor_id = uuid.UUID(ref)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That is not a vendor.") from None
        vendor = (await db.execute(select(Vendor).where(Vendor.id == vendor_id, Vendor.tenant_id == tenant))).scalar_one_or_none()
        if vendor is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That vendor is not in this client vendor list.")
        ref, label = str(vendor.id), vendor.name
    taken = (
        await db.execute(
            select(RiskRegisterLink.id).where(
                RiskRegisterLink.risk_id == risk_id,
                RiskRegisterLink.kind == body.kind,
                func.coalesce(RiskRegisterLink.framework, "") == (framework or ""),
                RiskRegisterLink.ref == ref,
            )
        )
    ).first()
    if taken is None:
        db.add(RiskRegisterLink(id=uuid.uuid4(), tenant_id=tenant, risk_id=risk_id, kind=body.kind, framework=framework, ref=ref))
        await _note(db, tenant, risk_id, user, "link_added", f"{body.kind}: {(framework + ' ') if framework else ''}{label or ref}")
        await db.commit()
    return await _detail(db, tenant, risk_id)


@router.delete("/{risk_id}/links/{link_id}", response_model=RiskDetail, summary="Remove a link from this risk")
async def remove_link(
    risk_id: uuid.UUID,
    link_id: uuid.UUID,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> RiskDetail:
    await _get(db, tenant, risk_id)
    link = (
        await db.execute(select(RiskRegisterLink).where(RiskRegisterLink.id == link_id, RiskRegisterLink.risk_id == risk_id, RiskRegisterLink.tenant_id == tenant))
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such link.")
    await db.delete(link)
    await _note(db, tenant, risk_id, user, "link_removed", f"{link.kind}: {link.ref}")
    await db.commit()
    return await _detail(db, tenant, risk_id)


@router.patch("/{risk_id}/tasks/{task_id}", response_model=RiskDetail, summary="Change or finish a task")
async def update_task(
    risk_id: uuid.UUID,
    task_id: uuid.UUID,
    body: TaskPatch,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> RiskDetail:
    await _get(db, tenant, risk_id)
    task = (
        await db.execute(
            select(RiskRegisterTask).where(
                RiskRegisterTask.id == task_id, RiskRegisterTask.risk_id == risk_id, RiskRegisterTask.tenant_id == tenant
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    data = body.model_dump(exclude_unset=True)
    if "title" in data and data["title"]:
        task.title = data["title"].strip()
    if "owner" in data:
        task.owner = data["owner"]
    if "due_date" in data:
        task.due_date = data["due_date"]
    if "done" in data and data["done"] is not None and data["done"] != task.done:
        task.done = data["done"]
        task.done_at = datetime.now(UTC) if task.done else None
        await _note(db, tenant, risk_id, user, "task_done" if task.done else "task_reopened", task.title)
    await db.commit()
    return await _detail(db, tenant, risk_id)


@router.delete("/{risk_id}/tasks/{task_id}", response_model=RiskDetail, summary="Remove a task")
async def delete_task(
    risk_id: uuid.UUID,
    task_id: uuid.UUID,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> RiskDetail:
    await _get(db, tenant, risk_id)
    task = (
        await db.execute(
            select(RiskRegisterTask).where(
                RiskRegisterTask.id == task_id, RiskRegisterTask.risk_id == risk_id, RiskRegisterTask.tenant_id == tenant
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    await _note(db, tenant, risk_id, user, "task_removed", task.title)
    await db.delete(task)
    await db.commit()
    return await _detail(db, tenant, risk_id)


# TREATMENTS is part of the contract the page offers; kept importable from here.
__all__ = ["TREATMENTS", "router"]

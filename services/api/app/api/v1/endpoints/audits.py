"""Audits (Secureframe parity plan): an audit of a framework and the evidence requests that come with it.

An audit has a framework, the auditor's firm, the period it covers and where it stands (planning, fieldwork, review, complete). Its requests are what the auditor asks for: a title, optionally the control it is about,
an owner, a due date, and where it stands (open, provided with a note and a link, accepted). "Add requests for the controls that need evidence" makes one request for each control of the framework that is unhealthy
or not tested and has none yet. An audit cannot be completed while any request is still open. A sign-in for the auditor is not built: the auditor's answers are recorded by the person working with them.
Read with ``reports:read``, change with ``reports:write``; ``client_id`` reads or writes one of the caller's clients.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import FRAMEWORKS, ScopeTenant
from app.api.v1.endpoints.compliance_controls import build_rows, evidence_by_control
from app.models.trust_audit import Audit, AuditRequest
from app.services import compliance_audit as audit

router = APIRouter(prefix="/compliance/audits", tags=["compliance"])

AuditStatus = Literal["planning", "fieldwork", "review", "complete"]
RequestStatus = Literal["open", "provided", "accepted"]
MAX_FROM_CONTROLS = 150


class AuditIn(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    framework: str = Field(min_length=1, max_length=20)
    auditor: str | None = Field(default=None, max_length=200)
    period_start: date | None = None
    period_end: date | None = None


class AuditPatch(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=200)
    auditor: str | None = Field(default=None, max_length=200)
    period_start: date | None = None
    period_end: date | None = None
    status: AuditStatus | None = None


class RequestIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    control_id: str | None = Field(default=None, max_length=60)
    owner: str | None = Field(default=None, max_length=200)
    due_date: date | None = None


class RequestPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    owner: str | None = Field(default=None, max_length=200)
    due_date: date | None = None
    status: RequestStatus | None = None
    note: str | None = Field(default=None, max_length=4000)
    link: str | None = Field(default=None, max_length=1000)


class RequestOut(BaseModel):
    id: uuid.UUID
    title: str
    control_id: str | None
    owner: str | None
    due_date: date | None
    status: str
    overdue: bool
    note: str
    link: str | None
    updated_at: datetime


class AuditOut(BaseModel):
    id: uuid.UUID
    name: str
    framework: str
    auditor: str | None
    period_start: date | None
    period_end: date | None
    status: str
    requests: int
    open: int
    provided: int
    accepted: int
    overdue: int
    created_at: datetime


class AuditDetail(AuditOut):
    items: list[RequestOut]


class AuditList(BaseModel):
    audits: list[AuditOut]
    frameworks: list[str]


def _summary(a: Audit, reqs: list[AuditRequest], today: date) -> AuditOut:
    by = [r.status for r in reqs]
    return AuditOut(
        id=a.id,
        name=a.name,
        framework=a.framework,
        auditor=a.auditor,
        period_start=a.period_start,
        period_end=a.period_end,
        status=a.status,
        requests=len(reqs),
        open=by.count("open"),
        provided=by.count("provided"),
        accepted=by.count("accepted"),
        overdue=sum(1 for r in reqs if r.status == "open" and r.due_date is not None and r.due_date < today),
        created_at=a.created_at,
    )


def _req_out(r: AuditRequest, today: date) -> RequestOut:
    return RequestOut(
        id=r.id,
        title=r.title,
        control_id=r.control_id,
        owner=r.owner,
        due_date=r.due_date,
        status=r.status,
        overdue=r.status == "open" and r.due_date is not None and r.due_date < today,
        note=r.note,
        link=r.link,
        updated_at=r.updated_at,
    )


def check_link(link: str | None) -> str | None:
    """A link to what was provided: https or http, or nothing (pure). Anything else raises ValueError."""
    value = (link or "").strip()
    if not value:
        return None
    if not value.lower().startswith(("https://", "http://")):
        raise ValueError("The link must start with https:// (or http://).")
    return value


async def _audit(db: DBSession, tenant: uuid.UUID, audit_id: uuid.UUID) -> Audit:
    row = (await db.execute(select(Audit).where(Audit.id == audit_id, Audit.tenant_id == tenant))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")
    return row


async def _requests(db: DBSession, tenant: uuid.UUID, audit_id: uuid.UUID) -> list[AuditRequest]:
    rows = (
        (await db.execute(select(AuditRequest).where(AuditRequest.audit_id == audit_id, AuditRequest.tenant_id == tenant))).scalars().all()
    )
    order = {"open": 0, "provided": 1, "accepted": 2}
    return sorted(rows, key=lambda r: (order[r.status], r.due_date or date.max, r.title.lower()))


async def _detail(db: DBSession, tenant: uuid.UUID, a: Audit) -> AuditDetail:
    reqs = await _requests(db, tenant, a.id)
    today = datetime.now(UTC).date()
    return AuditDetail(**_summary(a, reqs, today).model_dump(), items=[_req_out(r, today) for r in reqs])


@router.get("", response_model=AuditList, summary="The audits, newest first")
async def list_audits(
    tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> AuditList:
    audits = (await db.execute(select(Audit).where(Audit.tenant_id == tenant).order_by(Audit.created_at.desc()))).scalars().all()
    by: dict[uuid.UUID, list[AuditRequest]] = {}
    for r in (await db.execute(select(AuditRequest).where(AuditRequest.tenant_id == tenant))).scalars():
        by.setdefault(r.audit_id, []).append(r)
    today = datetime.now(UTC).date()
    return AuditList(audits=[_summary(a, by.get(a.id, []), today) for a in audits], frameworks=sorted(FRAMEWORKS))


@router.post("", response_model=AuditDetail, status_code=status.HTTP_201_CREATED, summary="Start an audit")
async def start_audit(
    body: AuditIn, tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> AuditDetail:
    if body.framework not in FRAMEWORKS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{body.framework} is not a framework.")
    if body.period_start and body.period_end and body.period_end < body.period_start:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The period ends before it starts.")
    a = Audit(
        id=uuid.uuid4(),
        tenant_id=tenant,
        name=body.name.strip(),
        framework=body.framework,
        auditor=body.auditor,
        period_start=body.period_start,
        period_end=body.period_end,
        created_by=getattr(user, "email", None),
    )
    db.add(a)
    await audit.note(db, tenant, user, "audit:started", "audit", a.id, name=a.name, framework=a.framework)
    await db.commit()
    return await _detail(db, tenant, a)


@router.get("/{audit_id}", response_model=AuditDetail, summary="One audit with its requests")
async def get_audit(
    audit_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> AuditDetail:
    return await _detail(db, tenant, await _audit(db, tenant, audit_id))


@router.patch("/{audit_id}", response_model=AuditDetail, summary="Change an audit, or move it to its next stage")
async def patch_audit(
    audit_id: uuid.UUID,
    body: AuditPatch,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> AuditDetail:
    a = await _audit(db, tenant, audit_id)
    if a.status == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That audit is complete and cannot be changed.")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("status") == "complete":
        open_ones = sum(1 for r in await _requests(db, tenant, audit_id) if r.status == "open")
        if open_ones:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=f"{open_ones} request{' is' if open_ones == 1 else 's are'} still open."
            )
    for k, v in changes.items():
        if v is None and k in ("name", "status"):
            continue
        setattr(a, k, v)
    a.updated_at = datetime.now(UTC)
    await audit.note(db, tenant, user, "audit:changed", "audit", audit_id, changes=sorted(changes))
    await db.commit()
    return await _detail(db, tenant, a)


@router.post(
    "/{audit_id}/requests", response_model=AuditDetail, status_code=status.HTTP_201_CREATED, summary="Add something the auditor asks for"
)
async def add_request(
    audit_id: uuid.UUID,
    body: RequestIn,
    tenant: ScopeTenant,
    db: DBSession,
    _user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> AuditDetail:
    a = await _audit(db, tenant, audit_id)
    db.add(
        AuditRequest(
            id=uuid.uuid4(),
            tenant_id=tenant,
            audit_id=audit_id,
            title=body.title.strip(),
            control_id=body.control_id,
            owner=body.owner,
            due_date=body.due_date,
        )
    )
    await db.commit()
    return await _detail(db, tenant, a)


@router.post(
    "/{audit_id}/requests/from-controls",
    response_model=AuditDetail,
    summary="Add a request for each control of the framework that is unhealthy or not tested and has none yet",
)
async def requests_from_controls(
    audit_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> AuditDetail:
    a = await _audit(db, tenant, audit_id)
    have = {r.control_id for r in await _requests(db, tenant, audit_id) if r.control_id}
    evidence = await evidence_by_control(db, tenant, [a.framework])
    made = 0
    for row in build_rows([a.framework], evidence, datetime.now(UTC)):
        if row.state in ("unhealthy", "not_tested", "at_risk") and row.control_id not in have and made < MAX_FROM_CONTROLS:
            db.add(
                AuditRequest(
                    id=uuid.uuid4(),
                    tenant_id=tenant,
                    audit_id=audit_id,
                    title=f"Evidence for {row.control_id}: {row.title}"[:300],
                    control_id=row.control_id,
                )
            )
            made += 1
    await db.commit()
    return await _detail(db, tenant, a)


@router.patch(
    "/{audit_id}/requests/{request_id}",
    response_model=AuditDetail,
    summary="Answer a request: who owns it, what was provided, and whether the auditor accepted it",
)
async def patch_request(
    audit_id: uuid.UUID,
    request_id: uuid.UUID,
    body: RequestPatch,
    tenant: ScopeTenant,
    db: DBSession,
    _user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> AuditDetail:
    a = await _audit(db, tenant, audit_id)
    r = (
        await db.execute(
            select(AuditRequest).where(AuditRequest.id == request_id, AuditRequest.audit_id == audit_id, AuditRequest.tenant_id == tenant)
        )
    ).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if a.status == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That audit is complete and cannot be changed.")
    changes = body.model_dump(exclude_unset=True)
    if "link" in changes:
        try:
            changes["link"] = check_link(changes["link"])
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
    for k, v in changes.items():
        if v is None and k in ("title", "status", "note"):
            continue
        setattr(r, k, v)
    r.updated_at = datetime.now(UTC)
    await db.commit()
    return await _detail(db, tenant, a)

"""Vendor management for an organization or one of its clients (Secureframe parity plan, step 2).

A register of the third parties the organization depends on: what each does for it, who owns the relationship, the risk level a person sets, how it signs in, the contract dates, the security reviews (a
recurring one comes due every N months after the last completed one; a one-time one can be added any time), and the documents held for it (links; the files themselves are not stored here). Every change is a
line in the vendor's history and a vendor is archived, never deleted. ``client_id`` reads or writes one of the caller's clients, as the other compliance routes do.

Permission: ``reports:read`` to see, ``reports:write`` to change.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import ScopeTenant
from app.models.vendor_management import Vendor, VendorDocument, VendorHistory, VendorReview
from app.services.audit import emit_audit
from app.services.vendor_management import CATEGORIES, DOC_TYPES, RISK_LEVELS, describe_changes, review_state

router = APIRouter(prefix="/compliance/vendors", tags=["vendors"])

Risk = Literal["unassessed", "low", "medium", "high", "critical"]
DataAccess = Literal["unknown", "none", "internal", "sensitive"]
FIELDS = (
    "name",
    "website",
    "trust_url",
    "service",
    "category",
    "owner",
    "risk_level",
    "data_access",
    "auth_type",
    "mfa",
    "account_manager_name",
    "account_manager_email",
    "contract_start",
    "contract_end",
    "review_interval_months",
    "notes",
)


class VendorIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    website: str | None = Field(default=None, max_length=300)
    trust_url: str | None = Field(default=None, max_length=500)
    service: str | None = Field(default=None, max_length=300)
    category: str = Field(default="Other", max_length=60)
    owner: str | None = Field(default=None, max_length=200)
    risk_level: Risk = "unassessed"
    data_access: DataAccess = "unknown"
    auth_type: str | None = Field(default=None, max_length=60)
    mfa: bool | None = None
    account_manager_name: str | None = Field(default=None, max_length=200)
    account_manager_email: str | None = Field(default=None, max_length=320)
    contract_start: date | None = None
    contract_end: date | None = None
    review_interval_months: int | None = Field(default=None, ge=1, le=60)
    notes: str = Field(default="", max_length=4000)


class VendorPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    website: str | None = Field(default=None, max_length=300)
    trust_url: str | None = Field(default=None, max_length=500)
    service: str | None = Field(default=None, max_length=300)
    category: str | None = Field(default=None, max_length=60)
    owner: str | None = Field(default=None, max_length=200)
    risk_level: Risk | None = None
    data_access: DataAccess | None = None
    auth_type: str | None = Field(default=None, max_length=60)
    mfa: bool | None = None
    account_manager_name: str | None = Field(default=None, max_length=200)
    account_manager_email: str | None = Field(default=None, max_length=320)
    contract_start: date | None = None
    contract_end: date | None = None
    review_interval_months: int | None = Field(default=None, ge=1, le=60)
    notes: str | None = Field(default=None, max_length=4000)
    clear_review_schedule: bool = False


class ReviewIn(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    kind: Literal["recurring", "one_time"] = "one_time"
    start_date: date | None = None
    due_date: date | None = None
    reviewer: str | None = Field(default=None, max_length=200)


class ReviewDone(BaseModel):
    outcome: Literal["no_concerns", "concerns"]
    findings: str = Field(default="", max_length=4000)
    reviewer: str | None = Field(default=None, max_length=200)


class DocumentIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    doc_type: str = Field(default="Other", max_length=40)
    url: str | None = Field(default=None, max_length=1000)


class ReviewOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    start_date: date
    due_date: date
    status: str
    reviewer: str | None
    outcome: str | None
    findings: str
    completed_at: datetime | None
    overdue: bool


class DocumentOut(BaseModel):
    id: uuid.UUID
    name: str
    doc_type: str
    url: str | None
    added_by: str | None
    added_at: datetime


class HistoryOut(BaseModel):
    actor: str | None
    action: str
    detail: str
    created_at: datetime


class VendorOut(BaseModel):
    id: uuid.UUID
    name: str
    website: str | None
    trust_url: str | None
    service: str | None
    category: str
    owner: str | None
    risk_level: str
    data_access: str
    auth_type: str | None
    mfa: bool | None
    account_manager_name: str | None
    account_manager_email: str | None
    contract_start: date | None
    contract_end: date | None
    review_interval_months: int | None
    notes: str
    status: str
    # none: no review open and none scheduled; in_progress; overdue; current (next one more than 30 days off); due (within 30 days).
    review_state: str
    next_review_due: date | None
    last_reviewed: date | None
    document_count: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class VendorDetail(VendorOut):
    reviews: list[ReviewOut]
    documents: list[DocumentOut]
    history: list[HistoryOut]


class Summary(BaseModel):
    total: int
    by_risk: dict[str, int]
    reviews_overdue: int
    reviews_in_progress: int
    unassessed: int


class VendorList(BaseModel):
    vendors: list[VendorOut]
    summary: Summary
    categories: list[str]
    document_types: list[str]


def _actor(user: Any) -> str | None:
    return getattr(user, "email", None)


def _snapshot(v: Vendor) -> dict[str, Any]:
    return {k: getattr(v, k) for k in FIELDS}


def _out(v: Vendor, reviews: list[VendorReview], documents: int, today: date) -> VendorOut:
    st = review_state(v.review_interval_months, reviews, v.created_at.date(), today)
    return VendorOut(
        **{k: getattr(v, k) for k in (*FIELDS, "id", "status", "created_at", "updated_at", "archived_at")},
        review_state=st["state"],
        next_review_due=st["next_due"],
        last_reviewed=st["last_completed"],
        document_count=documents,
    )


async def _note(db: Any, tenant: uuid.UUID, vendor_id: uuid.UUID, user: Any, action: str, detail: str = "") -> None:
    db.add(VendorHistory(id=uuid.uuid4(), tenant_id=tenant, vendor_id=vendor_id, actor=_actor(user), action=action, detail=detail[:2000]))


async def _get(db: Any, tenant: uuid.UUID, vendor_id: uuid.UUID) -> Vendor:
    row = (await db.execute(select(Vendor).where(Vendor.id == vendor_id, Vendor.tenant_id == tenant))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")
    return row


async def _audit(
    db: Any, tenant: uuid.UUID, user: AuthUser, request: Request, action: str, v: Vendor, changes: dict[str, Any] | None = None
) -> None:
    await emit_audit(
        db=db,
        tenant_id=tenant,
        actor_id=user.user_id,
        action=f"vendor:{action}",
        resource="vendor",
        resource_id=str(v.id),
        changes={"name": v.name, **(changes or {})},
        request=request,
    )


@router.get("", response_model=VendorList, summary="The vendors of this organization or client, with the dashboard figures")
async def list_vendors(
    tenant: ScopeTenant,
    db: DBSession,
    _user: Annotated[AuthUser, Depends(require_permission("reports:read"))],
    archived: bool = Query(False, description="True lists the archived vendors instead of the active ones."),
) -> VendorList:
    today = datetime.now(UTC).date()
    vendors = (
        (
            await db.execute(
                select(Vendor)
                .where(Vendor.tenant_id == tenant, (Vendor.status == "archived") if archived else (Vendor.status != "archived"))
                .order_by(Vendor.name)
            )
        )
        .scalars()
        .all()
    )
    reviews = (await db.execute(select(VendorReview).where(VendorReview.tenant_id == tenant))).scalars().all()
    docs = (await db.execute(select(VendorDocument.vendor_id).where(VendorDocument.tenant_id == tenant))).scalars().all()
    by_vendor: dict[uuid.UUID, list[VendorReview]] = {}
    for r in reviews:
        by_vendor.setdefault(r.vendor_id, []).append(r)
    doc_count: dict[uuid.UUID, int] = {}
    for d in docs:
        doc_count[d] = doc_count.get(d, 0) + 1
    out = [_out(v, by_vendor.get(v.id, []), doc_count.get(v.id, 0), today) for v in vendors]
    by_risk = dict.fromkeys(RISK_LEVELS, 0)
    for v in out:
        by_risk[v.risk_level] += 1
    return VendorList(
        vendors=out,
        summary=Summary(
            total=len(out),
            by_risk=by_risk,
            reviews_overdue=sum(1 for v in out if v.review_state == "overdue"),
            reviews_in_progress=sum(1 for v in out if v.review_state == "in_progress"),
            unassessed=by_risk["unassessed"],
        ),
        categories=list(CATEGORIES),
        document_types=list(DOC_TYPES),
    )


async def _detail(db: Any, tenant: uuid.UUID, vendor_id: uuid.UUID) -> VendorDetail:
    v = await _get(db, tenant, vendor_id)
    today = datetime.now(UTC).date()
    reviews = (
        (
            await db.execute(
                select(VendorReview)
                .where(VendorReview.vendor_id == vendor_id, VendorReview.tenant_id == tenant)
                .order_by(VendorReview.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    docs = (
        (
            await db.execute(
                select(VendorDocument)
                .where(VendorDocument.vendor_id == vendor_id, VendorDocument.tenant_id == tenant)
                .order_by(VendorDocument.added_at)
            )
        )
        .scalars()
        .all()
    )
    history = (
        (
            await db.execute(
                select(VendorHistory)
                .where(VendorHistory.vendor_id == vendor_id, VendorHistory.tenant_id == tenant)
                .order_by(VendorHistory.created_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    base = _out(v, list(reviews), len(docs), today)
    return VendorDetail(
        **base.model_dump(),
        reviews=[
            ReviewOut(
                id=r.id,
                kind=r.kind,
                title=r.title,
                start_date=r.start_date,
                due_date=r.due_date,
                status=r.status,
                reviewer=r.reviewer,
                outcome=r.outcome,
                findings=r.findings,
                completed_at=r.completed_at,
                overdue=r.status != "complete" and r.due_date < today,
            )
            for r in reviews
        ],
        documents=[
            DocumentOut(id=d.id, name=d.name, doc_type=d.doc_type, url=d.url, added_by=d.added_by, added_at=d.added_at) for d in docs
        ],
        history=[HistoryOut(actor=h.actor, action=h.action, detail=h.detail, created_at=h.created_at) for h in history],
    )


@router.post("", response_model=VendorDetail, status_code=status.HTTP_201_CREATED, summary="Add a vendor")
async def create_vendor(
    body: VendorIn,
    request: Request,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> VendorDetail:
    data = body.model_dump()
    data["name"] = data["name"].strip()
    if data["category"] not in CATEGORIES:
        data["category"] = "Other"
    dup = (
        await db.execute(select(Vendor.id).where(Vendor.tenant_id == tenant, Vendor.status == "active", Vendor.name.ilike(data["name"])))
    ).first()
    if dup is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A vendor with that name is already in the register.")
    now = datetime.now(UTC)
    v = Vendor(id=uuid.uuid4(), tenant_id=tenant, created_by=_actor(user), created_at=now, updated_at=now, **data)
    db.add(v)
    await db.flush()
    await _note(db, tenant, v.id, user, "created", f"risk {v.risk_level}")
    await _audit(db, tenant, user, request, "created", v)
    await db.commit()
    return await _detail(db, tenant, v.id)


@router.get("/{vendor_id}", response_model=VendorDetail, summary="One vendor with its reviews, documents and history")
async def get_vendor(
    vendor_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> VendorDetail:
    return await _detail(db, tenant, vendor_id)


@router.patch("/{vendor_id}", response_model=VendorDetail, summary="Change a vendor")
async def update_vendor(
    vendor_id: uuid.UUID,
    body: VendorPatch,
    request: Request,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> VendorDetail:
    v = await _get(db, tenant, vendor_id)
    if v.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An archived vendor cannot be changed. Restore it first.")
    before = _snapshot(v)
    changes = body.model_dump(exclude_unset=True, exclude={"clear_review_schedule"})
    if "category" in changes and changes["category"] not in CATEGORIES:
        changes["category"] = "Other"
    for key, value in changes.items():
        if value is None and key in ("name", "risk_level", "data_access", "category", "notes"):
            continue
        setattr(v, key, value.strip() if key == "name" and isinstance(value, str) else value)
    if body.clear_review_schedule:
        v.review_interval_months = None
    v.updated_at = datetime.now(UTC)
    lines = describe_changes(before, _snapshot(v))
    if lines:
        await _note(db, tenant, v.id, user, "changed", "; ".join(lines))
        await _audit(db, tenant, user, request, "changed", v, {"changes": lines})
    await db.commit()
    return await _detail(db, tenant, vendor_id)


@router.post("/{vendor_id}/archive", response_model=VendorDetail, summary="Archive a vendor (it stays in the history and can be restored)")
async def archive_vendor(
    vendor_id: uuid.UUID,
    request: Request,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> VendorDetail:
    v = await _get(db, tenant, vendor_id)
    if v.status != "archived":
        v.status = "archived"
        v.archived_at = v.updated_at = datetime.now(UTC)
        await _note(db, tenant, v.id, user, "archived")
        await _audit(db, tenant, user, request, "archived", v)
        await db.commit()
    return await _detail(db, tenant, vendor_id)


@router.post("/{vendor_id}/restore", response_model=VendorDetail, summary="Bring an archived vendor back")
async def restore_vendor(
    vendor_id: uuid.UUID,
    request: Request,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> VendorDetail:
    v = await _get(db, tenant, vendor_id)
    if v.status == "archived":
        v.status = "active"
        v.archived_at = None
        v.updated_at = datetime.now(UTC)
        await _note(db, tenant, v.id, user, "restored")
        await _audit(db, tenant, user, request, "restored", v)
        await db.commit()
    return await _detail(db, tenant, vendor_id)


@router.post(
    "/{vendor_id}/reviews", response_model=VendorDetail, status_code=status.HTTP_201_CREATED, summary="Start a security review of a vendor"
)
async def start_review(
    vendor_id: uuid.UUID,
    body: ReviewIn,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> VendorDetail:
    v = await _get(db, tenant, vendor_id)
    if v.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An archived vendor cannot be reviewed. Restore it first.")
    open_one = (
        await db.execute(select(VendorReview.id).where(VendorReview.vendor_id == vendor_id, VendorReview.status == "in_progress"))
    ).first()
    if open_one is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A review of this vendor is already in progress. Finish it first.")
    today = datetime.now(UTC).date()
    start = body.start_date or today
    due = body.due_date or start + timedelta(days=60)
    if due < start:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The due date is before the start date.")
    title = (body.title or f"Security review: {v.name} ({start.isoformat()})").strip()
    db.add(
        VendorReview(
            id=uuid.uuid4(),
            tenant_id=tenant,
            vendor_id=vendor_id,
            kind=body.kind,
            title=title,
            start_date=start,
            due_date=due,
            reviewer=body.reviewer,
        )
    )
    await _note(db, tenant, vendor_id, user, "review_started", f"{title}, due {due.isoformat()}")
    await db.commit()
    return await _detail(db, tenant, vendor_id)


@router.post(
    "/{vendor_id}/reviews/{review_id}/complete", response_model=VendorDetail, summary="Finish a security review with what it found"
)
async def complete_review(
    vendor_id: uuid.UUID,
    review_id: uuid.UUID,
    body: ReviewDone,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> VendorDetail:
    await _get(db, tenant, vendor_id)
    r = (
        await db.execute(
            select(VendorReview).where(VendorReview.id == review_id, VendorReview.vendor_id == vendor_id, VendorReview.tenant_id == tenant)
        )
    ).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    if r.status == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That review is already complete.")
    r.status = "complete"
    r.outcome = body.outcome
    r.findings = body.findings
    r.reviewer = body.reviewer or r.reviewer or _actor(user)
    r.completed_at = datetime.now(UTC)
    await _note(
        db, tenant, vendor_id, user, "review_completed", f"{r.title}: {'concerns found' if body.outcome == 'concerns' else 'no concerns'}"
    )
    await db.commit()
    return await _detail(db, tenant, vendor_id)


@router.post(
    "/{vendor_id}/documents",
    response_model=VendorDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Record a document held for a vendor",
)
async def add_document(
    vendor_id: uuid.UUID,
    body: DocumentIn,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> VendorDetail:
    await _get(db, tenant, vendor_id)
    doc_type = body.doc_type if body.doc_type in DOC_TYPES else "Other"
    url = (body.url or "").strip() or None
    if url and not url.lower().startswith(("https://", "http://")):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The link must start with https:// (or http://).")
    db.add(
        VendorDocument(
            id=uuid.uuid4(),
            tenant_id=tenant,
            vendor_id=vendor_id,
            name=body.name.strip(),
            doc_type=doc_type,
            url=url,
            added_by=_actor(user),
        )
    )
    await _note(db, tenant, vendor_id, user, "document_added", f"{doc_type}: {body.name.strip()}")
    await db.commit()
    return await _detail(db, tenant, vendor_id)


@router.delete("/{vendor_id}/documents/{document_id}", response_model=VendorDetail, summary="Remove a document record")
async def remove_document(
    vendor_id: uuid.UUID,
    document_id: uuid.UUID,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> VendorDetail:
    await _get(db, tenant, vendor_id)
    d = (
        await db.execute(
            select(VendorDocument).where(
                VendorDocument.id == document_id, VendorDocument.vendor_id == vendor_id, VendorDocument.tenant_id == tenant
            )
        )
    ).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    await _note(db, tenant, vendor_id, user, "document_removed", d.name)
    await db.delete(d)
    await db.commit()
    return await _detail(db, tenant, vendor_id)

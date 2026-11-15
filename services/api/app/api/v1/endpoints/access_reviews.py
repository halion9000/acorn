"""Access reviews (Secureframe parity plan: personnel and access reviews).

Start a review of a system: A.C.O.R.N takes a snapshot of the people who have access (the Microsoft 365 people it holds, another tool's people, or names typed in), flags the ones worth a second look (administrators,
no multi-factor, guests, disabled accounts, nobody signed in for three months) and the reviewer decides for each: keep or remove. A review can be completed only when every person is decided; it keeps a sentence
saying what was decided. Removing the access itself is done in the tool: this records the decision. Read with ``reports:read``, change with ``reports:write``; ``client_id`` reads or writes one of the caller's clients.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import ScopeTenant
from app.models.access_review import AccessReview, AccessReviewEntry
from app.models.identity_source import IdentitySource
from app.models.signin import IdentityMfaUser
from app.services import access_reviews as rules
from app.services import compliance_audit as audit

router = APIRouter(prefix="/compliance/access-reviews", tags=["compliance"])

M365 = "Microsoft 365"


class SystemChoice(BaseModel):
    system: str
    people: int  # how many people a snapshot of it would hold (0: type the names in)


class ReviewIn(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    system: str = Field(min_length=1, max_length=120)
    reviewer: str | None = Field(default=None, max_length=200)
    due_date: date | None = None
    # For a system with no connected source: the people, one name or address each.
    people: list[Annotated[str, Field(max_length=320)]] = Field(default_factory=list, max_length=2000)


class DecisionIn(BaseModel):
    decision: Literal["pending", "keep", "remove"]
    note: str = Field(default="", max_length=1000)


class BulkIn(BaseModel):
    decision: Literal["keep", "remove"]
    only_unflagged: bool = True  # leave the flagged people for a look of their own


class EntryOut(BaseModel):
    id: uuid.UUID
    person: str
    name: str | None
    access: str
    flags: list[str]
    decision: str
    note: str
    decided_by: str | None
    decided_at: datetime | None


class ReviewOut(BaseModel):
    id: uuid.UUID
    name: str
    system: str
    reviewer: str | None
    due_date: date | None
    status: str
    overdue: bool
    summary: str
    people: int
    pending: int
    keep: int
    remove: int
    flagged: int
    created_at: datetime
    completed_at: datetime | None
    completed_by: str | None


class ReviewDetail(ReviewOut):
    entries: list[EntryOut]


class ReviewList(BaseModel):
    reviews: list[ReviewOut]
    systems: list[SystemChoice]


def _actor(user: AuthUser) -> str | None:
    return getattr(user, "email", None)


def _out(r: AccessReview, entries: list[AccessReviewEntry], today: date) -> ReviewOut:
    decisions = [e.decision for e in entries]
    return ReviewOut(
        id=r.id,
        name=r.name,
        system=r.system,
        reviewer=r.reviewer,
        due_date=r.due_date,
        status=r.status,
        overdue=r.status == "open" and r.due_date is not None and r.due_date < today,
        summary=r.summary,
        people=len(entries),
        pending=decisions.count("pending"),
        keep=decisions.count("keep"),
        remove=decisions.count("remove"),
        flagged=sum(1 for e in entries if e.flags),
        created_at=r.created_at,
        completed_at=r.completed_at,
        completed_by=r.completed_by,
    )


async def _entries(db: DBSession, tenant: uuid.UUID, review_id: uuid.UUID) -> list[AccessReviewEntry]:
    rows = (
        (await db.execute(select(AccessReviewEntry).where(AccessReviewEntry.review_id == review_id, AccessReviewEntry.tenant_id == tenant)))
        .scalars()
        .all()
    )
    return sorted(rows, key=lambda e: (-len(e.flags or []), e.person.lower()))


async def _review(db: DBSession, tenant: uuid.UUID, review_id: uuid.UUID) -> AccessReview:
    row = (
        await db.execute(select(AccessReview).where(AccessReview.id == review_id, AccessReview.tenant_id == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    return row


async def _detail(db: DBSession, tenant: uuid.UUID, review: AccessReview) -> ReviewDetail:
    entries = await _entries(db, tenant, review.id)
    base = _out(review, entries, datetime.now(UTC).date())
    return ReviewDetail(
        **base.model_dump(),
        entries=[
            EntryOut(
                id=e.id,
                person=e.person,
                name=e.name,
                access=e.access,
                flags=list(e.flags or []),
                decision=e.decision,
                note=e.note,
                decided_by=e.decided_by,
                decided_at=e.decided_at,
            )
            for e in entries
        ],
    )


async def _systems(db: DBSession, tenant: uuid.UUID) -> list[SystemChoice]:
    out: list[SystemChoice] = []
    m365 = (await db.execute(select(func.count()).select_from(IdentityMfaUser).where(IdentityMfaUser.tenant_id == tenant))).scalar_one()
    if m365:
        out.append(SystemChoice(system=M365, people=int(m365)))
    for vendor, n in (
        await db.execute(
            select(IdentitySource.vendor, func.count())
            .where(IdentitySource.tenant_id == tenant)
            .group_by(IdentitySource.vendor)
            .order_by(IdentitySource.vendor)
        )
    ).all():
        out.append(SystemChoice(system=vendor, people=int(n)))
    return out


@router.get("", response_model=ReviewList, summary="The access reviews, newest first, and the systems whose people can be snapshotted")
async def list_reviews(
    tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> ReviewList:
    reviews = (
        (await db.execute(select(AccessReview).where(AccessReview.tenant_id == tenant).order_by(AccessReview.created_at.desc())))
        .scalars()
        .all()
    )
    by_review: dict[uuid.UUID, list[AccessReviewEntry]] = {}
    for e in (await db.execute(select(AccessReviewEntry).where(AccessReviewEntry.tenant_id == tenant))).scalars():
        by_review.setdefault(e.review_id, []).append(e)
    today = datetime.now(UTC).date()
    return ReviewList(reviews=[_out(r, by_review.get(r.id, []), today) for r in reviews], systems=await _systems(db, tenant))


@router.post(
    "",
    response_model=ReviewDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Start a review: snapshot the people with access to a system",
)
async def start_review(
    body: ReviewIn, tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> ReviewDetail:
    system = body.system.strip()
    if system == M365:
        users = (await db.execute(select(IdentityMfaUser).where(IdentityMfaUser.tenant_id == tenant))).scalars().all()
        lines = rules.entries_from_mfa_users(list(users))
    elif body.people:
        lines = rules.entries_from_names(body.people, system)
    else:
        rows = (
            (await db.execute(select(IdentitySource).where(IdentitySource.tenant_id == tenant, IdentitySource.vendor == system)))
            .scalars()
            .all()
        )
        lines = rules.entries_from_identities(list(rows), system)
    if not lines:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"There are no people to review for {system}. Type the names in, or choose a system A.C.O.R.N holds people for.",
        )
    review = AccessReview(
        id=uuid.uuid4(),
        tenant_id=tenant,
        name=body.name.strip(),
        system=system,
        reviewer=body.reviewer,
        due_date=body.due_date,
        created_by=_actor(user),
    )
    db.add(review)
    await db.flush()
    for ln in lines:
        db.add(
            AccessReviewEntry(
                id=uuid.uuid4(),
                tenant_id=tenant,
                review_id=review.id,
                person=ln["person"],
                name=ln["name"],
                access=ln["access"],
                flags=ln["flags"],
            )
        )
    await audit.note(
        db, tenant, user, "access_review:started", "access_review", review.id, name=review.name, system=review.system, people=len(lines)
    )
    await db.commit()
    return await _detail(db, tenant, review)


@router.get("/{review_id}", response_model=ReviewDetail, summary="One review with every person and the decision for each")
async def get_review(
    review_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> ReviewDetail:
    return await _detail(db, tenant, await _review(db, tenant, review_id))


@router.patch("/{review_id}/entries/{entry_id}", response_model=ReviewDetail, summary="Decide for one person: keep or remove their access")
async def decide(
    review_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: DecisionIn,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> ReviewDetail:
    review = await _review(db, tenant, review_id)
    if review.status == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That review is complete and cannot be changed.")
    entry = (
        await db.execute(
            select(AccessReviewEntry).where(
                AccessReviewEntry.id == entry_id, AccessReviewEntry.review_id == review_id, AccessReviewEntry.tenant_id == tenant
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found in this review")
    entry.decision = body.decision
    entry.note = body.note
    entry.decided_by = None if body.decision == "pending" else _actor(user)
    entry.decided_at = None if body.decision == "pending" else datetime.now(UTC)
    await db.commit()
    return await _detail(db, tenant, review)


@router.post(
    "/{review_id}/decide-all",
    response_model=ReviewDetail,
    summary="Decide for everyone still pending (by default only the people with no flag)",
)
async def decide_all(
    review_id: uuid.UUID,
    body: BulkIn,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> ReviewDetail:
    review = await _review(db, tenant, review_id)
    if review.status == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That review is complete and cannot be changed.")
    now = datetime.now(UTC)
    for e in await _entries(db, tenant, review_id):
        if e.decision != "pending" or (body.only_unflagged and e.flags):
            continue
        e.decision, e.decided_by, e.decided_at = body.decision, _actor(user), now
    await audit.note(
        db,
        tenant,
        user,
        "access_review:decided_all",
        "access_review",
        review_id,
        decision=body.decision,
        only_unflagged=body.only_unflagged,
    )
    await db.commit()
    return await _detail(db, tenant, review)


@router.post("/{review_id}/complete", response_model=ReviewDetail, summary="Complete the review once everyone is decided")
async def complete(
    review_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> ReviewDetail:
    review = await _review(db, tenant, review_id)
    if review.status == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That review is already complete.")
    decisions = [e.decision for e in await _entries(db, tenant, review_id)]
    ok, pending = rules.can_complete(decisions)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{pending} {'person is' if pending == 1 else 'people are'} still waiting for a decision."
            if pending
            else "There is nobody in this review.",
        )
    review.status = "complete"
    review.summary = rules.summarize(decisions)
    review.completed_at = datetime.now(UTC)
    review.completed_by = _actor(user)
    await audit.note(db, tenant, user, "access_review:completed", "access_review", review_id, summary=review.summary)
    await db.commit()
    return await _detail(db, tenant, review)

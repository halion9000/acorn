"""The review calendar and the policy library.

Things that must be looked at again on a schedule (policies, vendor reviews, evidence renewals, anything else) with an owner and a due date, and the text of a policy kept in numbered versions that are never edited,
only added to. Read with ``reports:read``, changed with ``reports:write`` (the compliance permissions). Every change is audited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.models.governance import GovernanceItem, GovernanceVersion
from app.models.tenant import Tenant
from app.services import governance as gov
from app.services import policy_templates as pt
from app.services.audit import emit_audit

router = APIRouter(prefix="/governance", tags=["compliance"])

MAX_ITEMS = 500


class ItemIn(BaseModel):
    kind: Literal["policy", "vendor", "evidence", "other"]
    title: str = Field(min_length=1, max_length=160)
    owner: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=2000)
    interval_days: int = Field(default=365, ge=1, le=1095)
    # The first due date; today plus the interval when left out.
    next_due: date | None = None


class ItemPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    owner: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    interval_days: int | None = Field(default=None, ge=1, le=1095)
    next_due: date | None = None


class ItemOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    owner: str
    notes: str
    interval_days: int
    next_due: date
    last_reviewed_at: date | None
    state: str
    days_until: int
    versions: int


class VersionIn(BaseModel):
    body: str = Field(min_length=1, max_length=100_000)
    change_note: str = Field(default="", max_length=300)


class VersionOut(BaseModel):
    version: int
    body: str
    change_note: str
    created_at: datetime


def _today() -> date:
    return datetime.now(UTC).date()


def _out(row: GovernanceItem, versions: int, today: date) -> ItemOut:
    return ItemOut(
        id=row.id,
        kind=row.kind,
        title=row.title,
        owner=row.owner,
        notes=row.notes,
        interval_days=row.interval_days,
        next_due=row.next_due,
        last_reviewed_at=row.last_reviewed_at,
        state=gov.due_state(row.next_due, today),
        days_until=gov.days_until(row.next_due, today),
        versions=versions,
    )


async def _item(db: DBSession, tenant: uuid.UUID, item_id: uuid.UUID) -> GovernanceItem:
    row = (
        await db.execute(
            select(GovernanceItem).where(
                GovernanceItem.id == item_id, GovernanceItem.tenant_id == tenant, GovernanceItem.archived_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such item")
    return row


async def _version_counts(db: DBSession, tenant: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = (
        await db.execute(
            select(GovernanceVersion.item_id, func.count()).where(GovernanceVersion.tenant_id == tenant).group_by(GovernanceVersion.item_id)
        )
    ).all()
    return dict(rows)


@router.get("", response_model=list[ItemOut], dependencies=[Depends(require_permission("reports:read"))])
async def list_items(user: AuthUser, db: DBSession) -> list[ItemOut]:
    today = _today()
    rows = (
        (
            await db.execute(
                select(GovernanceItem)
                .where(GovernanceItem.tenant_id == user.tenant_id, GovernanceItem.archived_at.is_(None))
                .order_by(GovernanceItem.next_due, GovernanceItem.title)
                .limit(MAX_ITEMS)
            )
        )
        .scalars()
        .all()
    )
    counts = await _version_counts(db, user.tenant_id)
    return [_out(r, counts.get(r.id, 0), today) for r in rows]


@router.post("", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(
    body: ItemIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("reports:write"))], db: DBSession
) -> ItemOut:
    count = (
        await db.execute(
            select(func.count())
            .select_from(GovernanceItem)
            .where(GovernanceItem.tenant_id == user.tenant_id, GovernanceItem.archived_at.is_(None))
        )
    ).scalar_one()
    if count >= MAX_ITEMS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"There are already {MAX_ITEMS} items; archive some first.")
    today = _today()
    row = GovernanceItem(
        tenant_id=user.tenant_id,
        kind=body.kind,
        title=body.title.strip(),
        owner=body.owner.strip(),
        notes=body.notes.strip(),
        interval_days=body.interval_days,
        next_due=body.next_due or gov.next_due_after_review(today, body.interval_days),
        created_by=user.user_id,
    )
    db.add(row)
    await db.flush()
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="governance_item:created",
        resource="governance_item",
        resource_id=str(row.id),
        changes={"kind": row.kind, "title": row.title},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return _out(row, 0, today)


@router.patch("/{item_id}", response_model=ItemOut)
async def update_item(
    item_id: uuid.UUID,
    body: ItemPatch,
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
    db: DBSession,
) -> ItemOut:
    row = await _item(db, user.tenant_id, item_id)
    changed = body.model_dump(exclude_unset=True)
    for k, v in changed.items():
        if v is None:
            continue
        setattr(row, k, v.strip() if isinstance(v, str) else v)
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="governance_item:updated",
        resource="governance_item",
        resource_id=str(row.id),
        changes={"fields": sorted(changed)},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return _out(row, (await _version_counts(db, user.tenant_id)).get(row.id, 0), _today())


@router.post("/{item_id}/reviewed", response_model=ItemOut)
async def mark_reviewed(
    item_id: uuid.UUID, request: Request, user: Annotated[AuthUser, Depends(require_permission("reports:write"))], db: DBSession
) -> ItemOut:
    """Reviewed today: the last-reviewed date is today and the next one is today plus the interval."""
    row = await _item(db, user.tenant_id, item_id)
    today = _today()
    row.last_reviewed_at = today
    row.next_due = gov.next_due_after_review(today, row.interval_days)
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="governance_item:reviewed",
        resource="governance_item",
        resource_id=str(row.id),
        changes={"next_due": row.next_due.isoformat()},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return _out(row, (await _version_counts(db, user.tenant_id)).get(row.id, 0), today)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_item(
    item_id: uuid.UUID, request: Request, user: Annotated[AuthUser, Depends(require_permission("reports:write"))], db: DBSession
) -> None:
    """Archive (hide), never delete: its versions and audit trail stay."""
    row = await _item(db, user.tenant_id, item_id)
    row.archived_at = datetime.now(UTC)
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="governance_item:archived",
        resource="governance_item",
        resource_id=str(row.id),
        changes={"title": row.title},
        request=request,
    )
    await db.commit()


@router.get("/{item_id}/versions", response_model=list[VersionOut], dependencies=[Depends(require_permission("reports:read"))])
async def list_versions(item_id: uuid.UUID, user: AuthUser, db: DBSession) -> list[VersionOut]:
    await _item(db, user.tenant_id, item_id)
    rows = (
        (
            await db.execute(
                select(GovernanceVersion)
                .where(GovernanceVersion.item_id == item_id, GovernanceVersion.tenant_id == user.tenant_id)
                .order_by(GovernanceVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return [VersionOut(version=r.version, body=r.body, change_note=r.change_note, created_at=r.created_at) for r in rows]


@router.post("/{item_id}/versions", response_model=VersionOut, status_code=status.HTTP_201_CREATED)
async def add_version(
    item_id: uuid.UUID,
    body: VersionIn,
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
    db: DBSession,
) -> VersionOut:
    """Save a new numbered version of a policy's text. An old version is never changed."""
    row = await _item(db, user.tenant_id, item_id)
    if row.kind != "policy":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only a policy keeps versions of its text.")
    latest = (
        await db.execute(select(func.coalesce(func.max(GovernanceVersion.version), 0)).where(GovernanceVersion.item_id == item_id))
    ).scalar_one()
    v = GovernanceVersion(
        tenant_id=user.tenant_id,
        item_id=item_id,
        version=latest + 1,
        body=body.body,
        change_note=body.change_note.strip(),
        created_by=user.user_id,
    )
    db.add(v)
    await db.flush()
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="governance_version:added",
        resource="governance_item",
        resource_id=str(item_id),
        changes={"version": v.version},
        request=request,
    )
    await db.commit()
    await db.refresh(v)
    return VersionOut(version=v.version, body=v.body, change_note=v.change_note, created_at=v.created_at)


# ---- policy templates --------------------------------------------------------------------------------------------------------------------------------------


class TemplateOut(BaseModel):
    key: str
    title: str
    summary: str
    interval_days: int
    fields: list[str]  # the fields the text fills in by itself
    added: bool  # a policy with this title is already in the library


class FromTemplate(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    owner: str = Field(default="", max_length=120)


class RenderedOut(BaseModel):
    title: str
    version: int
    text: str  # the version's text with the fields filled in
    missing: list[str]  # fields still showing as written because they have no value yet


async def _client_name(db: DBSession, tenant: uuid.UUID) -> str:
    row = await db.get(Tenant, tenant)
    return (getattr(row, "name", "") or "").strip()


@router.get("/templates", response_model=list[TemplateOut], dependencies=[Depends(require_permission("reports:read"))])
async def list_templates(user: AuthUser, db: DBSession) -> list[TemplateOut]:
    """The policy templates, and whether each is already in the library."""
    name = await _client_name(db, user.tenant_id)
    have = set(
        (
            await db.execute(
                select(GovernanceItem.title).where(
                    GovernanceItem.tenant_id == user.tenant_id, GovernanceItem.kind == "policy", GovernanceItem.archived_at.is_(None)
                )
            )
        ).scalars()
    )
    return [
        TemplateOut(
            key=t.key,
            title=t.title,
            summary=pt.render(t.summary, {"client_name": name}),
            interval_days=t.interval_days,
            fields=pt.fields_used(t.body),
            added=t.title in have,
        )
        for t in pt.TEMPLATES
    ]


@router.post("/from-template", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_from_template(
    body: FromTemplate, request: Request, user: Annotated[AuthUser, Depends(require_permission("reports:write"))], db: DBSession
) -> ItemOut:
    """Add a policy to the library from a template: its text becomes version 1 with the fields left as fields."""
    template = pt.BY_KEY.get(body.key)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such template.")
    exists = (
        await db.execute(
            select(GovernanceItem.id).where(
                GovernanceItem.tenant_id == user.tenant_id,
                GovernanceItem.kind == "policy",
                GovernanceItem.title == template.title,
                GovernanceItem.archived_at.is_(None),
            )
        )
    ).first()
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That policy is already in the library.")
    today = _today()
    row = GovernanceItem(
        tenant_id=user.tenant_id,
        kind="policy",
        title=template.title,
        owner=body.owner.strip(),
        notes="Made from the A.C.O.R.N template. Read it and adapt it before it is relied on.",
        interval_days=template.interval_days,
        next_due=gov.next_due_after_review(today, template.interval_days),
        created_by=user.user_id,
    )
    db.add(row)
    await db.flush()
    db.add(
        GovernanceVersion(
            tenant_id=user.tenant_id,
            item_id=row.id,
            version=1,
            body=template.body,
            change_note="From the template",
            created_by=user.user_id,
        )
    )
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="governance_item:created_from_template",
        resource="governance_item",
        resource_id=str(row.id),
        changes={"template": template.key, "title": template.title},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return _out(row, 1, today)


@router.get("/{item_id}/rendered", response_model=RenderedOut, dependencies=[Depends(require_permission("reports:read"))])
async def rendered_version(item_id: uuid.UUID, user: AuthUser, db: DBSession, version: int | None = None) -> RenderedOut:
    """A policy's text (the newest version, or the one asked for) with the organization, owner, version, dates filled in."""
    item = await _item(db, user.tenant_id, item_id)
    q = select(GovernanceVersion).where(GovernanceVersion.item_id == item_id, GovernanceVersion.tenant_id == user.tenant_id)
    q = q.where(GovernanceVersion.version == version) if version is not None else q.order_by(GovernanceVersion.version.desc()).limit(1)
    v = (await db.execute(q)).scalars().first()
    if v is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That policy has no such version.")
    values = pt.field_values(await _client_name(db, user.tenant_id), item.owner, v.version, v.created_at.date(), item.next_due, _today())
    text = pt.render(v.body, values)
    return RenderedOut(title=item.title, version=v.version, text=text, missing=[f for f in pt.fields_used(text) if f in pt.FIELDS])

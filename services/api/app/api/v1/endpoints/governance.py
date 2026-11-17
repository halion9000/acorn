"""The review calendar and the policy library.

Things that must be looked at again on a schedule (policies, vendor reviews, evidence renewals, anything else) with an owner and a due date, and the text of a policy kept in numbered versions that are never edited,
only added to. Read with ``reports:read``, changed with ``reports:write`` (the compliance permissions). Every change is audited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import ScopeTenant
from app.models.governance import GovernanceItem, GovernanceVersion
from app.models.policy_acceptance import PolicyAcceptance, PolicyAssignment
from app.models.tenant import Tenant
from app.services import governance as gov
from app.services import policy_acceptance as pa
from app.services import policy_assignment as pas
from app.services import policy_templates as pt
from app.services.audit import emit_audit
from app.services.identity_people import is_active

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
async def list_items(tenant: ScopeTenant, user: AuthUser, db: DBSession) -> list[ItemOut]:
    today = _today()
    rows = (
        (
            await db.execute(
                select(GovernanceItem)
                .where(GovernanceItem.tenant_id == tenant, GovernanceItem.archived_at.is_(None))
                .order_by(GovernanceItem.next_due, GovernanceItem.title)
                .limit(MAX_ITEMS)
            )
        )
        .scalars()
        .all()
    )
    counts = await _version_counts(db, tenant)
    return [_out(r, counts.get(r.id, 0), today) for r in rows]


@router.post("", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(
    tenant: ScopeTenant,
    body: ItemIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("reports:write"))], db: DBSession
) -> ItemOut:
    count = (
        await db.execute(
            select(func.count())
            .select_from(GovernanceItem)
            .where(GovernanceItem.tenant_id == tenant, GovernanceItem.archived_at.is_(None))
        )
    ).scalar_one()
    if count >= MAX_ITEMS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"There are already {MAX_ITEMS} items; archive some first.")
    today = _today()
    row = GovernanceItem(
        tenant_id=tenant,
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
        tenant_id=tenant,
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
    tenant: ScopeTenant,
    item_id: uuid.UUID,
    body: ItemPatch,
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
    db: DBSession,
) -> ItemOut:
    row = await _item(db, tenant, item_id)
    changed = body.model_dump(exclude_unset=True)
    for k, v in changed.items():
        if v is None:
            continue
        setattr(row, k, v.strip() if isinstance(v, str) else v)
    await emit_audit(
        db=db,
        tenant_id=tenant,
        actor_id=user.user_id,
        action="governance_item:updated",
        resource="governance_item",
        resource_id=str(row.id),
        changes={"fields": sorted(changed)},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return _out(row, (await _version_counts(db, tenant)).get(row.id, 0), _today())


@router.post("/{item_id}/reviewed", response_model=ItemOut)
async def mark_reviewed(
    tenant: ScopeTenant,
    item_id: uuid.UUID, request: Request, user: Annotated[AuthUser, Depends(require_permission("reports:write"))], db: DBSession
) -> ItemOut:
    """Reviewed today: the last-reviewed date is today and the next one is today plus the interval."""
    row = await _item(db, tenant, item_id)
    today = _today()
    row.last_reviewed_at = today
    row.next_due = gov.next_due_after_review(today, row.interval_days)
    await emit_audit(
        db=db,
        tenant_id=tenant,
        actor_id=user.user_id,
        action="governance_item:reviewed",
        resource="governance_item",
        resource_id=str(row.id),
        changes={"next_due": row.next_due.isoformat()},
        request=request,
    )
    await db.commit()
    await db.refresh(row)
    return _out(row, (await _version_counts(db, tenant)).get(row.id, 0), today)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_item(
    tenant: ScopeTenant,
    item_id: uuid.UUID, request: Request, user: Annotated[AuthUser, Depends(require_permission("reports:write"))], db: DBSession
) -> None:
    """Archive (hide), never delete: its versions and audit trail stay."""
    row = await _item(db, tenant, item_id)
    row.archived_at = datetime.now(UTC)
    await emit_audit(
        db=db,
        tenant_id=tenant,
        actor_id=user.user_id,
        action="governance_item:archived",
        resource="governance_item",
        resource_id=str(row.id),
        changes={"title": row.title},
        request=request,
    )
    await db.commit()


@router.get("/{item_id}/versions", response_model=list[VersionOut], dependencies=[Depends(require_permission("reports:read"))])
async def list_versions(tenant: ScopeTenant, item_id: uuid.UUID, user: AuthUser, db: DBSession) -> list[VersionOut]:
    await _item(db, tenant, item_id)
    rows = (
        (
            await db.execute(
                select(GovernanceVersion)
                .where(GovernanceVersion.item_id == item_id, GovernanceVersion.tenant_id == tenant)
                .order_by(GovernanceVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )
    return [VersionOut(version=r.version, body=r.body, change_note=r.change_note, created_at=r.created_at) for r in rows]


@router.post("/{item_id}/versions", response_model=VersionOut, status_code=status.HTTP_201_CREATED)
async def add_version(
    tenant: ScopeTenant,
    item_id: uuid.UUID,
    body: VersionIn,
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
    db: DBSession,
) -> VersionOut:
    """Save a new numbered version of a policy's text. An old version is never changed."""
    row = await _item(db, tenant, item_id)
    if row.kind != "policy":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only a policy keeps versions of its text.")
    latest = (
        await db.execute(select(func.coalesce(func.max(GovernanceVersion.version), 0)).where(GovernanceVersion.item_id == item_id))
    ).scalar_one()
    v = GovernanceVersion(
        tenant_id=tenant,
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
        tenant_id=tenant,
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


class AcceptanceIn(BaseModel):
    emails: list[str] = Field(min_length=1, max_length=200)
    version: int | None = Field(default=None, ge=1)  # the newest version when left out
    accepted_on: date | None = None  # today when left out


class AcceptedOut(BaseModel):
    email: str
    name: str | None
    version: int
    accepted_on: date
    recorded_by: str | None


class PendingOut(BaseModel):
    email: str
    name: str | None
    older_version: int | None


class AcceptanceOut(BaseModel):
    version: int | None
    accepted: list[AcceptedOut]
    pending: list[PendingOut]
    others: list[AcceptedOut]
    share: float | None


def _accepted_out(a: pa.Accepted) -> AcceptedOut:
    return AcceptedOut(email=a.email, name=a.name, version=a.version, accepted_on=a.accepted_on, recorded_by=a.recorded_by)


async def _acceptance_view(db: DBSession, tenant: uuid.UUID, item_id: uuid.UUID) -> AcceptanceOut:
    from app.api.v1.endpoints.identities import _people  # late: that module is large and imports compliance helpers

    latest = (await db.execute(select(func.max(GovernanceVersion.version)).where(GovernanceVersion.item_id == item_id))).scalar_one()
    if latest is None:
        return AcceptanceOut(version=None, accepted=[], pending=[], others=[], share=None)
    rows = (await db.execute(select(PolicyAcceptance).where(PolicyAcceptance.item_id == item_id, PolicyAcceptance.tenant_id == tenant))).scalars().all()
    people, _ = await _people(db, tenant, None)
    roster = [(p.email, p.display_name) for p in people if p.tenant_id == tenant and is_active(p)]
    out = pa.summarize(roster, [pa.Accepted(r.email, r.display_name, r.version, r.accepted_on, r.recorded_by) for r in rows], latest)
    return AcceptanceOut(
        version=latest,
        accepted=[_accepted_out(a) for a in out["accepted"]],
        pending=[PendingOut(**p) for p in out["pending"]],
        others=[_accepted_out(a) for a in out["others"]],
        share=out["share"],
    )


@router.get("/{item_id}/acceptances", response_model=AcceptanceOut, dependencies=[Depends(require_permission("reports:read"))])
async def list_acceptances(tenant: ScopeTenant, item_id: uuid.UUID, user: AuthUser, db: DBSession) -> AcceptanceOut:
    """Who has accepted the newest version of a policy and who has not (from the organization's active people)."""
    row = await _item(db, tenant, item_id)
    if row.kind != "policy":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only a policy is accepted.")
    return await _acceptance_view(db, tenant, item_id)


@router.post("/{item_id}/acceptances", response_model=AcceptanceOut, status_code=status.HTTP_201_CREATED)
async def record_acceptances(
    tenant: ScopeTenant,
    item_id: uuid.UUID,
    body: AcceptanceIn,
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
    db: DBSession,
) -> AcceptanceOut:
    """Record that people accepted a version (the newest unless named). Asking twice for the same person and version changes nothing."""
    row = await _item(db, tenant, item_id)
    if row.kind != "policy":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only a policy is accepted.")
    latest = (await db.execute(select(func.max(GovernanceVersion.version)).where(GovernanceVersion.item_id == item_id))).scalar_one()
    if latest is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Save the policy's text first; there is nothing to accept yet.")
    version = body.version or latest
    if version > latest:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That policy has no such version.")
    day = body.accepted_on or _today()
    if day > _today():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The day of acceptance is in the future.")
    emails = sorted({pa.norm(e) for e in body.emails if "@" in e})
    if not emails:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Give at least one e-mail address.")
    have = set(
        (await db.execute(select(PolicyAcceptance.email).where(PolicyAcceptance.item_id == item_id, PolicyAcceptance.version == version, PolicyAcceptance.email.in_(emails)))).scalars().all()
    )
    added = [e for e in emails if e not in have]
    for e in added:
        db.add(PolicyAcceptance(id=uuid.uuid4(), tenant_id=tenant, item_id=item_id, version=version, email=e, accepted_on=day, recorded_by=getattr(user, "email", None)))
    await db.flush()
    if added:
        await emit_audit(
            db=db,
            tenant_id=tenant,
            actor_id=user.user_id,
            action="policy_acceptance:recorded",
            resource="governance_item",
            resource_id=str(item_id),
            changes={"version": version, "people": len(added)},
            request=request,
        )
    await db.commit()
    return await _acceptance_view(db, tenant, item_id)


class AssignIn(BaseModel):
    emails: list[str] = Field(default_factory=list, max_length=500)
    everyone: bool = False  # every active person the organization holds, as well as the addresses given
    due_on: date | None = None  # fourteen days from today when left out


class AssignmentOut(BaseModel):
    email: str
    name: str | None
    due_on: date
    assigned_by: str | None
    state: str  # accepted / pending / overdue
    reminders_sent: int
    last_reminded_on: date | None


async def _assignment_rows(db: DBSession, tenant: uuid.UUID, item_id: uuid.UUID) -> list[AssignmentOut]:
    latest = (await db.execute(select(func.max(GovernanceVersion.version)).where(GovernanceVersion.item_id == item_id))).scalar_one()
    rows = (
        (await db.execute(select(PolicyAssignment).where(PolicyAssignment.item_id == item_id, PolicyAssignment.tenant_id == tenant).order_by(PolicyAssignment.email)))
        .scalars()
        .all()
    )
    accepted = set()
    if latest is not None:
        accepted = set(
            (await db.execute(select(PolicyAcceptance.email).where(PolicyAcceptance.item_id == item_id, PolicyAcceptance.version == latest))).scalars().all()
        )
    today = _today()
    return [
        AssignmentOut(
            email=r.email,
            name=r.display_name,
            due_on=r.due_on,
            assigned_by=r.assigned_by,
            state=pas.state_of(r.due_on, r.email in accepted, today),
            reminders_sent=r.reminders_sent,
            last_reminded_on=r.last_reminded_at.date() if r.last_reminded_at else None,
        )
        for r in rows
    ]


@router.get("/{item_id}/assignments", response_model=list[AssignmentOut], dependencies=[Depends(require_permission("reports:read"))])
async def list_assignments(tenant: ScopeTenant, item_id: uuid.UUID, user: AuthUser, db: DBSession) -> list[AssignmentOut]:
    """Who the policy is assigned to, with whether each has accepted its newest version."""
    row = await _item(db, tenant, item_id)
    if row.kind != "policy":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only a policy is assigned.")
    return await _assignment_rows(db, tenant, item_id)


@router.post("/{item_id}/assignments", response_model=list[AssignmentOut], status_code=status.HTTP_201_CREATED)
async def assign_policy(
    tenant: ScopeTenant,
    item_id: uuid.UUID,
    body: AssignIn,
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
    db: DBSession,
) -> list[AssignmentOut]:
    """Assign the policy to people (by address and/or everyone active): each must read and accept its newest version, and is reminded by e-mail until they do. Assigning again keeps the earlier due day."""
    row = await _item(db, tenant, item_id)
    if row.kind != "policy":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only a policy is assigned.")
    has_text = (await db.execute(select(func.max(GovernanceVersion.version)).where(GovernanceVersion.item_id == item_id))).scalar_one()
    if has_text is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Save the text of the policy first; there is nothing to read yet.")
    today = _today()
    due = body.due_on or pas.default_due(today)
    if due < today:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The due day has already passed.")
    people: dict[str, str | None] = {pa.norm(e): None for e in body.emails if "@" in e}
    if body.everyone:
        from app.api.v1.endpoints.identities import _people  # late: that module is large and imports compliance helpers

        found, _ = await _people(db, tenant, None)
        for p in found:
            if p.tenant_id == tenant and is_active(p):
                people.setdefault(pa.norm(p.email), p.display_name)
    if not people:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Give at least one e-mail address, or choose everyone.")
    if len(people) > 2000:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That is too many people at once (2000 at most).")
    have = set((await db.execute(select(PolicyAssignment.email).where(PolicyAssignment.item_id == item_id, PolicyAssignment.email.in_(list(people))))).scalars().all())
    added = [e for e in sorted(people) if e not in have]
    for e in added:
        db.add(PolicyAssignment(id=uuid.uuid4(), tenant_id=tenant, item_id=item_id, email=e, display_name=people[e], due_on=due, assigned_by=getattr(user, "email", None)))
    await db.flush()
    if added:
        await emit_audit(
            db=db,
            tenant_id=tenant,
            actor_id=user.user_id,
            action="policy_assignment:added",
            resource="governance_item",
            resource_id=str(item_id),
            changes={"people": len(added), "due_on": due.isoformat()},
            request=request,
        )
    await db.commit()
    return await _assignment_rows(db, tenant, item_id)


@router.delete("/{item_id}/assignments/{email}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_policy(
    tenant: ScopeTenant,
    item_id: uuid.UUID,
    email: str,
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
    db: DBSession,
) -> None:
    """Take the policy off one person (their acceptances stay on record)."""
    await _item(db, tenant, item_id)
    found = (
        await db.execute(select(PolicyAssignment).where(PolicyAssignment.item_id == item_id, PolicyAssignment.tenant_id == tenant, PolicyAssignment.email == pa.norm(email)))
    ).scalar_one_or_none()
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That person is not assigned this policy.")
    await db.delete(found)
    await emit_audit(
        db=db,
        tenant_id=tenant,
        actor_id=user.user_id,
        action="policy_assignment:removed",
        resource="governance_item",
        resource_id=str(item_id),
        changes={"people": 1},
        request=request,
    )
    await db.commit()


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
async def list_templates(tenant: ScopeTenant, user: AuthUser, db: DBSession) -> list[TemplateOut]:
    """The policy templates, and whether each is already in the library."""
    name = await _client_name(db, tenant)
    have = set(
        (
            await db.execute(
                select(GovernanceItem.title).where(
                    GovernanceItem.tenant_id == tenant, GovernanceItem.kind == "policy", GovernanceItem.archived_at.is_(None)
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
    tenant: ScopeTenant,
    body: FromTemplate, request: Request, user: Annotated[AuthUser, Depends(require_permission("reports:write"))], db: DBSession
) -> ItemOut:
    """Add a policy to the library from a template: its text becomes version 1 with the fields left as fields."""
    template = pt.BY_KEY.get(body.key)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such template.")
    exists = (
        await db.execute(
            select(GovernanceItem.id).where(
                GovernanceItem.tenant_id == tenant,
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
        tenant_id=tenant,
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
            tenant_id=tenant,
            item_id=row.id,
            version=1,
            body=template.body,
            change_note="From the template",
            created_by=user.user_id,
        )
    )
    await emit_audit(
        db=db,
        tenant_id=tenant,
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
async def rendered_version(
    tenant: ScopeTenant,
    item_id: uuid.UUID, user: AuthUser, db: DBSession, version: Annotated[int | None, Query(ge=1, le=100_000)] = None
) -> RenderedOut:
    """A policy's text (the newest version, or the one asked for) with the organization, owner, version, dates filled in."""
    item = await _item(db, tenant, item_id)
    q = select(GovernanceVersion).where(GovernanceVersion.item_id == item_id, GovernanceVersion.tenant_id == tenant)
    q = q.where(GovernanceVersion.version == version) if version is not None else q.order_by(GovernanceVersion.version.desc()).limit(1)
    v = (await db.execute(q)).scalars().first()
    if v is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That policy has no such version.")
    values = pt.field_values(await _client_name(db, tenant), item.owner, v.version, v.created_at.date(), item.next_due, _today())
    text = pt.render(v.body, values)
    return RenderedOut(title=item.title, version=v.version, text=text, missing=[f for f in pt.fields_used(text) if f in pt.FIELDS])

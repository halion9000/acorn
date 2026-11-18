"""People and their onboarding and offboarding checklists.

The people are the organization's active people (the same list policies are assigned from), plus anyone with a checklist (a leaver is no longer active but their offboarding list stays). A checklist is started from a
built-in list; tasks are ticked off one at a time and stay on file with who did it and when. Read with ``reports:read``, changed with ``reports:write``. Every change is audited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import ScopeTenant
from app.models.policy_acceptance import PersonnelTask
from app.services import personnel_tasks as pt
from app.services.audit import emit_audit
from app.services.identity_people import is_active

router = APIRouter(prefix="/personnel", tags=["compliance"])


class TaskOut(BaseModel):
    id: uuid.UUID
    email: str
    kind: str
    title: str
    due_on: date | None
    done_at: datetime | None
    done_by: str | None


class ProgressOut(BaseModel):
    started: bool
    total: int
    done: int
    open: int
    overdue: int


class PersonOut(BaseModel):
    email: str
    name: str | None
    active: bool
    onboarding: ProgressOut
    offboarding: ProgressOut


class StartIn(BaseModel):
    kind: Literal["onboarding", "offboarding"]


class AddIn(BaseModel):
    kind: Literal["onboarding", "offboarding"]
    title: str = Field(min_length=3, max_length=200)
    due_on: date | None = None


class DoneIn(BaseModel):
    done: bool


def _today() -> date:
    return datetime.now(UTC).date()


def _out(t: PersonnelTask) -> TaskOut:
    return TaskOut(id=t.id, email=t.email, kind=t.kind, title=t.title, due_on=t.due_on, done_at=t.done_at, done_by=t.done_by)


def _me(user: AuthUser) -> str | None:
    mine = pt.norm(getattr(user, "email", None))
    return mine or None


def _email(raw: str) -> str:
    e = pt.norm(raw)
    if "@" not in e or " " in e or len(e) > 254:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That is not an e-mail address.")
    return e


async def _roster(db: DBSession, tenant: uuid.UUID) -> dict[str, str | None]:
    from app.api.v1.endpoints.identities import _people  # late: that module is large and imports compliance helpers

    people, _ = await _people(db, tenant, None)
    return {pt.norm(p.email): p.display_name for p in people if p.tenant_id == tenant and is_active(p)}


@router.get("", response_model=list[PersonOut], dependencies=[Depends(require_permission("reports:read"))])
async def list_people(tenant: ScopeTenant, db: DBSession) -> list[PersonOut]:
    """Each active person, and anyone with a checklist, with how their onboarding and offboarding stand."""
    roster = await _roster(db, tenant)
    rows = (await db.execute(select(PersonnelTask).where(PersonnelTask.tenant_id == tenant))).scalars().all()
    by_person: dict[str, list[pt.Task]] = {}
    for r in rows:
        by_person.setdefault(pt.norm(r.email), []).append(pt.Task(r.kind, r.done_at is not None, r.due_on))
    today = _today()
    out: list[PersonOut] = []
    for email in sorted(set(roster) | set(by_person)):
        mine = by_person.get(email, [])
        out.append(
            PersonOut(
                email=email,
                name=roster.get(email),
                active=email in roster,
                onboarding=ProgressOut(**pt.progress(mine, "onboarding", today)),
                offboarding=ProgressOut(**pt.progress(mine, "offboarding", today)),
            )
        )
    return out


async def _tasks_of(db: DBSession, tenant: uuid.UUID, who: str) -> list[TaskOut]:
    q = select(PersonnelTask).where(PersonnelTask.tenant_id == tenant, PersonnelTask.email == who).order_by(PersonnelTask.kind, PersonnelTask.due_on, PersonnelTask.title)
    return [_out(r) for r in (await db.execute(q)).scalars().all()]


@router.get("/{email}/tasks", response_model=list[TaskOut], dependencies=[Depends(require_permission("reports:read"))])
async def person_tasks(tenant: ScopeTenant, email: str, db: DBSession) -> list[TaskOut]:
    return await _tasks_of(db, tenant, _email(email))


@router.post("/{email}/tasks/start", response_model=list[TaskOut], status_code=status.HTTP_201_CREATED)
async def start_checklist(
    tenant: ScopeTenant, email: str, body: StartIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("reports:write"))], db: DBSession
) -> list[TaskOut]:
    """Start the built-in onboarding or offboarding list for a person. Starting it again only adds the tasks the person does not have."""
    who = _email(email)
    have = set((await db.execute(select(PersonnelTask.title).where(PersonnelTask.tenant_id == tenant, PersonnelTask.email == who, PersonnelTask.kind == body.kind))).scalars().all())
    added = pt.tasks_to_start(body.kind, have, _today())
    for title, due in added:
        db.add(PersonnelTask(id=uuid.uuid4(), tenant_id=tenant, email=who, kind=body.kind, title=title, due_on=due, created_by=_me(user)))
    await db.flush()
    if added:
        await emit_audit(db=db, tenant_id=tenant, actor_id=user.user_id, action="personnel_checklist:started", resource="personnel", resource_id=who, changes={"kind": body.kind, "tasks": len(added)}, request=request)
    await db.commit()
    return await _tasks_of(db, tenant, who)


@router.post("/{email}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def add_task(
    tenant: ScopeTenant, email: str, body: AddIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("reports:write"))], db: DBSession
) -> TaskOut:
    """Add one task of your own to a person's checklist."""
    who = _email(email)
    title = " ".join(body.title.split())
    same = select(PersonnelTask.id).where(PersonnelTask.tenant_id == tenant, PersonnelTask.email == who, PersonnelTask.kind == body.kind, PersonnelTask.title == title)
    if (await db.execute(same)).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That task is already on the list.")
    t = PersonnelTask(id=uuid.uuid4(), tenant_id=tenant, email=who, kind=body.kind, title=title, due_on=body.due_on, created_by=_me(user))
    db.add(t)
    await db.flush()
    await emit_audit(db=db, tenant_id=tenant, actor_id=user.user_id, action="personnel_task:added", resource="personnel", resource_id=who, changes={"kind": body.kind}, request=request)
    await db.commit()
    return _out(t)


async def _task(db: DBSession, tenant: uuid.UUID, task_id: uuid.UUID) -> PersonnelTask:
    t = (await db.execute(select(PersonnelTask).where(PersonnelTask.id == task_id, PersonnelTask.tenant_id == tenant))).scalar_one_or_none()
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such task.")
    return t


@router.post("/tasks/{task_id}/done", response_model=TaskOut)
async def mark_task(
    tenant: ScopeTenant, task_id: uuid.UUID, body: DoneIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("reports:write"))], db: DBSession
) -> TaskOut:
    """Tick a task off (who and when are kept), or put it back."""
    t = await _task(db, tenant, task_id)
    t.done_at, t.done_by = (datetime.now(UTC), _me(user)) if body.done else (None, None)
    await db.flush()
    action = "personnel_task:done" if body.done else "personnel_task:reopened"
    await emit_audit(db=db, tenant_id=tenant, actor_id=user.user_id, action=action, resource="personnel", resource_id=t.email, changes={"kind": t.kind}, request=request)
    await db.commit()
    return _out(t)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_task(
    tenant: ScopeTenant, task_id: uuid.UUID, request: Request, user: Annotated[AuthUser, Depends(require_permission("reports:write"))], db: DBSession
) -> None:
    """Remove a task from a list (one that was added by mistake)."""
    t = await _task(db, tenant, task_id)
    await db.delete(t)
    await emit_audit(db=db, tenant_id=tenant, actor_id=user.user_id, action="personnel_task:removed", resource="personnel", resource_id=t.email, changes={"kind": t.kind}, request=request)
    await db.commit()

"""Scheduled reports: choose a report, who gets it and how often (roadmap r7-af-32). Read with ``reports:read``, change with ``reports:write``; ``client_id`` reads or writes one of the caller's clients.

The report is e-mailed as plain text by the mail account A.C.O.R.N already uses for the compliance notice (the mail credentials must be set). "Send now" sends one right away and records how it went. A new schedule
first runs at its next slot, not at once. Which kinds of report exist is in ``app.services.report_scheduler.KINDS``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import ScopeTenant
from app.models.report_schedule import ReportSchedule
from app.services import report_scheduler as rs
from app.workers.report_schedule_worker import send_schedule

router = APIRouter(prefix="/compliance/report-schedules", tags=["compliance"])

MAX_SCHEDULES = 50


class ScheduleIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    report_kind: str = Field(min_length=1, max_length=40)
    emails: list[str] = Field(min_length=1, max_length=rs.MAX_EMAILS)
    frequency: Literal["daily", "weekly", "monthly"]
    day: int = Field(default=0, ge=0, le=28)
    hour_utc: int = Field(default=7, ge=0, le=23)
    enabled: bool = True


class SchedulePatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    emails: list[str] | None = Field(default=None, min_length=1, max_length=rs.MAX_EMAILS)
    frequency: Literal["daily", "weekly", "monthly"] | None = None
    day: int | None = Field(default=None, ge=0, le=28)
    hour_utc: int | None = Field(default=None, ge=0, le=23)
    enabled: bool | None = None


class ScheduleOut(BaseModel):
    id: uuid.UUID
    name: str
    report_kind: str
    report_label: str
    emails: list[str]
    frequency: str
    day: int
    hour_utc: int
    enabled: bool
    last_run_at: datetime | None
    last_result: str | None


class ScheduleList(BaseModel):
    schedules: list[ScheduleOut]
    kinds: list[dict[str, str]]


def _out(r: ReportSchedule) -> ScheduleOut:
    return ScheduleOut(
        id=r.id,
        name=r.name,
        report_kind=r.report_kind,
        report_label=rs.KINDS.get(r.report_kind, (r.report_kind, None))[0],
        emails=list(r.emails or []),
        frequency=r.frequency,
        day=r.day,
        hour_utc=r.hour_utc,
        enabled=r.enabled,
        last_run_at=r.last_run_at,
        last_result=r.last_result,
    )


def _check_slot(frequency: str, day: int) -> None:
    if frequency == "weekly" and day > 6:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A weekly schedule's day is 0 (Monday) to 6 (Sunday).")
    if frequency == "monthly" and not 1 <= day <= 28:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A monthly schedule's day is 1 to 28.")


async def _get(db: DBSession, tenant: uuid.UUID, schedule_id: uuid.UUID) -> ReportSchedule:
    row = (await db.execute(select(ReportSchedule).where(ReportSchedule.id == schedule_id, ReportSchedule.tenant_id == tenant))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return row


def _emails(raw: list[str]) -> list[str]:
    cleaned = rs.clean_emails(raw)
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Give at least one valid e-mail address.")
    return cleaned


@router.get("", response_model=ScheduleList, summary="The scheduled reports and the kinds of report that can be scheduled")
async def list_schedules(tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]) -> ScheduleList:
    rows = (await db.execute(select(ReportSchedule).where(ReportSchedule.tenant_id == tenant).order_by(ReportSchedule.created_at))).scalars().all()
    return ScheduleList(schedules=[_out(r) for r in rows], kinds=[{"kind": k, "label": v[0]} for k, v in rs.KINDS.items()])


@router.post("", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED, summary="Schedule a report")
async def create_schedule(
    body: ScheduleIn, tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> ScheduleOut:
    if body.report_kind not in rs.KINDS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That kind of report cannot be scheduled.")
    _check_slot(body.frequency, body.day)
    emails = _emails(body.emails)
    count = len((await db.execute(select(ReportSchedule.id).where(ReportSchedule.tenant_id == tenant))).all())
    if count >= MAX_SCHEDULES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"At most {MAX_SCHEDULES} scheduled reports.")
    row = ReportSchedule(
        id=uuid.uuid4(), tenant_id=tenant, name=body.name.strip(), report_kind=body.report_kind, emails=emails, frequency=body.frequency, day=body.day,
        hour_utc=body.hour_utc, enabled=body.enabled, last_run_at=datetime.now(UTC), created_by=getattr(user, "email", None),
    )
    db.add(row)
    await db.commit()
    return _out(row)


@router.patch("/{schedule_id}", response_model=ScheduleOut, summary="Change a schedule")
async def patch_schedule(
    schedule_id: uuid.UUID, body: SchedulePatch, tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> ScheduleOut:
    row = await _get(db, tenant, schedule_id)
    changes = body.model_dump(exclude_unset=True)
    frequency = changes.get("frequency", row.frequency)
    day = changes.get("day", row.day)
    _check_slot(frequency, day)
    if "emails" in changes and changes["emails"] is not None:
        changes["emails"] = _emails(changes["emails"])
    for k, v in changes.items():
        if v is not None:
            setattr(row, k, v)
    await db.commit()
    return _out(row)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a schedule")
async def delete_schedule(schedule_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:write"))]) -> None:
    await db.delete(await _get(db, tenant, schedule_id))
    await db.commit()


@router.post("/{schedule_id}/send-now", response_model=ScheduleOut, summary="Send this report now and record how it went")
async def send_now(
    schedule_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> ScheduleOut:
    row = await _get(db, tenant, schedule_id)
    await send_schedule(db, row, now=datetime.now(UTC))
    await db.commit()
    return _out(row)

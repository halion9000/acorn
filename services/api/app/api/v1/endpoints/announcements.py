"""Announcements: a short banner a person can post for the team, shown above every page until it ends or is removed.

``GET /announcements`` is open to everyone who can use the console (the viewer permission, alerts:read) and returns what is live today (not past its end day), newest first. Posting and removing need ``settings_workspace:manage``.
The text is plain: control characters are dropped and it is cut at 400 characters; the page shows it as text, never as markup. At most 5 can be live at once so the banner cannot fill the screen.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.v1.deps import AuthUser, require_permission
from app.db.rls import TenantDBSession
from app.models.announcement import Announcement

router = APIRouter(prefix="/announcements", tags=["announcements"])

MAX_LIVE = 5
MAX_LEN = 400


class AnnouncementIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    tone: Literal["info", "warning"] = "info"
    ends_on: date | None = None


class AnnouncementOut(BaseModel):
    id: uuid.UUID
    message: str
    tone: str
    ends_on: date | None
    created_by: str | None
    created_at: datetime


def clean_message(text: str) -> str:
    """The message as stored: control characters other than a space dropped, runs of white space made one space, cut at 400 characters (pure)."""
    kept = "".join(ch if ch >= " " else " " for ch in text)
    return " ".join(kept.split())[:MAX_LEN]


def is_live(ends_on: date | None, today: date) -> bool:
    """Whether an announcement still shows: with no end day always, otherwise through its end day (pure)."""
    return ends_on is None or ends_on >= today


async def _live(db: TenantDBSession, tenant: uuid.UUID, today: date) -> list[Announcement]:
    rows = (await db.execute(select(Announcement).where(Announcement.tenant_id == tenant).order_by(Announcement.created_at.desc()))).scalars().all()
    return [r for r in rows if is_live(r.ends_on, today)]


def _out(r: Announcement) -> AnnouncementOut:
    return AnnouncementOut(id=r.id, message=r.message, tone=r.tone, ends_on=r.ends_on, created_by=r.created_by, created_at=r.created_at)


@router.get("", response_model=list[AnnouncementOut])
async def list_announcements(user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: TenantDBSession) -> list[AnnouncementOut]:
    return [_out(r) for r in await _live(db, user.tenant_id, datetime.now(UTC).date())][:MAX_LIVE]


@router.post("", response_model=AnnouncementOut, status_code=status.HTTP_201_CREATED)
async def post_announcement(
    body: AnnouncementIn, user: Annotated[AuthUser, Depends(require_permission("settings_workspace:manage"))], db: TenantDBSession
) -> AnnouncementOut:
    today = datetime.now(UTC).date()
    text = clean_message(body.message)
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The announcement is empty.")
    if body.ends_on is not None and body.ends_on < today:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The end day has already passed.")
    if len(await _live(db, user.tenant_id, today)) >= MAX_LIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"{MAX_LIVE} announcements are already showing. Remove one first.")
    row = Announcement(id=uuid.uuid4(), tenant_id=user.tenant_id, message=text, tone=body.tone, ends_on=body.ends_on, created_by=getattr(user, "email", None))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _out(row)


@router.delete("/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_announcement(
    announcement_id: uuid.UUID, user: Annotated[AuthUser, Depends(require_permission("settings_workspace:manage"))], db: TenantDBSession
) -> Response:
    gone = await db.execute(delete(Announcement).where(Announcement.id == announcement_id, Announcement.tenant_id == user.tenant_id))
    if gone.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Announcement not found")
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

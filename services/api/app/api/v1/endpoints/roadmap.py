"""The roadmap (Settings > Upcoming improvements): what is waiting to be built or fixed, who it waits on, how urgent it is and where it stands.

The person sets priority, adds items of their own, and may move an item's status. Items kept in step from the repository file (see ``services/roadmap_sync.py``) have their wording, status and "needs" rewritten by that
sync, never their priority. Nothing is deleted. Permission: the Workspace area of Settings (``settings_workspace:view`` to see, ``settings_workspace:manage`` to change). The roadmap belongs to the caller's own organization.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.models.roadmap import RoadmapItem
from app.services import compliance_audit as audit

router = APIRouter(prefix="/roadmap", tags=["roadmap"])

Status = Literal["new", "not_started", "in_progress", "completed"]
Needs = Literal["claude", "signoff", "hal"]
Priority = Literal["high", "normal", "low"]
ORDER = {"in_progress": 0, "new": 1, "not_started": 2, "completed": 3}
RANK = {"high": 0, "normal": 1, "low": 2}


class ItemOut(BaseModel):
    id: uuid.UUID
    key: str | None
    title: str
    detail: str
    area: str
    status: Status
    needs: Needs
    priority: Priority
    note: str
    completed_ref: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    approved_at: datetime | None = None
    approved_by: str | None = None
    reply: str = ""
    reply_at: datetime | None = None
    reply_by: str | None = None


class ItemIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    detail: str = Field(default="", max_length=4000)
    area: str = Field(default="General", max_length=60)
    needs: Needs = "claude"
    priority: Priority = "normal"


class ItemPatch(BaseModel):
    priority: Priority | None = None
    status: Status | None = None
    needs: Needs | None = None
    note: str | None = Field(default=None, max_length=4000)
    # The person's own answer or question; an empty text clears it.
    reply: str | None = Field(default=None, max_length=4000)


class RoadmapOut(BaseModel):
    items: list[ItemOut]
    counts: dict[str, int]


def _sorted(rows: list[RoadmapItem]) -> list[RoadmapItem]:
    """Open work first (in progress, new, not started), the most urgent first, then the finished, newest finish first."""
    done = sorted((r for r in rows if r.status == "completed"), key=lambda r: r.completed_at or r.updated_at, reverse=True)
    open_ = sorted((r for r in rows if r.status != "completed"), key=lambda r: (ORDER[r.status], RANK[r.priority], r.created_at))
    return open_ + done


def _out(r: RoadmapItem) -> ItemOut:
    return ItemOut.model_validate(r, from_attributes=True)


@router.get("", response_model=RoadmapOut, summary="Everything on the roadmap with the count in each status")
async def list_items(db: DBSession, user: Annotated[AuthUser, Depends(require_permission("settings_workspace:view"))]) -> RoadmapOut:
    rows = list(
        (await db.execute(select(RoadmapItem).where(RoadmapItem.tenant_id == user.tenant_id, RoadmapItem.removed_at.is_(None)))).scalars()
    )
    counts = dict.fromkeys(("new", "not_started", "in_progress", "completed"), 0)
    for r in rows:
        counts[r.status] += 1
    return RoadmapOut(items=[_out(r) for r in _sorted(rows)], counts=counts)


@router.post("", response_model=ItemOut, status_code=status.HTTP_201_CREATED, summary="Add an item of your own")
async def add_item(
    body: ItemIn, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("settings_workspace:manage"))]
) -> ItemOut:
    now = datetime.now(UTC)
    row = RoadmapItem(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        title=body.title.strip(),
        detail=body.detail,
        area=body.area.strip() or "General",
        needs=body.needs,
        priority=body.priority,
        created_by=getattr(user, "email", None),
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await audit.note(db, user.tenant_id, user, "roadmap:added", "roadmap_item", row.id, title=row.title)
    await db.commit()
    return _out(row)


@router.patch("/{item_id}", response_model=ItemOut, summary="Set an item's priority, move its status, or change who it waits on")
async def update_item(
    item_id: uuid.UUID, body: ItemPatch, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("settings_workspace:manage"))]
) -> ItemOut:
    row = (
        await db.execute(select(RoadmapItem).where(RoadmapItem.id == item_id, RoadmapItem.tenant_id == user.tenant_id))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    changes = body.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(row, key, value.strip() if key == "reply" else value)
    if "reply" in changes:
        row.reply_at, row.reply_by = (datetime.now(UTC), getattr(user, "email", None)) if row.reply else (None, None)
    if "status" in changes:
        row.completed_at = datetime.now(UTC) if changes["status"] == "completed" else None
        row.person_status = row.key is not None
    row.updated_at = datetime.now(UTC)
    await audit.note(db, user.tenant_id, user, "roadmap:changed", "roadmap_item", item_id, changes=sorted(changes))
    await db.commit()
    return _out(row)


@router.post("/{item_id}/approve", response_model=ItemOut, summary="Approve an item that waits on sign-off: it moves to ready to build, with who approved it and when")
async def approve_item(
    item_id: uuid.UUID, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("settings_workspace:manage"))]
) -> ItemOut:
    row = (
        await db.execute(select(RoadmapItem).where(RoadmapItem.id == item_id, RoadmapItem.tenant_id == user.tenant_id, RoadmapItem.removed_at.is_(None)))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    if row.needs != "signoff" or row.status == "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only an item that is waiting on sign-off can be approved.")
    now = datetime.now(UTC)
    row.needs, row.approved_at, row.approved_by, row.updated_at = "claude", now, getattr(user, "email", None), now
    await audit.note(db, user.tenant_id, user, "roadmap:approved", "roadmap_item", item_id, title=row.title)
    await db.commit()
    return _out(row)


@router.delete(
    "/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an item from the list (it is hidden, not deleted, and the sync does not bring it back)",
)
async def remove_item(
    item_id: uuid.UUID, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("settings_workspace:manage"))]
) -> None:
    row = (
        await db.execute(
            select(RoadmapItem).where(RoadmapItem.id == item_id, RoadmapItem.tenant_id == user.tenant_id, RoadmapItem.removed_at.is_(None))
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    row.removed_at = row.updated_at = datetime.now(UTC)
    await audit.note(db, user.tenant_id, user, "roadmap:removed", "roadmap_item", item_id, title=row.title)
    await db.commit()

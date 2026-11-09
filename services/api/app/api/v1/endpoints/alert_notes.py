"""Notes on an alert: what someone looked at or who they called, written without changing the alert's status, owner or priority.

``GET /alerts/{id}/notes`` (``alerts:read``) lists them oldest first; ``POST /alerts/{id}/notes`` (``alerts:triage``, the permission to claim and snooze) adds one. A note is never edited or deleted from here; each
is audited. The alert is found the way every single-alert route finds it (the caller's own, or a client's), and the note is kept under the tenant that holds the alert.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.v1.deps import AuthUser, require_permission
from app.db.rls import TenantDBSession
from app.models.alert import Alert
from app.models.alert_note import AlertNote
from app.services.alert_scope import alert_scope
from app.services.audit import emit_audit

router = APIRouter(prefix="/alerts", tags=["alerts"])

MAX_NOTES = 200
MAX_BODY = 4000


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_BODY)


class NoteOut(BaseModel):
    id: uuid.UUID
    author: str
    body: str
    created_at: datetime


def clean_body(text: str) -> str:
    """The note as stored: line breaks kept, trailing space and blank edges removed, control characters other than a line break or tab dropped (pure)."""
    kept = "".join(ch for ch in text if ch in "\n\t" or ch >= " ")
    return "\n".join(line.rstrip() for line in kept.strip().splitlines())


@router.get("/{alert_id}/notes", response_model=list[NoteOut], dependencies=[Depends(require_permission("alerts:read"))])
async def list_notes(alert_id: uuid.UUID, user: AuthUser, db: TenantDBSession) -> list[NoteOut]:
    async with alert_scope(db, user.tenant_id, alert_id) as tid:
        found = (await db.execute(select(Alert.id).where(Alert.id == alert_id, Alert.tenant_id == tid))).first()
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        rows = (await db.execute(select(AlertNote).where(AlertNote.alert_id == alert_id, AlertNote.tenant_id == tid).order_by(AlertNote.created_at, AlertNote.id).limit(MAX_NOTES))).scalars().all()
    return [NoteOut(id=r.id, author=r.author, body=r.body, created_at=r.created_at) for r in rows]


@router.post("/{alert_id}/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
async def add_note(alert_id: uuid.UUID, body: NoteIn, request: Request, user: Annotated[AuthUser, Depends(require_permission("alerts:triage"))], db: TenantDBSession) -> NoteOut:
    text = clean_body(body.body)
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The note is empty.")
    async with alert_scope(db, user.tenant_id, alert_id) as tid:
        found = (await db.execute(select(Alert.id).where(Alert.id == alert_id, Alert.tenant_id == tid))).first()
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        count = (await db.execute(select(func.count()).select_from(AlertNote).where(AlertNote.alert_id == alert_id, AlertNote.tenant_id == tid))).scalar_one()
        if count >= MAX_NOTES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"This alert already has {MAX_NOTES} notes.")
        row = AlertNote(tenant_id=tid, alert_id=alert_id, author_id=user.user_id, author=(getattr(user, "email", "") or "")[:160], body=text)
        db.add(row)
        await db.flush()
        await emit_audit(db=db, tenant_id=tid, actor_id=user.user_id, action="alert_note:added", resource="alert", resource_id=str(alert_id), changes={"length": len(text)}, request=request)
        await db.commit()
        await db.refresh(row)
    return NoteOut(id=row.id, author=row.author, body=row.body, created_at=row.created_at)

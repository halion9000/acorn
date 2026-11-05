"""Platform administrators' reminders for stored credentials that have an end date: a name and a date each, never the credential. Warnings appear on the platform health page.

Platform administrators only (``platform:cross_tenant_query``, written out on each route). The list belongs to the owner tenant's settings. Changing it writes an audit event in the same transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.models.tenant import Tenant
from app.services.audit import emit_audit
from app.services.credential_expiry import InvalidEntries, clean_entries, stored_entries, with_days_left

router = APIRouter(prefix="/platform/credential-expiries", tags=["platform"])


class Entry(BaseModel):
    name: str
    expires_on: str


class EntryRow(Entry):
    days_left: int


class Entries(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[Entry]


class Rows(BaseModel):
    entries: list[EntryRow]


def _rows(settings: Any) -> Rows:
    return Rows(entries=[EntryRow(**r) for r in with_days_left(stored_entries(settings), datetime.now(UTC).date())])


@router.get("", response_model=Rows)
async def list_credential_expiries(
    current_user: Annotated[AuthUser, Depends(require_permission("platform:cross_tenant_query"))], db: DBSession
) -> Rows:
    owner = await db.get(Tenant, current_user.tenant_id)
    return _rows(getattr(owner, "settings", None))


@router.put("", response_model=Rows)
async def replace_credential_expiries(
    body: Entries, current_user: Annotated[AuthUser, Depends(require_permission("platform:cross_tenant_query"))], db: DBSession
) -> Rows:
    try:
        entries = clean_entries([e.model_dump() for e in body.entries])
    except InvalidEntries as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    owner = await db.get(Tenant, current_user.tenant_id)
    if owner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    before = stored_entries(owner.settings)
    settings = dict(owner.settings or {})
    settings["credential_expiries"] = entries
    owner.settings = settings  # a new dict, so the JSONB column is seen as changed
    await emit_audit(
        db=db,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        action="platform:credential_expiries_changed",
        resource="tenant",
        resource_id=str(owner.id),
        changes={"names_before": [e["name"] for e in before], "names_after": [e["name"] for e in entries]},
    )
    await db.commit()
    return _rows(owner.settings)

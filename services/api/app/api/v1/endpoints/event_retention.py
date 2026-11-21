"""How long each client's stored events are kept (SIEM style storage): infinite by default, or 1, 3, 5, 7 or 10 years per client (and a default for the organization).

Nothing is deleted by setting a retention. Deleting is a second, deliberate step: the preview says how many events each client's retention has passed, and the purge deletes exactly that many only when the number
confirmed matches the number now (so it cannot remove more than was shown). Reading needs ``reports:read``; changing and purging need ``mssp:manage`` and are written to the audit log.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.models.tenant import Tenant
from app.services import event_store as es
from app.services.audit import emit_audit

router = APIRouter(prefix="/events/retention", tags=["events"])


class RetentionIn(BaseModel):
    """``default`` and each client's value: 1, 3, 5, 7 or 10 (years), or "infinite"."""

    default: int | str = "infinite"
    clients: dict[str, int | str] = Field(default_factory=dict, max_length=2000)


def clean(body: RetentionIn) -> dict[str, Any]:
    """The retention as it is stored (pure): only the five choices or "infinite"; anything else is refused with the value named."""

    def one(v: int | str, what: str) -> int | str:
        if v == "infinite":
            return "infinite"
        if isinstance(v, int) and not isinstance(v, bool) and v in es.RETENTION_CHOICES:
            return v
        raise HTTPException(status_code=422, detail=f"{what}: choose 1, 3, 5, 7 or 10 years, or infinite")

    out: dict[str, Any] = {"default": one(body.default, "default"), "clients": {}}
    for cid, v in body.clients.items():
        try:
            uuid.UUID(cid)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"{cid} is not a client id") from None
        out["clients"][cid] = one(v, cid)
    return out


async def _settings(db: Any, tenant_id: uuid.UUID) -> tuple[Any, dict[str, Any]]:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant, dict(tenant.settings or {})


@router.get("", dependencies=[Depends(require_permission("reports:read"))], summary="The retention of the stored events")
async def get_retention(user: AuthUser, db: DBSession) -> dict[str, Any]:
    _, settings = await _settings(db, user.tenant_id)
    r = settings.get("retention") or {}
    return {"default": r.get("default", "infinite"), "clients": r.get("clients") or {}, "choices": list(es.RETENTION_CHOICES)}


@router.put("", dependencies=[Depends(require_permission("mssp:manage"))], summary="Set how long events are kept (deletes nothing)")
async def put_retention(body: RetentionIn, request: Request, user: AuthUser, db: DBSession) -> dict[str, Any]:
    tenant, settings = await _settings(db, user.tenant_id)
    settings["retention"] = clean(body)
    tenant.settings = settings
    await emit_audit(db=db, tenant_id=user.tenant_id, actor_id=user.user_id, action="events:retention_changed", resource="retention", resource_id="events", changes=settings["retention"], request=request)
    await db.commit()
    return {**settings["retention"], "choices": list(es.RETENTION_CHOICES)}


@router.get("/preview", dependencies=[Depends(require_permission("reports:read"))], summary="How many events each client's retention has passed (deletes nothing)")
async def preview(user: AuthUser, db: DBSession) -> dict[str, Any]:
    _, settings = await _settings(db, user.tenant_id)
    counts = await es.expired_counts(db, user.tenant_id, settings, datetime.now(UTC))
    return {"by_client": counts, "total": sum(counts.values())}


class PurgeIn(BaseModel):
    confirm: int = Field(ge=0, description="The total the preview gave; the purge runs only when it is still the number of events past retention")


@router.post("/purge", dependencies=[Depends(require_permission("mssp:manage"))], summary="Delete the events past each client's retention, only when the confirmed number matches")
async def purge(body: PurgeIn, request: Request, user: AuthUser, db: DBSession) -> dict[str, Any]:
    _, settings = await _settings(db, user.tenant_id)
    now = datetime.now(UTC)
    total = sum((await es.expired_counts(db, user.tenant_id, settings, now)).values())
    if total != body.confirm:
        raise HTTPException(status_code=409, detail=f"{total} events are past retention now, not {body.confirm}; look at the preview again.")
    deleted = await es.purge_expired(db, user.tenant_id, settings, now) if total else 0
    await emit_audit(db=db, tenant_id=user.tenant_id, actor_id=user.user_id, action="events:purged", resource="retention", resource_id="events", changes={"deleted": deleted}, request=request)
    await db.commit()
    return {"deleted": deleted}

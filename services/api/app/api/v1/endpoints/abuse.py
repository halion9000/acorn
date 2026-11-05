"""``GET /abuse/logins``: failed sign-ins in the lock window, as counts. Read only; names no address that was typed."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.api.v1.deps import DBSession, require_permission
from app.models.login_failure import LoginFailure
from app.services.login_abuse import abuse_summary
from app.services.login_throttle import limits, window

router = APIRouter(prefix="/abuse", tags=["abuse"])


class BusyClient(BaseModel):
    client: str
    failures: int


class LoginAbuse(BaseModel):
    window_minutes: int
    failures: int
    addresses_tried: int
    clients: int
    locked_addresses: int
    locked_clients: int
    busiest_clients: list[BusyClient]


@router.get(
    "/logins",
    response_model=LoginAbuse,
    dependencies=[Depends(require_permission("audit_log:read"))],
    summary="Failed sign-ins in the lock window: how many, from how many places, and what is locked (no typed address is named)",
)
async def login_abuse(db: DBSession) -> dict[str, Any]:
    from app.db.rls_scope import cross_tenant_reads

    now = datetime.now(UTC)
    async with cross_tenant_reads(db):  # a sign-in happens before any tenant is known
        rows = (
            await db.execute(select(LoginFailure.email_key, LoginFailure.client_ip).where(LoginFailure.created_at > now - window()))
        ).all()
    per_address, per_client = limits()
    return abuse_summary(list(rows), per_address, per_client, round(window().total_seconds() / 60))

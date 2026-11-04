"""The Cloudflare tunnel token for the public honeytoken address: CORE hands it over, the update script on the VM puts it to use (app/services/canary_tunnel.py says how).

The token is never returned. ``GET`` says only whether one is stored, which tunnel it is for (an id Cloudflare shows on its own page) and when it last changed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.inbox_core_feed import _verify_core_feed_token
from app.db.rls_sessions import adopt_tenant
from app.services import canary_tunnel as tunnel
from app.services.audit import emit_audit
from app.services.update_control import control_dir

ingest_router = APIRouter(prefix="/inbox", tags=["inbox-core-feed"])
router = APIRouter(prefix="/canary-tunnel", tags=["honeytokens"])


class TunnelIn(BaseModel):
    token: Annotated[str, Field(min_length=1, max_length=tunnel.MAX_TOKEN_CHARS + 200)]


class TunnelStored(BaseModel):
    stored: bool
    changed: bool


class TunnelStateOut(BaseModel):
    stored: bool
    tunnel_id: str | None = None
    changed_at: datetime | None = None


@ingest_router.post("/core-feed/{tenant_token}/canary-tunnel", response_model=TunnelStored)
async def receive_tunnel_token(tenant_token: str, body: TunnelIn, db: DBSession, request: Request) -> TunnelStored:
    """CORE's "Cloudflare canary" card sends the tunnel token here. Checked, kept for the update script, never echoed; a change is audited (without the token)."""
    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    try:
        token = tunnel.check_token(body.token)
    except tunnel.TokenRefused as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
    try:
        changed = tunnel.store_token(control_dir(), token)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from None
    if changed:
        await emit_audit(
            db=db,
            tenant_id=owner,
            action="honeytokens:tunnel_token_changed",
            resource="canary-tunnel",
            resource_id=tunnel.state(control_dir()).tunnel_id,
            changes={"source": "core"},
            request=request,
        )
        await db.commit()
    return TunnelStored(stored=True, changed=changed)


@router.get(
    "",
    response_model=TunnelStateOut,
    dependencies=[Depends(require_permission("alerts:read"))],
    summary="Whether the Cloudflare tunnel token for the public honeytoken address is stored",
)
async def tunnel_state(_user: AuthUser) -> TunnelStateOut:
    s = tunnel.state(control_dir())
    return TunnelStateOut(stored=s.stored, tunnel_id=s.tunnel_id, changed_at=s.changed_at)

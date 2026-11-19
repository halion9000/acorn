"""The employee toolbox, stage 1 (roadmap rw-toolbox): list the Microsoft 365 tools and make a request for one, which becomes an approval card. Nothing runs against a client's tenant.

Read the tools with ``alerts:read``; make a request with ``cases:write``. The request is an ordinary approval (``/approvals``) owned by the organization, naming the client, the tool and every value, so a
person with the right to decide sees exactly what was asked. Running an approved request through CIPP is a later stage.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import _scope
from app.models.responder import AgentApproval
from app.services import toolbox as tb
from app.services.audit import emit_audit

router = APIRouter(prefix="/toolbox", tags=["toolbox"])

EXPIRES_AFTER = timedelta(days=7)


class RequestIn(BaseModel):
    tool: str = Field(min_length=1, max_length=40)
    client_id: uuid.UUID
    args: dict[str, Any] = Field(default_factory=dict)


@router.get("/tools", summary="The Microsoft 365 tools a technician can ask for, in groups")
async def tools(user: Annotated[AuthUser, Depends(require_permission("alerts:read"))]) -> dict[str, Any]:
    return {"groups": list(tb.GROUPS), "tools": tb.catalog(), "stage": "Requests are recorded for approval. Running an approved request is the next stage."}


@router.post("/request", status_code=201, summary="Ask for a tool to be run for a client: creates an approval request, runs nothing")
async def make_request(body: RequestIn, user: Annotated[AuthUser, Depends(require_permission("cases:write"))], db: DBSession) -> dict[str, Any]:
    scope, names = await _scope(db, user.tenant_id, body.client_id)
    if body.client_id not in scope or body.client_id not in names:
        raise HTTPException(status_code=404, detail="Client not found")
    tool, args, why = tb.check_request(body.tool, body.args)
    if why or tool is None:
        raise HTTPException(status_code=422, detail=why or "That request cannot be made.")
    client = names[body.client_id]
    title, summary = tb.approval_text(tool, client, args)
    row = AgentApproval(
        tenant_id=user.tenant_id,
        requested_by=f"toolbox:{user.email}"[:120],
        title=title,
        summary=summary,
        risk_level=tool.risk,
        action={"kind": "toolbox", "tool": tool.id, "client_id": str(body.client_id), "client": client, "args": args},
        expires_at=datetime.now(UTC) + EXPIRES_AFTER,
        status="pending",
    )
    db.add(row)
    await db.flush()
    await emit_audit(db=db, tenant_id=user.tenant_id, actor_id=user.user_id, action="toolbox:request", resource="agent_approval", resource_id=str(row.id), changes={"tool": tool.id, "client": client})
    await db.commit()
    return {"approval_id": str(row.id), "status": "pending", "title": title, "risk": tool.risk, "note": "Waiting for approval. Nothing has been run."}

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
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import _scope
from app.db.rls_scope import cross_tenant_reads
from app.models.responder import AgentApproval
from app.models.signin import IdentityMfaUser
from app.services import core_lookup as lk
from app.services import toolbox as tb
from app.services.audit import emit_audit
from app.security.credential_vault import get_vault
from app.services.identity_people import MICROSOFT

router = APIRouter(prefix="/toolbox", tags=["toolbox"])

MAX_LOOKUP_ROWS = 5000

EXPIRES_AFTER = timedelta(days=7)


class RequestIn(BaseModel):
    tool: str = Field(min_length=1, max_length=40)
    client_id: uuid.UUID
    args: dict[str, Any] = Field(default_factory=dict)


@router.get("/tools", summary="The Microsoft 365 tools a technician can ask for, in groups")
async def tools(user: Annotated[AuthUser, Depends(require_permission("alerts:read"))]) -> dict[str, Any]:
    return {"groups": list(tb.GROUPS), "tools": tb.catalog(), "stage": "Requests are recorded for approval. Running an approved request is the next stage."}


async def _client_people(db: DBSession, owner: uuid.UUID, client_id: uuid.UUID) -> dict[str, Any]:
    """The picker lists of one client (people and sign-in domains) from its latest Microsoft 365 user list, or 404 when it is not the caller's client."""
    scope, names = await _scope(db, owner, client_id)
    if client_id not in scope or client_id not in names:
        raise HTTPException(status_code=404, detail="Client not found")
    async with cross_tenant_reads(db):
        rows = (
            await db.execute(
                select(IdentityMfaUser.upn, IdentityMfaUser.display_name, IdentityMfaUser.enabled, IdentityMfaUser.user_type)
                .where(IdentityMfaUser.tenant_id == client_id, IdentityMfaUser.source == MICROSOFT)
                .limit(MAX_LOOKUP_ROWS)
            )
        ).all()
    return tb.people_and_domains([(r[0], r[1], r[2], r[3]) for r in rows])


@router.get("/lookups", summary="The people and sign-in domains of one client, for the pickers")
async def lookups(client_id: uuid.UUID, user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> dict[str, Any]:
    """Read from the client's latest Microsoft 365 user list (the one CORE reads through CIPP), so a form offers real people instead of a text box."""
    return await _client_people(db, user.tenant_id, client_id)


class GroupsIn(BaseModel):
    client_id: uuid.UUID


class RulesIn(BaseModel):
    client_id: uuid.UUID
    user: str = Field(min_length=3, max_length=320)


async def _queue(db: DBSession, user: AuthUser, action: str, value: str) -> dict[str, Any]:
    try:
        row = await lk.queue_toolbox_lookup(db, user.tenant_id, user.user_id, action, value)
    except lk.LookupRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()
    return lk.present_toolbox(row)


async def _read(db: DBSession, user: AuthUser, request_id: uuid.UUID, kind: str) -> dict[str, Any]:
    row = await lk.read_toolbox_lookup(db, user.tenant_id, request_id)
    if row is None or row.action != (lk.DIRECTORY if kind == "groups" else lk.RULES):
        raise HTTPException(status_code=404, detail="No such lookup request.")
    return lk.present_toolbox(row)


@router.post("/groups", summary="Ask CORE for a client's groups and licenses (read only), for the group form")
async def ask_groups(body: GroupsIn, user: Annotated[AuthUser, Depends(require_permission("cases:write"))], db: DBSession) -> dict[str, Any]:
    domains = (await _client_people(db, user.tenant_id, body.client_id))["domains"]
    if not domains:
        raise HTTPException(status_code=422, detail="No Microsoft 365 people are known for this client yet, so its groups cannot be asked for.")
    return await _queue(db, user, lk.DIRECTORY, domains[0])


@router.get("/groups/{request_id}", summary="The answer to a groups request: waiting, failed or the groups")
async def read_groups(request_id: uuid.UUID, user: Annotated[AuthUser, Depends(require_permission("cases:write"))], db: DBSession) -> dict[str, Any]:
    return await _read(db, user, request_id, "groups")


@router.post("/inbox-rules", summary="Ask CORE for one person's inbox rules (read only), so the bad ones can be picked")
async def ask_inbox_rules(body: RulesIn, user: Annotated[AuthUser, Depends(require_permission("identities:bec"))], db: DBSession) -> dict[str, Any]:
    people = (await _client_people(db, user.tenant_id, body.client_id))["people"]
    if body.user.strip().lower() not in {p["email"].lower() for p in people}:
        raise HTTPException(status_code=422, detail="That person is not one of this client's Microsoft 365 users.")
    return await _queue(db, user, lk.RULES, body.user)


@router.get("/inbox-rules/{request_id}", summary="The answer to an inbox rules request: waiting, failed or the rules")
async def read_inbox_rules(request_id: uuid.UUID, user: Annotated[AuthUser, Depends(require_permission("identities:bec"))], db: DBSession) -> dict[str, Any]:
    return await _read(db, user, request_id, "rules")


@router.post("/request", status_code=201, summary="Ask for a tool to be run for a client: creates an approval request, runs nothing")
async def make_request(body: RequestIn, user: Annotated[AuthUser, Depends(require_permission("cases:write"))], db: DBSession) -> dict[str, Any]:
    scope, names = await _scope(db, user.tenant_id, body.client_id)
    if body.client_id not in scope or body.client_id not in names:
        raise HTTPException(status_code=404, detail="Client not found")
    tool, args, why = tb.check_request(body.tool, body.args)
    if why or tool is None:
        raise HTTPException(status_code=422, detail=why or "That request cannot be made.")
    client = names[body.client_id]
    secrets = {f.key for f in tool.fields if f.kind == "secret" and f.key in args}
    title, summary = tb.approval_text(tool, client, args)
    row = AgentApproval(
        tenant_id=user.tenant_id,
        requested_by=f"toolbox:{user.email}"[:120],
        title=title,
        summary=summary,
        risk_level=tool.risk,
        # A secret (a typed password) is kept encrypted, named in secret_args, and never written to the summary or the audit.
        action={
            "kind": "toolbox",
            "tool": tool.id,
            "client_id": str(body.client_id),
            "client": client,
            "args": {k: (get_vault().encrypt(v) if k in secrets else v) for k, v in args.items()},
            "secret_args": sorted(secrets),
        },
        expires_at=datetime.now(UTC) + EXPIRES_AFTER,
        status="pending",
    )
    db.add(row)
    await db.flush()
    await emit_audit(db=db, tenant_id=user.tenant_id, actor_id=user.user_id, action="toolbox:request", resource="agent_approval", resource_id=str(row.id), changes={"tool": tool.id, "client": client})
    await db.commit()
    return {"approval_id": str(row.id), "status": "pending", "title": title, "risk": tool.risk, "note": "Recorded. Nothing has been run yet."}

"""The employee toolbox (roadmap rw-toolbox): list the Microsoft 365 tools and make a request for one, which is queued for CORE to run through CIPP.

Read the tools with ``alerts:read``; make a request with ``cases:write`` (the person confirms on the page first). The request is a ``toolbox_run`` vendor action for CORE in the client's own tenant, naming the
tool and its values (a typed password is never queued); CORE runs it under its CIPP safety rules, opens or updates the ticket and reports what happened, shown on ``GET /toolbox/requests``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import _as, _scope
from app.api.v1.endpoints.identity_actions import cipp_customer
from app.api.v1.endpoints.identity_halo_user import halo_client
from app.db.rls_scope import cross_tenant_reads
from app.models.vendor_action import VendorAction
from app.models.signin import IdentityMfaUser
from app.services import core_lookup as lk
from app.services import toolbox as tb
from app.services.audit import emit_audit
from app.services.identity_people import MICROSOFT

router = APIRouter(prefix="/toolbox", tags=["toolbox"])

MAX_LOOKUP_ROWS = 5000

RECENT_FOR = timedelta(days=14)
RECENT_LIMIT = 40


class RequestIn(BaseModel):
    tool: str = Field(min_length=1, max_length=40)
    client_id: uuid.UUID
    args: dict[str, Any] = Field(default_factory=dict)


@router.get("/tools", summary="The Microsoft 365 tools a technician can ask for, in groups")
async def tools(user: Annotated[AuthUser, Depends(require_permission("alerts:read"))]) -> dict[str, Any]:
    return {"groups": list(tb.GROUPS), "tools": tb.catalog(), "stage": "A request is queued for CORE, which runs it through CIPP and writes the result into the ticket."}


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


@router.post("/request", status_code=202, summary="Ask for a tool to be run for a client: queued for CORE, which does it through CIPP and writes the result into the ticket")
async def make_request(body: RequestIn, user: Annotated[AuthUser, Depends(require_permission("cases:write"))], db: DBSession) -> dict[str, Any]:
    scope, names = await _scope(db, user.tenant_id, body.client_id)
    if body.client_id not in scope or body.client_id not in names or body.client_id == user.tenant_id:
        raise HTTPException(status_code=404, detail="Client not found")
    tool, args, why = tb.check_request(body.tool, body.args)
    if why or tool is None:
        raise HTTPException(status_code=422, detail=why or "That request cannot be made.")
    cipp = await cipp_customer(db, user.tenant_id, body.client_id)
    if not cipp:
        raise HTTPException(status_code=409, detail="This client is not linked to CIPP (Settings, Client mapping), so there is no Microsoft 365 tenant to work in.")
    halo = await halo_client(db, user.tenant_id, body.client_id)
    if not halo and not args.get("ticket"):
        raise HTTPException(status_code=409, detail="This client is not linked to a HaloPSA client, so a new ticket cannot be opened. Give an existing ticket number or link the client (Settings, Client mapping).")
    client = names[body.client_id]
    title, _summary = tb.approval_text(tool, client, args)
    now = datetime.now(UTC)
    async with _as(db, user.tenant_id, body.client_id):
        row = VendorAction(
            id=uuid.uuid4(),
            tenant_id=body.client_id,
            alert_id=None,
            vendor="core",
            incident_uid=f"toolbox:{uuid.uuid4().hex[:12]}",
            action=tb.RUN_ACTION,
            params=tb.run_params(tool, client, args, cipp, halo, user.email),
            status="pending",
            requested_by=user.user_id,
            created_at=now,
        )
        db.add(row)
        await db.flush()
        # The audit names the tool and the client only: never the values.
        await emit_audit(db=db, tenant_id=body.client_id, actor_id=user.user_id, action="toolbox:request", resource="vendor_action", resource_id=str(row.id), changes={"tool": tool.id, "client": client})
        await db.commit()
    return {"request_id": str(row.id), "status": "waiting", "title": title, "risk": tool.risk, "note": "Queued. CORE picks it up within a minute, does the work through CIPP and writes the result into the ticket."}


@router.get("/requests", summary="The recent toolbox requests of this company's clients, newest first, with what CORE did")
async def recent_requests(user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> dict[str, Any]:
    scope, names = await _scope(db, user.tenant_id, None)
    async with cross_tenant_reads(db):
        rows = (
            (
                await db.execute(
                    select(VendorAction)
                    .where(VendorAction.tenant_id.in_(list(scope)), VendorAction.vendor == "core", VendorAction.action == tb.RUN_ACTION, VendorAction.created_at >= datetime.now(UTC) - RECENT_FOR)
                    .order_by(VendorAction.created_at.desc())
                    .limit(RECENT_LIMIT)
                )
            )
            .scalars()
            .all()
        )
    return {"requests": [tb.present_run(r, names.get(r.tenant_id)) for r in rows]}

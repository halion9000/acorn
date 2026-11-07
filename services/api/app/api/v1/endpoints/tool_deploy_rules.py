"""Automatic installs: install a tool on the machines that should have it and do not (see ``app/services/tool_deploy_rules.py`` for what a rule does and the safeguards).

A rule names a tool (Huntress, Field Effect or the approved ScreenConnect), for one client or all, with a Windows install script, a Mac install script or both (scripts CORE has switched on). Making and turning off
a rule are audited. Needs ``connectors:write``, like Run script and the other rules. Whether an install starts at once or waits for an approval card is CORE's decision for each script.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.alert_scripts import ScriptOption
from app.api.v1.endpoints.devices import _scope
from app.models.tenant import Tenant
from app.models.tool_deploy_rule import ToolDeployRule
from app.services.alert_script_rules import published
from app.services.audit import emit_audit
from app.services.tool_deploy_rules import TOOL_NAMES

router = APIRouter(prefix="/tool-deploy-rules", tags=["devices"])

MAX_RULES = 30


class DeployRuleIn(BaseModel):
    tool: Literal["huntress", "fieldeffect", "screenconnect"]
    scope: Literal["client", "all"]
    client_id: uuid.UUID | None = None
    windows_script_id: int | None = Field(default=None, ge=1, le=2_000_000_000)
    mac_script_id: int | None = Field(default=None, ge=1, le=2_000_000_000)


class DeployRuleOut(BaseModel):
    id: uuid.UUID
    tool: str
    tool_name: str
    scope: str
    client_id: uuid.UUID | None = None
    client_name: str | None = None
    windows_script: str | None = None
    mac_script: str | None = None
    created_at: datetime
    active: bool


def _out(rule: ToolDeployRule, names: dict[uuid.UUID, str], scripts: dict) -> DeployRuleOut:
    def name_of(script_id: int | None) -> str | None:
        if script_id is None:
            return None
        s = scripts.get(script_id)
        return s.name if s is not None else f"script {script_id} (not switched on in CORE now)"

    return DeployRuleOut(
        id=rule.id,
        tool=rule.tool,
        tool_name=TOOL_NAMES.get(rule.tool, rule.tool),
        scope=rule.scope,
        client_id=rule.client_tenant_id,
        client_name=names.get(rule.client_tenant_id) if rule.client_tenant_id else None,
        windows_script=name_of(rule.windows_script_id),
        mac_script=name_of(rule.mac_script_id),
        created_at=rule.created_at,
        active=rule.revoked_at is None,
    )


async def _names(db: DBSession, owner: uuid.UUID) -> dict[uuid.UUID, str]:
    return {r.id: r.name for r in (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == owner))).all()}


@router.get("/scripts", response_model=list[ScriptOption], summary="The scripts CORE has switched on, to choose from")
async def scripts_to_choose(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession
) -> list[ScriptOption]:
    found = await published(db, current_user.tenant_id)
    return sorted(found.values(), key=lambda s: s.name.lower())


@router.post("", response_model=DeployRuleOut, status_code=status.HTTP_201_CREATED)
async def make_deploy_rule(
    body: DeployRuleIn,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))],
    db: DBSession,
) -> DeployRuleOut:
    """Make a rule: from now on, where the tool is missing on a Windows or Mac machine of the client (or every client), run the matching install script. Nothing runs until CORE collects the request."""
    if body.windows_script_id is None and body.mac_script_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choose a Windows script, a Mac script, or both.")
    if body.scope == "client" and body.client_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choose the client this rule is for.")
    scripts = await published(db, current_user.tenant_id)
    for sid in (body.windows_script_id, body.mac_script_id):
        if sid is not None and sid not in scripts:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="CORE has not switched that script on.")
    client_id = None
    if body.scope == "client":
        await _scope(db, current_user.tenant_id, body.client_id)  # 404 for a client that is not this company's
        if body.client_id == current_user.tenant_id:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Pick a client, not your own organization.")
        client_id = body.client_id
    active = (
        await db.execute(
            select(ToolDeployRule.id).where(ToolDeployRule.tenant_id == current_user.tenant_id, ToolDeployRule.revoked_at.is_(None))
        )
    ).all()
    if len(active) >= MAX_RULES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"At most {MAX_RULES} automatic installs can be active; turn one off first."
        )
    same = (
        (
            await db.execute(
                select(ToolDeployRule).where(
                    ToolDeployRule.tenant_id == current_user.tenant_id,
                    ToolDeployRule.revoked_at.is_(None),
                    ToolDeployRule.tool == body.tool,
                    ToolDeployRule.scope == body.scope,
                    ToolDeployRule.client_tenant_id == client_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if same is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="There is already an automatic install of this tool for that place."
        )
    rule = ToolDeployRule(
        id=uuid.uuid4(),
        tenant_id=current_user.tenant_id,
        tool=body.tool,
        scope=body.scope,
        client_tenant_id=client_id,
        windows_script_id=body.windows_script_id,
        mac_script_id=body.mac_script_id,
        created_by=current_user.user_id,
        created_at=datetime.now(UTC),
    )
    db.add(rule)
    await db.flush()
    await emit_audit(
        db=db,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        action="tool_deploy_rule:created",
        resource="tool_deploy_rule",
        resource_id=str(rule.id),
        changes={
            "tool": body.tool,
            "scope": body.scope,
            "client_id": str(client_id) if client_id else None,
            "windows_script": body.windows_script_id,
            "mac_script": body.mac_script_id,
        },
        request=request,
    )
    await db.commit()
    return _out(rule, await _names(db, current_user.tenant_id), scripts)


@router.get("", response_model=list[DeployRuleOut], dependencies=[Depends(require_permission("alerts:read"))])
async def list_deploy_rules(current_user: AuthUser, db: DBSession) -> list[DeployRuleOut]:
    """The active automatic installs, newest first."""
    rules = (
        (
            await db.execute(
                select(ToolDeployRule)
                .where(ToolDeployRule.tenant_id == current_user.tenant_id, ToolDeployRule.revoked_at.is_(None))
                .order_by(ToolDeployRule.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    names = await _names(db, current_user.tenant_id)
    scripts = await published(db, current_user.tenant_id)
    return [_out(r, names, scripts) for r in rules]


@router.delete("/{rule_id}", response_model=DeployRuleOut)
async def turn_off_deploy_rule(
    rule_id: uuid.UUID,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))],
    db: DBSession,
) -> DeployRuleOut:
    """Turn a rule off. Requests already queued or run stay; no new ones are made."""
    rule = (
        await db.execute(select(ToolDeployRule).where(ToolDeployRule.id == rule_id, ToolDeployRule.tenant_id == current_user.tenant_id))
    ).scalar_one_or_none()
    if rule is None or rule.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such active rule")
    rule.revoked_at = datetime.now(UTC)
    await emit_audit(
        db=db,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        action="tool_deploy_rule:turned_off",
        resource="tool_deploy_rule",
        resource_id=str(rule.id),
        changes={"tool": rule.tool, "scope": rule.scope},
        request=request,
    )
    await db.commit()
    return _out(rule, await _names(db, current_user.tenant_id), await published(db, current_user.tenant_id))

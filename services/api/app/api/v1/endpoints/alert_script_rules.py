"""Script rules: run a script automatically for every alert of a type, choosing it by the machine's operating system (see ``app/services/alert_script_rules.py`` for what a rule does and the safeguards).

A rule is made from an alert ("run a script for alerts like this"), for that alert's client or for all clients, with a Windows script, a Mac script or both (the scripts CORE has switched on), and can be turned off.
Making and turning off a rule are audited. Needs ``connectors:write``, like Run script and the ticket rules. Whether a run starts at once or waits for an approval card is CORE's decision for each script.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.db.rls import TenantDBSession
from app.models.alert import Alert
from app.models.alert_script_rule import AlertScriptRule
from app.models.tenant import Tenant
from app.services.alert_scope import alert_scope
from app.services.alert_script_rules import TOOLS, published, queue_for_rule
from app.services.alert_suppression import signature_of, source_of
from app.services.audit import emit_audit

router = APIRouter(prefix="/alert-script-rules", tags=["alerts"])

MAX_RULES = 100


class ScriptRuleIn(BaseModel):
    alert_id: uuid.UUID
    scope: Literal["client", "all"]
    windows_script_id: int | None = Field(default=None, ge=1, le=2_000_000_000)
    mac_script_id: int | None = Field(default=None, ge=1, le=2_000_000_000)
    requires_tool: Literal["screenconnect", "huntress", "fieldeffect", "ninjaone", "addigy"] | None = None


class ScriptRuleOut(BaseModel):
    id: uuid.UUID
    scope: str
    client_id: uuid.UUID | None = None
    client_name: str | None = None
    source: str | None = None
    title: str
    windows_script: str | None = None
    mac_script: str | None = None
    requires_tool: str | None = None
    created_at: datetime
    active: bool
    queued_now: int = 0


def _out(rule: AlertScriptRule, names: dict[uuid.UUID, str], scripts: dict, queued_now: int = 0) -> ScriptRuleOut:
    def name_of(script_id: int | None) -> str | None:
        if script_id is None:
            return None
        s = scripts.get(script_id)
        return s.name if s is not None else f"script {script_id} (not switched on in CORE now)"

    return ScriptRuleOut(
        id=rule.id,
        scope=rule.scope,
        client_id=rule.client_tenant_id,
        client_name=names.get(rule.client_tenant_id) if rule.client_tenant_id else None,
        source=rule.source,
        title=rule.title,
        windows_script=name_of(rule.windows_script_id),
        mac_script=name_of(rule.mac_script_id),
        requires_tool=rule.requires_tool,
        created_at=rule.created_at,
        active=rule.revoked_at is None,
        queued_now=queued_now,
    )


async def _names(db: DBSession, owner: uuid.UUID) -> dict[uuid.UUID, str]:
    return {r.id: r.name for r in (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == owner))).all()}


@router.post("", response_model=ScriptRuleOut, status_code=status.HTTP_201_CREATED)
async def make_script_rule(
    body: ScriptRuleIn,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))],
    db: TenantDBSession,
) -> ScriptRuleOut:
    """Make a rule from an alert: from now on every alert of its type (for its client, or for all clients) on a Windows or Mac machine runs the matching script; this alert runs it now."""
    if body.windows_script_id is None and body.mac_script_id is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choose a Windows script, a Mac script, or both.")
    scripts = await published(db, current_user.tenant_id)
    for sid in (body.windows_script_id, body.mac_script_id):
        if sid is not None and sid not in scripts:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="CORE has not switched that script on.")
    now = datetime.now(UTC)
    async with alert_scope(db, current_user.tenant_id, body.alert_id) as tid:
        alert = (await db.execute(select(Alert).where(Alert.id == body.alert_id, Alert.tenant_id == tid))).scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        signature = signature_of(alert.rule_id, alert.title)
        source = source_of(alert.raw_event, alert.connector_type)
        title = ((alert.rule_name if alert.rule_id and alert.rule_name else alert.title) or "")[:500]
    active = (
        await db.execute(
            select(AlertScriptRule.id).where(AlertScriptRule.tenant_id == current_user.tenant_id, AlertScriptRule.revoked_at.is_(None))
        )
    ).all()
    if len(active) >= MAX_RULES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"At most {MAX_RULES} script rules can be active; turn one off first."
        )
    same = (
        (
            await db.execute(
                select(AlertScriptRule).where(
                    AlertScriptRule.tenant_id == current_user.tenant_id,
                    AlertScriptRule.revoked_at.is_(None),
                    AlertScriptRule.signature == signature,
                    AlertScriptRule.source == source,
                    AlertScriptRule.scope == body.scope,
                    AlertScriptRule.client_tenant_id == (tid if body.scope == "client" else None),
                )
            )
        )
        .scalars()
        .first()
    )
    if same is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There is already a script rule for this type of alert here.")
    rule = AlertScriptRule(
        id=uuid.uuid4(),
        tenant_id=current_user.tenant_id,
        scope=body.scope,
        client_tenant_id=tid if body.scope == "client" else None,
        source=source,
        signature=signature,
        title=title,
        windows_script_id=body.windows_script_id,
        mac_script_id=body.mac_script_id,
        requires_tool=body.requires_tool,
        created_by=current_user.user_id,
        created_at=now,
    )
    db.add(rule)
    await db.flush()
    queued = await queue_for_rule(db, rule, scripts, now, source_alert_id=body.alert_id)
    await emit_audit(
        db=db,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        action="alert_script_rule:created",
        resource="alert_script_rule",
        resource_id=str(rule.id),
        changes={
            "title": title[:200],
            "scope": body.scope,
            "source": source,
            "windows_script": body.windows_script_id,
            "mac_script": body.mac_script_id,
            "requires_tool": body.requires_tool,
            "queued_now": queued,
        },
        request=request,
    )
    await db.commit()
    return _out(rule, await _names(db, current_user.tenant_id), scripts, queued)


@router.get("", response_model=list[ScriptRuleOut], dependencies=[Depends(require_permission("alerts:read"))])
async def list_script_rules(current_user: AuthUser, db: DBSession) -> list[ScriptRuleOut]:
    """The active script rules, newest first."""
    rules = (
        (
            await db.execute(
                select(AlertScriptRule)
                .where(AlertScriptRule.tenant_id == current_user.tenant_id, AlertScriptRule.revoked_at.is_(None))
                .order_by(AlertScriptRule.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    names = await _names(db, current_user.tenant_id)
    scripts = await published(db, current_user.tenant_id)
    return [_out(r, names, scripts) for r in rules]


@router.delete("/{rule_id}", response_model=ScriptRuleOut)
async def turn_off_script_rule(
    rule_id: uuid.UUID,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))],
    db: DBSession,
) -> ScriptRuleOut:
    """Turn a rule off. Requests already queued or run stay; no new ones are made for the type."""
    rule = (
        await db.execute(select(AlertScriptRule).where(AlertScriptRule.id == rule_id, AlertScriptRule.tenant_id == current_user.tenant_id))
    ).scalar_one_or_none()
    if rule is None or rule.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such active rule")
    rule.revoked_at = datetime.now(UTC)
    await emit_audit(
        db=db,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        action="alert_script_rule:turned_off",
        resource="alert_script_rule",
        resource_id=str(rule.id),
        changes={"title": rule.title[:200], "scope": rule.scope},
        request=request,
    )
    await db.commit()
    return _out(rule, await _names(db, current_user.tenant_id), await published(db, current_user.tenant_id))


@router.get("/tools", response_model=list[str])
async def tools_a_rule_may_require(_: Annotated[AuthUser, Depends(require_permission("alerts:read"))]) -> list[str]:
    """The tools a rule may require a client to already use."""
    return list(TOOLS)

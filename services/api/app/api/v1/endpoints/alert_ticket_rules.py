"""Ticket rules: open a HaloPSA ticket automatically for every alert of a type (see ``app/services/alert_ticket_rules.py`` for what a rule does and the safeguards).

A rule is made from an alert ("make a ticket for alerts like this"), for that alert's client or for all clients, and can be turned off. It covers alerts raised after it was made and the alert it was
made from. Making and turning off a rule are audited. Needs ``connectors:write``, like the other things that make CORE act on a client's behalf.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.alert_quarantine_release import _actions, check_state_of
from app.db.rls import TenantDBSession
from app.models.alert import Alert
from app.models.alert_ticket_rule import AlertTicketRule
from app.models.tenant import Tenant
from app.services.alert_scope import alert_scope
from app.services.alert_status import FINISHED_ALERT_STATUSES
from app.services.alert_suppression import signature_of, source_of
from app.services.alert_ticket_rules import ACTION as TICKET_ACTION
from app.services.alert_ticket_rules import has_ticket, queue_for_rule, rule_covers
from app.services.audit import emit_audit

router = APIRouter(prefix="/alert-ticket-rules", tags=["alerts"])

MAX_RULES = 200


class TicketRuleIn(BaseModel):
    alert_id: uuid.UUID
    scope: Literal["client", "all"]
    # Also open tickets, once, for the alerts of this type that are already open and have none (at most CATCH_UP_MAX, newest first). A rule alone covers only alerts raised after it was made.
    catch_up: bool = True


class TicketRuleOut(BaseModel):
    id: uuid.UUID
    scope: str
    client_id: uuid.UUID | None = None
    client_name: str | None = None
    source: str | None = None
    title: str
    created_at: datetime
    active: bool
    # Tickets requested because of the rule the moment it was made (the alert it was made from); later ones are not counted here.
    queued_now: int = 0


def _out(rule: AlertTicketRule, names: dict[uuid.UUID, str], queued_now: int = 0) -> TicketRuleOut:
    return TicketRuleOut(
        id=rule.id,
        scope=rule.scope,
        client_id=rule.client_tenant_id,
        client_name=names.get(rule.client_tenant_id) if rule.client_tenant_id else None,
        source=rule.source,
        title=rule.title,
        created_at=rule.created_at,
        active=rule.revoked_at is None,
        queued_now=queued_now,
    )


async def _names(db: DBSession, owner: uuid.UUID) -> dict[uuid.UUID, str]:
    return {r.id: r.name for r in (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == owner))).all()}


@router.post("", response_model=TicketRuleOut, status_code=status.HTTP_201_CREATED)
async def make_ticket_rule(
    body: TicketRuleIn,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))],
    db: TenantDBSession,
) -> TicketRuleOut:
    """Make a rule from an alert: every alert of its type (for its client, or for all clients) from now on gets a HaloPSA ticket, and this alert gets one now if it has none."""
    now = datetime.now(UTC)
    async with alert_scope(db, current_user.tenant_id, body.alert_id) as tid:
        alert = (await db.execute(select(Alert).where(Alert.id == body.alert_id, Alert.tenant_id == tid))).scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        signature = signature_of(alert.rule_id, alert.title)
        source = source_of(alert.raw_event, alert.connector_type)
        # What the list shows: the alert TYPE's name when the tool gave one ("ScreenConnect for another server"), not one device's title.
        title = ((alert.rule_name if alert.rule_id and alert.rule_name else alert.title) or "")[:500]
    count = len(
        (
            await db.execute(
                select(AlertTicketRule.id).where(AlertTicketRule.tenant_id == current_user.tenant_id, AlertTicketRule.revoked_at.is_(None))
            )
        ).all()
    )
    if count >= MAX_RULES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"At most {MAX_RULES} ticket rules can be active; turn one off first."
        )
    same = (
        (
            await db.execute(
                select(AlertTicketRule).where(
                    AlertTicketRule.tenant_id == current_user.tenant_id,
                    AlertTicketRule.revoked_at.is_(None),
                    AlertTicketRule.signature == signature,
                    AlertTicketRule.source == source,
                    AlertTicketRule.scope == body.scope,
                    AlertTicketRule.client_tenant_id == (tid if body.scope == "client" else None),
                )
            )
        )
        .scalars()
        .first()
    )
    if same is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There is already a ticket rule for this type of alert here.")
    rule = AlertTicketRule(
        id=uuid.uuid4(),
        tenant_id=current_user.tenant_id,
        scope=body.scope,
        client_tenant_id=tid if body.scope == "client" else None,
        source=source,
        signature=signature,
        title=title,
        created_by=current_user.user_id,
        created_at=now,
    )
    db.add(rule)
    await db.flush()
    queued = await queue_for_rule(db, rule, now, source_alert_id=body.alert_id, catch_up=body.catch_up)
    await emit_audit(
        db=db,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        action="alert_ticket_rule:created",
        resource="alert_ticket_rule",
        resource_id=str(rule.id),
        changes={"title": title[:200], "scope": body.scope, "source": source, "queued_now": queued, "catch_up": body.catch_up},
        request=request,
    )
    await db.commit()
    return _out(rule, await _names(db, current_user.tenant_id), queued)


@router.get("", response_model=list[TicketRuleOut], dependencies=[Depends(require_permission("alerts:read"))])
async def list_ticket_rules(current_user: AuthUser, db: DBSession) -> list[TicketRuleOut]:
    """The active ticket rules, newest first."""
    rules = (
        (
            await db.execute(
                select(AlertTicketRule)
                .where(AlertTicketRule.tenant_id == current_user.tenant_id, AlertTicketRule.revoked_at.is_(None))
                .order_by(AlertTicketRule.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    names = await _names(db, current_user.tenant_id)
    return [_out(r, names) for r in rules]


@router.delete("/{rule_id}", response_model=TicketRuleOut)
async def turn_off_ticket_rule(
    rule_id: uuid.UUID,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))],
    db: DBSession,
) -> TicketRuleOut:
    """Turn a rule off. Tickets already requested or opened stay; no new ones are made for the type."""
    rule = (
        await db.execute(select(AlertTicketRule).where(AlertTicketRule.id == rule_id, AlertTicketRule.tenant_id == current_user.tenant_id))
    ).scalar_one_or_none()
    if rule is None or rule.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such active rule")
    rule.revoked_at = datetime.now(UTC)
    await emit_audit(
        db=db,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        action="alert_ticket_rule:turned_off",
        resource="alert_ticket_rule",
        resource_id=str(rule.id),
        changes={"title": rule.title[:200], "scope": rule.scope},
        request=request,
    )
    await db.commit()
    return _out(rule, await _names(db, current_user.tenant_id))


class TicketStatusOut(BaseModel):
    # has_ticket: nothing to say (the ticket is shown with the alert); waiting: a ticket is being opened; done / failed: what CORE reported; rule_will_open: a rule covers the alert and its request is due;
    # older_than_rule: a rule covers the type but the alert was raised before it was made; none: no rule covers it.
    state: Literal["has_ticket", "waiting", "done", "failed", "rule_will_open", "older_than_rule", "none"]
    message: str | None = None
    rule_title: str | None = None


@router.get("/alert/{alert_id}/status", response_model=TicketStatusOut)
async def ticket_status_for_alert(
    alert_id: uuid.UUID, user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: TenantDBSession
) -> TicketStatusOut:
    """Why an alert has, or has not got, a ticket from a ticket rule: waiting for CORE, opened, failed (with CORE's reason), covered but older than the rule, or not covered. Read only."""
    now = datetime.now(UTC)
    async with alert_scope(db, user.tenant_id, alert_id) as tid:
        alert = (await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tid))).scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        ticketed = has_ticket(alert.enrichment_data)
        finished = alert.status in FINISHED_ALERT_STATUSES
        fields = {"rule_id": alert.rule_id, "title": alert.title, "source": source_of(alert.raw_event, alert.connector_type), "created_at": alert.created_at}
        state, said, _ = check_state_of(await _actions(db, tid, alert_id, TICKET_ACTION), now)
    if ticketed:
        return TicketStatusOut(state="has_ticket")
    if state in ("pending", "claimed"):
        return TicketStatusOut(state="waiting", message="A ticket is being opened for this alert (CORE collects the request within about a minute).")
    if state == "failed":
        return TicketStatusOut(state="failed", message=said or "CORE did not say why.")
    if state == "done":
        return TicketStatusOut(state="done", message=said)
    if finished:
        return TicketStatusOut(state="none")
    rules = (
        (await db.execute(select(AlertTicketRule).where(AlertTicketRule.tenant_id == user.tenant_id, AlertTicketRule.revoked_at.is_(None)).order_by(AlertTicketRule.created_at.desc())))
        .scalars()
        .all()
    )
    for rule in rules:
        if rule_covers(rule, tenant_id=tid, alert_id=alert_id, **fields):
            return TicketStatusOut(state="rule_will_open", rule_title=rule.title, message="A ticket rule covers this alert; its ticket is requested within a few minutes.")
    for rule in rules:
        if rule_covers(rule, tenant_id=tid, alert_id=alert_id, catch_up=True, **fields):
            return TicketStatusOut(
                state="older_than_rule",
                rule_title=rule.title,
                message="A ticket rule covers this type of alert, but this alert was raised before the rule was made, so it got no ticket.",
            )
    return TicketStatusOut(state="none")

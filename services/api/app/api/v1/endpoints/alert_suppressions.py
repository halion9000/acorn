"""Hide an alert type: for one device, one client or everyone, for a number of days or without end.

``POST /alert-suppressions`` is made from an alert (the button on the alert page). ``GET`` lists the rules and how many alerts each hides. ``DELETE /{id}`` lifts a rule and puts its alerts back as they were.
Needs ``alerts:write``. Hiding is a view decision about noise; it never closes, deletes or changes an alert's data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.models.alert import Alert
from app.models.alert_suppression import AlertSuppression
from app.models.tenant import Tenant
from app.services.alert_scope import alert_scope
from app.services.alert_suppression import (
    MAX_DAYS,
    SUGGEST_AFTER,
    SUGGEST_WINDOW_DAYS,
    _type_filter,
    should_suggest_hiding,
    MAX_WINDOW_HOURS,
    WINDOW_SIGNATURE,
    SUPPRESSED,
    apply_rule,
    expiry_from_days,
    host_keys,
    is_active,
    release_rule,
    signature_of,
    source_of,
)
from app.services.device_identity import hostname_key

router = APIRouter(prefix="/alert-suppressions", tags=["alerts"])

DEFAULT_LIMIT = 500
MAX_LIMIT = 2000


class SuppressionIn(BaseModel):
    alert_id: uuid.UUID
    scope: Literal["device", "client", "all"]
    # Hide for this many days; leave out to hide without end.
    days: int | None = Field(default=None, description=f"1 to {MAX_DAYS} days, or leave out to hide without end")
    # For a device rule on an alert that names several machines: which one. Defaults to the alert's only machine.
    device: str | None = Field(default=None, max_length=255)


class SuppressionOut(BaseModel):
    id: uuid.UUID
    scope: str
    client_id: uuid.UUID | None = None
    client_name: str | None = None
    device: str | None = None
    source: str | None = None
    title: str
    expires_at: datetime | None = None
    starts_at: datetime | None = None
    maintenance: bool = False
    indefinite: bool
    created_at: datetime
    active: bool
    # None when the count could not be read: "hides 0 alerts" would be a statement of fact the page could not back up.
    hidden_alerts: int | None = 0


def _out(rule: AlertSuppression, now: datetime, names: dict[uuid.UUID, str], hidden: int | None) -> SuppressionOut:
    return SuppressionOut(
        id=rule.id,
        scope=rule.scope,
        client_id=rule.client_tenant_id,
        client_name=names.get(rule.client_tenant_id) if rule.client_tenant_id else None,
        device=rule.device_key,
        source=rule.source,
        title=rule.title,
        expires_at=rule.expires_at,
        starts_at=rule.starts_at,
        maintenance=rule.signature == WINDOW_SIGNATURE,
        indefinite=rule.expires_at is None,
        created_at=rule.created_at,
        active=is_active(rule, now),
        hidden_alerts=hidden,
    )


@router.post(
    "", response_model=SuppressionOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("alerts:write"))]
)
async def hide_alert_type(body: SuppressionIn, user: AuthUser, db: DBSession) -> SuppressionOut:
    """Hide this alert's type for the device, its client, or all clients, and hide the open alerts of that type right away."""
    now = datetime.now(UTC)
    expires = expiry_from_days(body.days, now)
    async with alert_scope(db, user.tenant_id, body.alert_id) as tid:
        alert = (await db.execute(select(Alert).where(Alert.id == body.alert_id, Alert.tenant_id == tid))).scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        device_key = None
        if body.scope == "device":
            keys = host_keys(alert.affected_hosts)
            wanted = hostname_key(body.device) if body.device else ""
            if wanted:
                if wanted not in keys:
                    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That device is not one this alert names")
                device_key = wanted
            elif len(keys) == 1:
                device_key = next(iter(keys))
            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="This alert names no device, or several: say which one" if keys else "This alert names no device to hide it for",
                )
        title = alert.title
        signature = signature_of(alert.rule_id, alert.title)
        source = source_of(alert.raw_event, alert.connector_type)
    rule = AlertSuppression(
        tenant_id=user.tenant_id,
        scope=body.scope,
        client_tenant_id=None if body.scope == "all" else tid,
        device_key=device_key,
        source=source,
        signature=signature,
        title=title[:500],
        expires_at=expires,
        created_by=user.user_id,
    )
    db.add(rule)
    await db.flush()
    hidden = await apply_rule(db, rule, user.tenant_id)
    await db.commit()
    names = {
        r.id: r.name for r in (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == user.tenant_id))).all()
    }
    return _out(rule, now, names, hidden)


class MaintenanceIn(BaseModel):
    client_id: uuid.UUID
    hours: int = Field(ge=1, le=MAX_WINDOW_HOURS, description=f"1 to {MAX_WINDOW_HOURS} hours")
    # When it starts; leave out to start now. May not be in the past by more than a few minutes, nor more than 30 days away.
    starts_at: datetime | None = None
    reason: str = Field(default="", max_length=200)


@router.post(
    "/maintenance",
    response_model=SuppressionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("alerts:write"))],
    summary="Hide a client's alerts during planned maintenance",
)
async def start_maintenance(body: MaintenanceIn, user: AuthUser, db: DBSession) -> SuppressionOut:
    """A maintenance window: every open and new alert of the client, except critical ones, is hidden from the start to the end (at most 72 hours) and comes back when it ends. Lift it early with DELETE."""
    now = datetime.now(UTC)
    starts = body.starts_at or now
    if starts.tzinfo is None:
        starts = starts.replace(tzinfo=UTC)
    if starts < now - timedelta(minutes=5):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The window cannot start in the past")
    if starts > now + timedelta(days=30):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The window cannot start more than 30 days from now")
    kids = {r.id: r.name for r in (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == user.tenant_id))).all()}
    if body.client_id != user.tenant_id and body.client_id not in kids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    rule = AlertSuppression(
        tenant_id=user.tenant_id,
        scope="client",
        client_tenant_id=body.client_id,
        source=None,
        signature=WINDOW_SIGNATURE,
        title=(f"Maintenance: {body.reason.strip()}" if body.reason.strip() else "Maintenance window")[:500],
        starts_at=starts,
        expires_at=starts + timedelta(hours=body.hours),
        created_by=user.user_id,
    )
    db.add(rule)
    await db.flush()
    hidden = await apply_rule(db, rule, user.tenant_id) if starts <= now else 0
    await db.commit()
    return _out(rule, now, kids, hidden)


class HideSuggestion(BaseModel):
    suggest: bool
    false_positives: int  # how many alerts of this type were closed as false positive for this client in the last SUGGEST_WINDOW_DAYS days
    threshold: int = SUGGEST_AFTER
    days: int = SUGGEST_WINDOW_DAYS


@router.get(
    "/suggestion",
    response_model=HideSuggestion,
    dependencies=[Depends(require_permission("alerts:read"))],
    summary="Whether hiding this alert's type is worth suggesting (it was closed as a false positive several times)",
)
async def hide_suggestion(alert_id: uuid.UUID, user: AuthUser, db: DBSession) -> HideSuggestion:
    """Counts the alerts of the same type, for the same client, closed as a false positive in the last 90 days. Three or more, and no rule hiding the type already, is worth suggesting. It suggests; it hides nothing."""
    now = datetime.now(UTC)
    async with alert_scope(db, user.tenant_id, alert_id) as tid:
        alert = (await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tid))).scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        signature = signature_of(alert.rule_id, alert.title)
        count = (
            await db.execute(
                select(func.count())
                .select_from(Alert)
                .where(
                    Alert.tenant_id == tid,
                    or_(Alert.status == "false_positive", Alert.disposition == "false_positive"),  # a single close sets the status, a bulk close also the verdict
                    Alert.resolved_at >= now - timedelta(days=SUGGEST_WINDOW_DAYS),
                    _type_filter(SimpleNamespace(signature=signature)),
                )
            )
        ).scalar_one()
    hiding = (
        await db.execute(
            select(func.count())
            .select_from(AlertSuppression)
            .where(
                AlertSuppression.signature == signature,
                AlertSuppression.revoked_at.is_(None),
                or_(AlertSuppression.expires_at.is_(None), AlertSuppression.expires_at > now),
                or_(AlertSuppression.starts_at.is_(None), AlertSuppression.starts_at <= now),
                or_(AlertSuppression.scope == "all", AlertSuppression.client_tenant_id == tid),
                AlertSuppression.tenant_id == user.tenant_id,
            )
        )
    ).scalar_one()
    return HideSuggestion(suggest=should_suggest_hiding(int(count), int(hiding) > 0), false_positives=int(count))


@router.get("", response_model=list[SuppressionOut], dependencies=[Depends(require_permission("alerts:read"))])
async def list_suppressions(
    user: AuthUser,
    db: DBSession,
    response: Response,
    include_ended: bool = False,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> list[SuppressionOut]:
    """The active rules (and, with ``include_ended``, those lifted or run out), newest first, with how many alerts each hides now (null when that could not be counted).

    ``X-Total-Count`` says how many rules match in all, so a list cut at ``limit`` is known to be cut (it used to stop at 500 without saying so).
    """
    now = datetime.now(UTC)
    where = [AlertSuppression.tenant_id == user.tenant_id]
    if not include_ended:
        where.append(AlertSuppression.revoked_at.is_(None))
    total = (await db.execute(select(func.count()).select_from(AlertSuppression).where(*where))).scalar_one()
    response.headers["X-Total-Count"] = str(int(total))
    q = select(AlertSuppression).where(*where).order_by(AlertSuppression.created_at.desc(), AlertSuppression.id).offset(offset).limit(limit)
    rules = list((await db.execute(q)).scalars().all())
    names = {
        r.id: r.name for r in (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == user.tenant_id))).all()
    }
    counts: dict[uuid.UUID, int] = {}
    failed: set[uuid.UUID] = set()  # the clients whose count could not be read
    for tid in {r.client_tenant_id or user.tenant_id for r in rules} | {user.tenant_id, *names}:
        try:
            rows = (
                await db.execute(
                    select(Alert.suppression_id, func.count())
                    .where(Alert.tenant_id == tid, Alert.status == SUPPRESSED)
                    .group_by(Alert.suppression_id)
                )
            ).all()
        except Exception:  # noqa: BLE001 - one client's count failing must not fail the list, but it must not read as zero either
            failed.add(tid)
            continue
        for sid, n in rows:
            if sid is not None:
                counts[sid] = counts.get(sid, 0) + int(n)

    def counted(rule: AlertSuppression) -> int | None:
        covered = {rule.client_tenant_id} if rule.client_tenant_id else {user.tenant_id, *names}
        return None if covered & failed else counts.get(rule.id, 0)

    return [_out(r, now, names, counted(r)) for r in rules]


@router.delete("/{suppression_id}", response_model=SuppressionOut, dependencies=[Depends(require_permission("alerts:write"))])
async def lift_suppression(suppression_id: uuid.UUID, user: AuthUser, db: DBSession) -> SuppressionOut:
    """Stop hiding this alert type: its hidden alerts come back with the status they had."""
    rule = (
        await db.execute(
            select(AlertSuppression).where(AlertSuppression.id == suppression_id, AlertSuppression.tenant_id == user.tenant_id)
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such rule")
    restored = 0
    if rule.revoked_at is None:
        restored = await release_rule(db, rule, user.tenant_id)
        rule.revoked_at = datetime.now(UTC)
        rule.revoked_reason = "lifted"
        await db.commit()
    names = {
        r.id: r.name for r in (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == user.tenant_id))).all()
    }
    return _out(rule, datetime.now(UTC), names, restored)

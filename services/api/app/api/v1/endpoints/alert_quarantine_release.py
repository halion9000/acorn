"""Release the quarantined message a "user asked to release a quarantined message" alert is about (see ``app/services/quarantine_release.py``).

A person presses Release and confirms; A.C.O.R.N queues the action for CORE, which asks CIPP to release it. Needs ``identities:respond`` (the same right as blocking an account). Asking is audited, and the
alert records that a release was asked for and how it went. One request for a message at a time, and a message already released is not asked for again.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.v1.deps import AuthUser, require_permission
from app.db.rls import TenantDBSession
from app.models.alert import Alert
from app.models.vendor_action import VendorAction
from app.services.alert_scope import alert_scope
from app.services.audit import emit_audit
from app.services.quarantine_release import ACTION, CHECK_ACTION, ELSEWHERE, VENDOR, quarantine_of
from app.services.vendor_actions import PENDING_TTL

router = APIRouter(prefix="/alerts", tags=["alerts"])


class QuarantineInfo(BaseModel):
    available: bool
    recipient: str | None = None
    sender: str | None = None
    kind: str | None = None
    # none (never asked), pending (waiting for CORE), claimed (CORE is doing it), done (released), failed
    state: str = "none"
    message: str | None = None
    asked_at: datetime | None = None
    # The read-only look at why it was held: none (never asked), pending, claimed, done (check_text says what CORE found) or failed.
    check_state: str = "none"
    check_text: str | None = None
    check_at: datetime | None = None


class ReleaseRequest(BaseModel):
    confirm: bool = False


def state_of(rows: list[Any], now: datetime) -> tuple[str, str | None, datetime | None]:
    """Where a release stands, from the actions asked for this alert, newest first: a finished or running one wins over an older failed one (pure)."""
    for r in rows:
        if r.status == "done":
            return "done", r.result_message, r.created_at
    for r in rows:
        if r.status in ("pending", "claimed"):
            stale = r.status == "pending" and r.created_at is not None and now - r.created_at > PENDING_TTL
            if not stale:
                return r.status, r.result_message, r.created_at
    if rows:
        return "failed", rows[0].result_message, rows[0].created_at
    return "none", None, None


def released_record(enrichment: Any, state: str, said: str | None, asked: datetime | None) -> tuple[str, str | None, datetime | None]:
    """A release the alert records (done from here, or seen released in Microsoft 365 by someone else) settles it as done, in words that say who (pure)."""
    rec = enrichment.get("quarantine_release") if isinstance(enrichment, dict) else None
    if not isinstance(rec, dict):
        return state, said, asked
    by = str(rec.get("by") or "")
    when = str(rec.get("released_at") or "")[:16].replace("T", " ")
    stamp = f" ({when} UTC)" if when else ""
    if by == ELSEWHERE:
        return "done", f"Already released by someone else in Microsoft 365{stamp}.", asked
    return "done", f"Released from A.C.O.R.N{f' by {by}' if by and by != 'A.C.O.R.N' else ''}{stamp}.", asked


def check_state_of(rows: list[Any], now: datetime) -> tuple[str, str | None, datetime | None]:
    """Where the look into why a message was held stands, from the newest request: waiting, running, finished (with CORE's text) or failed (with its reason). A request nobody collected for too long reads as failed (pure)."""
    if not rows:
        return "none", None, None
    r = rows[0]
    if r.status in ("pending", "claimed"):
        if r.status == "pending" and r.created_at is not None and now - r.created_at > PENDING_TTL:
            return "failed", "CORE did not pick the request up in time; ask again.", r.created_at
        return r.status, None, r.created_at
    return ("done" if r.status == "done" else "failed"), r.result_message, r.created_at


async def _actions(db: Any, tid: uuid.UUID, alert_id: uuid.UUID, action: str = ACTION) -> list[Any]:
    return list(
        (
            await db.execute(
                select(VendorAction)
                .where(
                    VendorAction.tenant_id == tid,
                    VendorAction.alert_id == alert_id,
                    VendorAction.vendor == VENDOR,
                    VendorAction.action == action,
                )
                .order_by(VendorAction.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


@router.get("/{alert_id}/quarantine", response_model=QuarantineInfo)
async def quarantine_info(
    alert_id: uuid.UUID, user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: TenantDBSession
) -> QuarantineInfo:
    """Whether this alert is about a quarantined message that can be released from here, who it was for and where a release stands."""
    async with alert_scope(db, user.tenant_id, alert_id) as tid:
        alert = (await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tid))).scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        message = quarantine_of(alert.raw_event)
        if message is None:
            return QuarantineInfo(available=False)
        state, said, asked = state_of(await _actions(db, tid, alert_id), datetime.now(UTC))
        state, said, asked = released_record(alert.enrichment_data, state, said, asked)
        check = check_state_of(await _actions(db, tid, alert_id, CHECK_ACTION), datetime.now(UTC))
    return QuarantineInfo(
        available=True,
        recipient=message["recipient"] or None,
        sender=message["sender"] or None,
        kind=message["kind"] or None,
        state=state,
        message=said,
        asked_at=asked,
        check_state=check[0],
        check_text=check[1],
        check_at=check[2],
    )


@router.post("/{alert_id}/release-quarantine", response_model=QuarantineInfo, status_code=status.HTTP_202_ACCEPTED)
async def release_quarantine(
    alert_id: uuid.UUID,
    body: ReleaseRequest,
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("identities:respond"))],
    db: TenantDBSession,
) -> QuarantineInfo:
    """Ask CORE to release the quarantined message. Returns 202: nothing has happened yet. Needs ``confirm: true``."""
    if not body.confirm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Confirm that the message is safe to release.")
    now = datetime.now(UTC)
    async with alert_scope(db, user.tenant_id, alert_id) as tid:
        alert = (await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tid))).scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        message = quarantine_of(alert.raw_event)
        if message is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="This alert is not about a quarantined message that can be released from here.",
            )
        state, said, asked = state_of(await _actions(db, tid, alert_id), now)
        state, said, asked = released_record(alert.enrichment_data, state, said, asked)
        if state == "done":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This message was already released.")
        if state in ("pending", "claimed"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="A release for this message is already waiting for CORE; let it finish first."
            )
        row = VendorAction(
            id=uuid.uuid4(),
            tenant_id=tid,
            alert_id=alert.id,
            vendor=VENDOR,
            incident_uid=f"quarantine:{message['identity']}"[:200],
            action=ACTION,
            params={
                "client_id": message["client"],
                "quarantine_identity": message["identity"],
                "recipient": message["recipient"],
                "requested_by_name": (getattr(user, "email", None) or "")[:200],
            },
            status="pending",
            requested_by=user.user_id,
            created_at=now,
        )
        db.add(row)
        await db.flush()
        await emit_audit(
            db=db,
            tenant_id=tid,
            actor_id=user.user_id,
            action="alerts:quarantine_release_requested",
            resource="alert",
            resource_id=str(alert.id),
            changes={"vendor_action_id": str(row.id), "recipient": message["recipient"], "sender": message["sender"]},
            request=request,
        )
        await db.commit()
    return QuarantineInfo(
        available=True,
        recipient=message["recipient"] or None,
        sender=message["sender"] or None,
        kind=message["kind"] or None,
        state="pending",
        asked_at=now,
    )


@router.post("/{alert_id}/check-quarantine", response_model=QuarantineInfo, status_code=status.HTTP_202_ACCEPTED)
async def check_quarantine(
    alert_id: uuid.UUID,
    request: Request,
    user: Annotated[AuthUser, Depends(require_permission("identities:respond"))],
    db: TenantDBSession,
) -> QuarantineInfo:
    """Ask CORE to look into why this message was quarantined (read only: its classification and headers through CIPP). Returns 202: nothing is known yet. One request at a time."""
    now = datetime.now(UTC)
    async with alert_scope(db, user.tenant_id, alert_id) as tid:
        alert = (await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tid))).scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        message = quarantine_of(alert.raw_event)
        if message is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This alert is not about a quarantined message.")
        rows = await _actions(db, tid, alert_id, CHECK_ACTION)
        current = check_state_of(rows, now)
        if current[0] in ("pending", "claimed"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="A check for this message is already waiting for CORE; let it finish first."
            )
        db.add(
            VendorAction(
                id=uuid.uuid4(),
                tenant_id=tid,
                alert_id=alert.id,
                vendor=VENDOR,
                incident_uid=f"quarantine:{message['identity']}"[:200],
                action=CHECK_ACTION,
                params={"client_id": message["client"], "quarantine_identity": message["identity"]},
                status="pending",
                requested_by=user.user_id,
                created_at=now,
            )
        )
        await db.flush()
        await emit_audit(
            db=db,
            tenant_id=tid,
            actor_id=user.user_id,
            action="alerts:quarantine_check_requested",
            resource="alert",
            resource_id=str(alert.id),
            changes={"recipient": message["recipient"], "sender": message["sender"]},
            request=request,
        )
        await db.commit()
    return QuarantineInfo(
        available=True,
        recipient=message["recipient"] or None,
        sender=message["sender"] or None,
        kind=message["kind"] or None,
        state="none",
        check_state="pending",
        check_at=now,
    )

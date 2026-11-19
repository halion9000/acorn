"""A command prompt for one machine on the Devices page, through ScreenConnect.

A.C.O.R.N runs nothing and holds no ScreenConnect secret. These routes only QUEUE a request for CORE (a ``vendor_actions`` row for the vendor ``core``, action ``sc_command``); CORE sends the command
through ScreenConnect's RESTful API Manager extension, waits for the machine's answer and reports it as the result, which the prompt reads back. Commands run on the machine as SYSTEM, so asking needs
``connectors:write`` and EVERY command is written to the audit log with its text. One command waits per machine at a time.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import _as, _client_of, _scope
from app.models.device import Device, DeviceSource
from app.models.vendor_action import VendorAction
from app.services.audit import emit_audit
from app.services.vendor_actions import PENDING_TTL

router = APIRouter(prefix="/devices", tags=["devices"])

CONSOLE_VENDOR = "core"
CONSOLE_ACTION = "sc_command"
# A deploy of the NinjaOne agent (devices_ninja_deploy.py) is read back the same way.
CONSOLE_ACTIONS = ("sc_command", "ninja_deploy")
MAX_COMMAND = 1000
HISTORY = 20


class ConsoleIn(BaseModel):
    command: str = Field(min_length=1, max_length=MAX_COMMAND)


class ConsoleLine(BaseModel):
    request_id: uuid.UUID
    command: str
    status: Literal["pending", "claimed", "done", "failed"]
    output: str | None = None
    requested_at: datetime
    finished_at: datetime | None = None


class ConsoleHistory(BaseModel):
    device_id: uuid.UUID
    device: str
    # False when no ScreenConnect record backs this machine, with the reason in `blocked`.
    available: bool
    blocked: str | None = None
    lines: list[ConsoleLine]


def _line(row: VendorAction) -> ConsoleLine:
    params = row.params or {}
    state = row.status
    # A request nobody collected in time is shown as failed, as the queue itself would.
    if state == "pending" and row.created_at < datetime.now(UTC) - PENDING_TTL:
        state = "failed"
    return ConsoleLine(
        request_id=row.id,
        command=str(params.get("command") or ""),
        status=state if state in ("pending", "claimed", "done", "failed") else "failed",
        output=row.result_message,
        requested_at=row.created_at,
        finished_at=row.finished_at,
    )


async def _session_of(db, tid: uuid.UUID, device_id: uuid.UUID) -> str | None:
    found = (
        await db.execute(
            select(DeviceSource.external_id)
            .where(DeviceSource.tenant_id == tid, DeviceSource.device_id == device_id, DeviceSource.vendor == "screenconnect")
            .order_by(DeviceSource.last_seen.desc())
        )
    ).first()
    return str(found[0]) if found else None


@router.get("/{device_id}/console", response_model=ConsoleHistory, summary="The recent commands sent to this machine, with their answers")
async def console_history(
    device_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))], db: DBSession
) -> ConsoleHistory:
    owner = current_user.tenant_id
    tid = await _client_of(db, owner, device_id)
    async with _as(db, owner, tid):
        device = (await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tid))).scalar_one()
        session = await _session_of(db, tid, device_id)
        rows = (
            (
                await db.execute(
                    select(VendorAction)
                    .where(
                        VendorAction.tenant_id == tid,
                        VendorAction.vendor == CONSOLE_VENDOR,
                        VendorAction.action.in_(CONSOLE_ACTIONS),
                        VendorAction.incident_uid.like(f"sc:{device_id}:%"),
                    )
                    .order_by(VendorAction.created_at.desc())
                    .limit(HISTORY)
                )
            )
            .scalars()
            .all()
        )
    return ConsoleHistory(
        device_id=device_id,
        device=device.hostname or "",
        available=session is not None,
        blocked=None if session else "ScreenConnect has no record of this machine, so there is nothing to send a command to.",
        lines=[_line(r) for r in reversed(rows)],
    )


@router.post(
    "/{device_id}/console",
    response_model=ConsoleLine,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send one command to this machine through ScreenConnect",
)
async def console_send(
    device_id: uuid.UUID,
    body: ConsoleIn,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))],
    db: DBSession,
) -> ConsoleLine:
    return await queue_command(db, current_user, request, device_id, body.command)


async def queue_command(db: Any, current_user: Any, request: Any, device_id: uuid.UUID, text: str, label: str = "devices:console_command") -> ConsoleLine:
    """Queue one ScreenConnect command for one machine (also used by the saved scripts). Raises 409 when ScreenConnect has no record of the machine or an earlier command still waits."""
    command = text.strip()
    if not command:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Type a command.")
    owner = current_user.tenant_id
    tid = await _client_of(db, owner, device_id)
    async with _as(db, owner, tid):
        device = (await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tid))).scalar_one()
        session = await _session_of(db, tid, device_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ScreenConnect has no record of this machine.")
        now = datetime.now(UTC)
        waiting = (
            await db.execute(
                select(VendorAction.id).where(
                    VendorAction.tenant_id == tid,
                    VendorAction.vendor == CONSOLE_VENDOR,
                    VendorAction.action.in_(CONSOLE_ACTIONS),
                    VendorAction.status.in_(("pending", "claimed")),
                    VendorAction.created_at > now - PENDING_TTL,
                    VendorAction.incident_uid.like(f"sc:{device_id}:%"),
                )
            )
        ).first()
        if waiting is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A command for this machine is still waiting for an answer.")
        row = VendorAction(
            id=uuid.uuid4(),
            tenant_id=tid,
            alert_id=None,
            incident_uid=f"sc:{device_id}:{uuid.uuid4().hex[:12]}",
            vendor=CONSOLE_VENDOR,
            action=CONSOLE_ACTION,
            params={"session_id": session, "command": command, "device": (device.hostname or "")[:255]},
            status="pending",
            requested_by=current_user.user_id,
            created_at=now,
        )
        db.add(row)
        await db.flush()
        await emit_audit(
            db=db,
            tenant_id=tid,
            actor_id=current_user.user_id,
            action=label,
            resource="device",
            resource_id=str(device_id),
            changes={"device": device.hostname, "command": command[:500]},
            request=request,
        )
        await db.commit()
        return _line(row)


@router.get("/console/{request_id}", response_model=ConsoleLine, summary="One command's state and answer")
async def console_line(
    request_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))], db: DBSession
) -> ConsoleLine:
    owner = current_user.tenant_id
    scope, _ = await _scope(db, owner, None)
    for tid in scope:
        async with _as(db, owner, tid):
            row = (
                await db.execute(
                    select(VendorAction).where(
                        VendorAction.id == request_id,
                        VendorAction.tenant_id == tid,
                        VendorAction.vendor == CONSOLE_VENDOR,
                        VendorAction.action.in_(CONSOLE_ACTIONS),
                    )
                )
            ).scalar_one_or_none()
        if row is not None:
            return _line(row)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such command.")

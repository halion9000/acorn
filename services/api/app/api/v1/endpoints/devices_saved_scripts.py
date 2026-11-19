"""Saved remote scripts (reboot, flush DNS, gpupdate...) sent to machines through ScreenConnect (roadmap r7-cf-04 and r7-cf-05, Hal 2026-11-18).

* Managing the list (add, change, switch off, delete) needs ``connectors:write``, the permission that already guards the free-form console.
* Running needs the new ``scripts:run`` permission, which a role is given on purpose: whoever holds it can send any script that is switched on, and nothing else (no free typing). A run names up to 25 machines
  and each gets its own result line (a machine ScreenConnect does not know, or one still busy with an earlier command, is refused on its own without stopping the others). Every send is audited.
* ``confirm`` must be true: the page asks before sending, and the API refuses a run that did not say it was confirmed.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices_console import ConsoleLine, queue_command
from app.models.remote_script import RemoteScript

router = APIRouter(prefix="/remote-scripts", tags=["devices"])

MAX_MACHINES = 25


class ScriptIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    command: str = Field(min_length=1, max_length=1000)
    enabled: bool = True


class ScriptPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    command: str | None = Field(default=None, min_length=1, max_length=1000)
    enabled: bool | None = None


class ScriptOut(BaseModel):
    id: uuid.UUID
    name: str
    command: str
    enabled: bool


class RunIn(BaseModel):
    device_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_MACHINES)
    confirm: bool = False


class RunResult(BaseModel):
    device_id: uuid.UUID
    line: ConsoleLine | None = None
    refused: str | None = None


def _out(r: RemoteScript) -> ScriptOut:
    return ScriptOut(id=r.id, name=r.name, command=r.command, enabled=r.enabled)


async def _get(db: Any, tenant: uuid.UUID, script_id: uuid.UUID) -> RemoteScript:
    row = (await db.execute(select(RemoteScript).where(RemoteScript.id == script_id, RemoteScript.tenant_id == tenant))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Script not found")
    return row


@router.get("", response_model=list[ScriptOut], summary="The saved scripts (people who may only run them see the ones that are switched on)")
async def list_scripts(current_user: AuthUser, db: DBSession) -> list[ScriptOut]:
    can_manage = current_user.has_permission("connectors:write")
    if not can_manage:
        current_user.require_permission("scripts:run")
    q = select(RemoteScript).where(RemoteScript.tenant_id == current_user.tenant_id).order_by(func.lower(RemoteScript.name))
    if not can_manage:
        q = q.where(RemoteScript.enabled.is_(True))
    return [_out(r) for r in (await db.execute(q)).scalars().all()]


@router.post("", response_model=ScriptOut, status_code=status.HTTP_201_CREATED, summary="Save a script")
async def create_script(body: ScriptIn, current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))], db: DBSession) -> ScriptOut:
    row = RemoteScript(id=uuid.uuid4(), tenant_id=current_user.tenant_id, name=body.name.strip(), command=body.command.strip(), enabled=body.enabled, created_by=getattr(current_user, "email", None))
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A script with that name already exists.") from None
    return _out(row)


@router.patch("/{script_id}", response_model=ScriptOut, summary="Change a script or switch it on or off")
async def patch_script(
    script_id: uuid.UUID, body: ScriptPatch, current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))], db: DBSession
) -> ScriptOut:
    row = await _get(db, current_user.tenant_id, script_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(row, k, v.strip() if isinstance(v, str) else v)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A script with that name already exists.") from None
    return _out(row)


@router.delete("/{script_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a script")
async def delete_script(script_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))], db: DBSession) -> None:
    row = await _get(db, current_user.tenant_id, script_id)
    await db.delete(row)
    await db.commit()


@router.post("/{script_id}/run", response_model=list[RunResult], summary="Send a saved script to up to 25 machines; each machine answers on its own")
async def run_script(
    script_id: uuid.UUID,
    body: RunIn,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("scripts:run"))],
    db: DBSession,
) -> list[RunResult]:
    if not body.confirm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Confirm before sending: this runs on the machines.")
    row = await _get(db, current_user.tenant_id, script_id)
    if not row.enabled:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That script is switched off.")
    command = row.command  # read before any refusal rolls the session back
    out: list[RunResult] = []
    for device_id in dict.fromkeys(body.device_ids):  # each machine once
        try:
            line = await queue_command(db, current_user, request, device_id, command, label="devices:script_run")
            out.append(RunResult(device_id=device_id, line=line))
        except HTTPException as exc:
            await db.rollback()
            out.append(RunResult(device_id=device_id, refused=str(exc.detail)))
    return out

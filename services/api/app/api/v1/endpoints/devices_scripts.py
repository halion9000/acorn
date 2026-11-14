"""Run one of CORE's NinjaOne scripts on several machines picked on the Devices page.

Like the alert page's bulk run (``alert_scripts.py``), A.C.O.R.N runs nothing and holds no NinjaOne or HaloPSA key: these routes only QUEUE requests for CORE (``vendor_actions`` rows for the
vendor ``core``). There is ONE request per machine, each opening its own HaloPSA ticket for the result, all tagged with one batch id so CORE asks its owner ONCE (a script switched to "run at
once" in CORE starts straight away). A machine is asked for once however many lines name it; a line with no name, or one that already has a request waiting, is left out with the reason.

Permission: ``connectors:write`` to ask (it reaches live machines), ``alerts:read`` to see the scripts on offer. Every request is audited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.alert_scripts import SCRIPT_ACTION, SCRIPT_VENDOR, ScriptOption, published_scripts
from app.api.v1.endpoints.devices import _as, _client_of
from app.models.client_alias import ClientAlias
from app.models.device import Device
from app.models.tenant import Tenant
from app.models.vendor_action import VendorAction
from app.services.audit import emit_audit
from app.services.vendor_actions import PENDING_TTL

router = APIRouter(prefix="/devices/scripts", tags=["devices"])

MAX_DEVICES = 200


class DeviceScripts(BaseModel):
    scripts: list[ScriptOption]
    # Why nothing can be run from here, in plain words; None when something can.
    blocked: str | None = None


@router.get("/options", response_model=DeviceScripts, summary="The scripts CORE has switched on, to run on picked devices")
async def device_script_options(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession
) -> DeviceScripts:
    owner = (await db.execute(select(Tenant.settings).where(Tenant.id == current_user.tenant_id))).scalar_one_or_none()
    scripts = published_scripts(owner)
    blocked = None if scripts else "CORE has not shared any scripts. Switch scripts on in CORE under Settings > Manage NinjaOne scripts."
    return DeviceScripts(scripts=scripts, blocked=blocked)


class BulkDeviceRun(BaseModel):
    script_id: int = Field(ge=1, le=2_000_000_000)
    device_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_DEVICES)
    preview: bool = Field(default=False, description="True: say what would be queued, queue nothing.")


class BulkDeviceItem(BaseModel):
    device_id: uuid.UUID
    device: str | None = None
    outcome: Literal["queued", "skipped"]
    reason: str | None = None
    request_id: uuid.UUID | None = None


class BulkDeviceResponse(BaseModel):
    batch_id: str | None = None
    preview: bool
    script_name: str
    runs_at_once: bool
    queued: int
    skipped: int
    items: list[BulkDeviceItem]


async def _halo_client(db: Any, owner: uuid.UUID, tid: uuid.UUID) -> str | None:
    """The HaloPSA client the device's client is mapped to, read in the owner's scope (a client's own scope cannot see the owner's aliases)."""
    found = (
        (
            await db.execute(
                select(ClientAlias.vendor_client_id).where(
                    ClientAlias.tenant_id == owner,
                    ClientAlias.vendor == "halopsa",
                    ClientAlias.child_tenant_id == tid,
                    ClientAlias.ignored.is_(False),
                )
            )
        )
        .scalars()
        .first()
    )
    return str(found) if found else None


@router.post(
    "/run-bulk", response_model=BulkDeviceResponse, status_code=status.HTTP_202_ACCEPTED, summary="Queue one script for each picked device"
)
async def run_script_on_devices(
    body: BulkDeviceRun,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))],
    db: DBSession,
) -> BulkDeviceResponse:
    owner = current_user.tenant_id
    settings = (await db.execute(select(Tenant.settings).where(Tenant.id == owner))).scalar_one_or_none()
    script = next((s for s in published_scripts(settings) if s.id == body.script_id), None)
    if script is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="CORE has not switched that script on.")
    batch_id = None if body.preview else uuid.uuid4().hex
    now = datetime.now(UTC)
    items: list[BulkDeviceItem] = []
    seen: set[tuple[uuid.UUID, str]] = set()
    halo: dict[uuid.UUID, str | None] = {}
    # Machines that already have a request waiting for CORE, per client, so a second press does not stack another.
    waiting: dict[uuid.UUID, set[str]] = {}
    for device_id in dict.fromkeys(body.device_ids):
        try:
            tid = await _client_of(db, owner, device_id)
        except HTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            items.append(BulkDeviceItem(device_id=device_id, outcome="skipped", reason="Device not found."))
            continue
        if tid not in halo:
            halo[tid] = await _halo_client(db, owner, tid)
        async with _as(db, owner, tid):
            device = (await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tid))).scalar_one_or_none()
            if device is None:
                items.append(BulkDeviceItem(device_id=device_id, outcome="skipped", reason="Device not found."))
                continue
            name = (device.hostname or "").strip()[:255]
            if not name:
                items.append(BulkDeviceItem(device_id=device_id, outcome="skipped", reason="This device has no name to run the script on."))
                continue
            if tid not in waiting:
                rows = (
                    (
                        await db.execute(
                            select(VendorAction.params).where(
                                VendorAction.tenant_id == tid,
                                VendorAction.vendor == SCRIPT_VENDOR,
                                VendorAction.action == SCRIPT_ACTION,
                                VendorAction.status.in_(("pending", "claimed")),
                                VendorAction.created_at > now - PENDING_TTL,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                waiting[tid] = {str((p or {}).get("device") or "").lower() for p in rows}
            key = (tid, name.lower())
            if key in seen:
                items.append(
                    BulkDeviceItem(
                        device_id=device_id,
                        device=name,
                        outcome="skipped",
                        reason="Another line in this batch already covers this machine.",
                    )
                )
                continue
            if name.lower() in waiting[tid]:
                items.append(
                    BulkDeviceItem(
                        device_id=device_id,
                        device=name,
                        outcome="skipped",
                        reason="A script request for this machine is already waiting for CORE.",
                    )
                )
                continue
            seen.add(key)
            if batch_id is None:
                items.append(BulkDeviceItem(device_id=device_id, device=name, outcome="queued"))
                continue
            params: dict[str, Any] = {
                "script_id": script.id,
                "script_name": script.name,
                "device": name,
                "batch_id": batch_id,
                "create_ticket": {
                    "summary": f"{script.name}: {name}"[:200],
                    "details": f"Run from the Devices page on {name}."[:3000],
                    **({"halo_client_id": halo[tid]} if halo[tid] else {}),
                },
            }
            row = VendorAction(
                id=uuid.uuid4(),
                tenant_id=tid,
                alert_id=None,
                # No alert behind it: an id with no ``vendor:`` prefix, so CORE does not try to link the new ticket to one.
                incident_uid=f"devicerun-{uuid.uuid4().hex}",
                vendor=SCRIPT_VENDOR,
                action=SCRIPT_ACTION,
                params=params,
                status="pending",
                requested_by=current_user.user_id,
            )
            db.add(row)
            await db.flush()
            await emit_audit(
                db=db,
                tenant_id=tid,
                actor_id=current_user.user_id,
                action="devices:script_requested",
                resource="device",
                resource_id=str(device_id),
                changes={"script": script.name, "device": name, "ticket": "create", "batch": batch_id},
                request=request,
            )
            items.append(BulkDeviceItem(device_id=device_id, device=name, outcome="queued", request_id=row.id))
    # One commit for the whole batch, so CORE sees every request at once and makes one approval card.
    if batch_id is not None:
        await db.commit()
    queued = sum(1 for i in items if i.outcome == "queued")
    return BulkDeviceResponse(
        batch_id=batch_id if queued else None,
        preview=body.preview,
        script_name=script.name,
        runs_at_once=script.one_click,
        queued=queued,
        skipped=len(items) - queued,
        items=items,
    )

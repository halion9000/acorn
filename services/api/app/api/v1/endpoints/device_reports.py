"""Fleet reports from what the tools already tell A.C.O.R.N about each device: Huntress agent versions, network device firmware (Auvik) and devices offline for more than a week.

Read with ``alerts:read``, like the Devices page. Nothing is changed. The newest version is the newest the fleet itself runs: there is no list of the vendors' releases (see ``app.services.device_reports``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import _scope
from app.db.rls_scope import cross_tenant_reads
from app.models.device import Device, DeviceSource
from app.services import device_reports as rep

router = APIRouter(prefix="/device-reports", tags=["devices"])


async def _rows(db: DBSession, owner: uuid.UUID, client_id: uuid.UUID | None, vendor: str) -> list[tuple[Any, ...]]:
    scope, names = await _scope(db, owner, client_id)
    async with cross_tenant_reads(db):
        rows = (
            await db.execute(
                select(DeviceSource.tenant_id, DeviceSource.name, DeviceSource.details, Device.hostname, Device.manufacturer, Device.model)
                .join(Device, Device.id == DeviceSource.device_id)
                .where(DeviceSource.vendor == vendor, DeviceSource.tenant_id.in_(scope))
            )
        ).all()
    return [(names.get(r[0]) or "", r[1] or r[3] or "", r[2] or {}, r[3] or "", r[4] or "", r[5] or "") for r in rows]


@router.get("/huntress-versions", summary="Huntress agent versions across the clients, and the agents more than two releases behind the newest")
async def huntress_versions(
    user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, client_id: uuid.UUID | None = None
) -> dict[str, Any]:
    rows = await _rows(db, user.tenant_id, client_id, "huntress")
    return rep.huntress_versions(
        [{"client": c, "hostname": n, "version": d.get("agent_version"), "last_callback": d.get("last_callback_at")} for c, n, d, _h, _m, _mo in rows]
    )


@router.get("/offline", summary="Devices a tool has shown as offline for more than a week (the clock starts when A.C.O.R.N first sees the device offline)")
async def offline_devices(
    user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, client_id: uuid.UUID | None = None, vendor: str = "unifi", days: int = 7
) -> dict[str, Any]:
    rows = await _rows(db, user.tenant_id, client_id, vendor)
    known = [{"client": c, "hostname": n, "model": mo, "offline_since": d.get("offline_since")} for c, n, d, _h, _m, mo in rows if rep.is_offline(d)]
    return {"vendor": vendor, "days": days, "offline_now": len(known), "devices": rep.offline_for_days(known, datetime.now(UTC), max(1, min(days, 365)))}


@router.get("/network-firmware", summary="Network devices (Auvik) running older firmware than another device of the same make and model")
async def network_firmware(
    user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, client_id: uuid.UUID | None = None
) -> dict[str, Any]:
    rows = await _rows(db, user.tenant_id, client_id, "auvik")
    return rep.firmware_behind(
        [{"client": c, "hostname": n, "manufacturer": maker, "model": model, "device_type": d.get("device_type"), "firmware": d.get("firmware_version")} for c, n, d, _h, maker, model in rows]
    )

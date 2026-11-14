"""Install the NinjaOne agent on a machine ScreenConnect already reaches, from the Devices page.

A.C.O.R.N holds no NinjaOne or ScreenConnect key. CORE tells A.C.O.R.N what can be chosen (the NinjaOne roles, organizations and locations; ``POST /core-feed/{token}/ninja-deploy-options``), the page
asks for one choice, and the request is only QUEUED for CORE (a ``vendor_actions`` row, vendor ``core``, action ``ninja_deploy``). CORE makes the installer link, sends the install command through
ScreenConnect, waits for the machine to show up in NinjaOne and sets the role that was picked (NinjaOne's installer link has no role of its own: it is always "Auto").

Installing software on a machine as SYSTEM: asking needs ``connectors:write``, a machine NinjaOne already has is refused, one request waits per machine, and every request is audited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import _as, _client_of
from app.api.v1.endpoints.devices_console import CONSOLE_VENDOR, ConsoleLine, _line, _session_of
from app.models.client_alias import ClientAlias
from app.models.device import Device, DeviceSource
from app.models.tenant import Tenant
from app.models.vendor_action import VendorAction
from app.services.audit import emit_audit
from app.services.vendor_actions import PENDING_TTL

router = APIRouter(prefix="/devices", tags=["devices"])

DEPLOY_ACTION = "ninja_deploy"
# NinjaOne's own node classes, by the kind of package: a Windows installer is for Windows machines, a Mac package for Macs.
CLASSES = {"msi": {"WINDOWS_WORKSTATION", "WINDOWS_SERVER"}, "pkg": {"MAC", "MAC_SERVER"}}
PACKAGES = {"msi": "Windows installer (MSI)", "pkg": "Mac package (PKG)"}


class RoleOut(BaseModel):
    id: int
    name: str
    node_class: str


class LocationOut(BaseModel):
    id: int
    name: str


class OrgOut(BaseModel):
    id: int
    name: str
    locations: list[LocationOut]


class DeployOptions(BaseModel):
    device_id: uuid.UUID
    device: str
    # Why nothing can be deployed from here, in plain words; None when something can.
    blocked: str | None = None
    # "msi" or "pkg": the package that suits the machine's operating system, as far as A.C.O.R.N can tell.
    suggested_package: Literal["msi", "pkg"]
    roles: list[RoleOut]
    organizations: list[OrgOut]
    # The NinjaOne organization the machine's client is mapped to, when it is.
    suggested_org_id: int | None = None


class DeployIn(BaseModel):
    package: Literal["msi", "pkg"]
    org_id: int = Field(ge=1, le=2_000_000_000)
    location_id: int = Field(ge=1, le=2_000_000_000)
    role_id: int = Field(ge=1, le=2_000_000_000)


def _stored(settings: Any) -> dict[str, Any]:
    found = settings.get("ninja_deploy") if isinstance(settings, dict) else None
    return found if isinstance(found, dict) else {}


def _package_for(device: Device) -> Literal["msi", "pkg"]:
    os_text = f"{device.os or ''} {device.os_version or ''}".lower()
    return "pkg" if any(w in os_text for w in ("mac", "darwin", "os x")) else "msi"


async def _mapped_org(db: Any, owner: uuid.UUID, tid: uuid.UUID) -> int | None:
    found = (
        (
            await db.execute(
                select(ClientAlias.vendor_client_id).where(
                    ClientAlias.tenant_id == owner,
                    ClientAlias.vendor == "ninjaone",
                    ClientAlias.child_tenant_id == tid,
                    ClientAlias.ignored.is_(False),
                )
            )
        )
        .scalars()
        .first()
    )
    return int(found) if found and str(found).isdigit() else None


@router.get(
    "/{device_id}/ninja-deploy", response_model=DeployOptions, summary="What can be chosen to install the NinjaOne agent on this machine"
)
async def deploy_options(
    device_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))], db: DBSession
) -> DeployOptions:
    owner = current_user.tenant_id
    tid = await _client_of(db, owner, device_id)
    stored = _stored((await db.execute(select(Tenant.settings).where(Tenant.id == owner))).scalar_one_or_none())
    async with _as(db, owner, tid):
        device = (await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tid))).scalar_one()
        session = await _session_of(db, tid, device_id)
        in_ninja = (
            await db.execute(
                select(DeviceSource.id).where(
                    DeviceSource.tenant_id == tid, DeviceSource.device_id == device_id, DeviceSource.vendor == "ninjaone"
                )
            )
        ).first()
    mapped = await _mapped_org(db, owner, tid)
    roles = [RoleOut(**r) for r in stored.get("roles", []) if isinstance(r, dict)]
    orgs = [
        OrgOut(id=o["id"], name=o["name"], locations=[LocationOut(**x) for x in o.get("locations", [])])
        for o in stored.get("organizations", [])
        if isinstance(o, dict)
    ]
    blocked = None
    if session is None:
        blocked = "ScreenConnect has no record of this machine, so there is no way to run the installer on it."
    elif in_ninja is not None:
        blocked = "NinjaOne already has this machine."
    elif not roles or not orgs:
        blocked = "CORE has not shared the NinjaOne organizations and roles yet. It does that on its own within a few minutes of NinjaOne being connected."
    return DeployOptions(
        device_id=device_id,
        device=device.hostname or "",
        blocked=blocked,
        suggested_package=_package_for(device),
        roles=roles,
        organizations=sorted(orgs, key=lambda o: o.name.lower()),
        suggested_org_id=mapped if any(o.id == mapped for o in orgs) else None,
    )


@router.post(
    "/{device_id}/ninja-deploy",
    response_model=ConsoleLine,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Install the NinjaOne agent on this machine through ScreenConnect",
)
async def deploy(
    device_id: uuid.UUID,
    body: DeployIn,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))],
    db: DBSession,
) -> ConsoleLine:
    owner = current_user.tenant_id
    tid = await _client_of(db, owner, device_id)
    stored = _stored((await db.execute(select(Tenant.settings).where(Tenant.id == owner))).scalar_one_or_none())
    role = next((r for r in stored.get("roles", []) if isinstance(r, dict) and r.get("id") == body.role_id), None)
    org = next((o for o in stored.get("organizations", []) if isinstance(o, dict) and o.get("id") == body.org_id), None)
    location = next((x for x in (org or {}).get("locations", []) if x.get("id") == body.location_id), None)
    if role is None or org is None or location is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That organization, location or role is not one NinjaOne offers."
        )
    if role.get("node_class") not in CLASSES[body.package]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"The role {role.get('name')} does not fit a {PACKAGES[body.package]}."
        )
    async with _as(db, owner, tid):
        device = (await db.execute(select(Device).where(Device.id == device_id, Device.tenant_id == tid))).scalar_one()
        session = await _session_of(db, tid, device_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="ScreenConnect has no record of this machine.")
        if (
            await db.execute(
                select(DeviceSource.id).where(
                    DeviceSource.tenant_id == tid, DeviceSource.device_id == device_id, DeviceSource.vendor == "ninjaone"
                )
            )
        ).first() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="NinjaOne already has this machine.")
        now = datetime.now(UTC)
        waiting = (
            await db.execute(
                select(VendorAction.id).where(
                    VendorAction.tenant_id == tid,
                    VendorAction.vendor == CONSOLE_VENDOR,
                    VendorAction.action.in_((DEPLOY_ACTION, "sc_command")),
                    VendorAction.status.in_(("pending", "claimed")),
                    VendorAction.created_at > now - PENDING_TTL,
                    VendorAction.incident_uid.like(f"sc:{device_id}:%"),
                )
            )
        ).first()
        if waiting is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Something for this machine is still waiting for an answer.")
        label = f"Install the NinjaOne agent ({PACKAGES[body.package]}) for {org['name']} / {location['name']}, role {role['name']}"
        row = VendorAction(
            id=uuid.uuid4(),
            tenant_id=tid,
            alert_id=None,
            incident_uid=f"sc:{device_id}:deploy{uuid.uuid4().hex[:8]}",
            vendor=CONSOLE_VENDOR,
            action=DEPLOY_ACTION,
            params={
                "session_id": session,
                "device": (device.hostname or "")[:255],
                "package": body.package,
                "org_id": body.org_id,
                "org_name": org["name"],
                "location_id": body.location_id,
                "role_id": body.role_id,
                "role_name": role["name"],
                "command": label[:900],
            },
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
            action="devices:ninja_deploy",
            resource="device",
            resource_id=str(device_id),
            changes={
                "device": device.hostname,
                "package": body.package,
                "organization": org["name"],
                "location": location["name"],
                "role": role["name"],
            },
            request=request,
        )
        await db.commit()
        return _line(row)

"""One client's environment on a page: the devices every tool reports, what sort each is, which tools cover it, and (from Auvik) what each network device is plugged into.

Built only from what is already stored: the merged device list (see ``devices.py``) and the ``connected_to`` list CORE sends with each Auvik device (see ``hud/src/aisoc-auvik.ts``).
A client with no Auvik has the devices and the coverage but no cabling, and the page says so.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import DeviceOut, _load_cached, _master_of, _scope, is_missing_from, long_offline
from app.models.tenant import Tenant

router = APIRouter(prefix="/client-environment", tags=["devices"])

# The tools whose absence from a computer is a gap (the same list the Devices page can filter by).
COVERAGE_TOOLS = ("ninjaone", "addigy", "huntress", "threatmate", "screenconnect", "fieldeffect", "dnsfilter", "autoelevate")
MAX_DEVICES = 1000
MAX_LINKS = 24


class EnvLink(BaseModel):
    name: str
    port: str | None = None
    remote_port: str | None = None
    speed: str | None = None


class EnvDevice(BaseModel):
    id: uuid.UUID
    hostname: str
    kind: str
    role: str | None = None  # what Auvik calls it: firewall, switch, accesspoint, server...
    online: bool | None = None
    tools: list[str] = Field(default_factory=list)
    links: list[EnvLink] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)  # tools a computer should have and does not


class EnvironmentOut(BaseModel):
    client_id: uuid.UUID
    client_name: str | None = None
    counts: dict[str, int]
    tools: dict[str, int]  # tool -> devices it reports
    gaps: dict[str, int]  # tool -> computers missing from it
    has_auvik: bool
    has_links: bool
    truncated: bool = False
    devices: list[EnvDevice]


def _links_of(d: DeviceOut) -> list[EnvLink]:
    out: list[EnvLink] = []
    for s in d.sources:
        if s.vendor != "auvik":
            continue
        raw = (s.details or {}).get("connected_to")
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"]:
                out.append(
                    EnvLink(
                        name=item["name"],
                        port=item.get("port") if isinstance(item.get("port"), str) else None,
                        remote_port=item.get("remote_port") if isinstance(item.get("remote_port"), str) else None,
                        speed=item.get("speed") if isinstance(item.get("speed"), str) else None,
                    )
                )
    return out[:MAX_LINKS]


def _role_of(d: DeviceOut) -> str | None:
    for s in d.sources:
        if s.vendor == "auvik":
            t = (s.details or {}).get("device_type")
            if isinstance(t, str) and t.strip():
                return t.strip().lower()
    return None


def build_environment(client_id: uuid.UUID, client_name: str | None, devices: list[DeviceOut]) -> EnvironmentOut:
    """The environment of one client from its (already loaded, not hidden) devices. Network devices come first, then computers, so a cap drops the least informative rows."""
    counted = [d for d in devices if d.hidden_since is None]
    counts = {"computer": 0, "network": 0, "camera": 0, "other": 0}
    tools: dict[str, int] = {}
    gaps = {t: 0 for t in COVERAGE_TOOLS}
    rows: list[EnvDevice] = []
    for d in counted:
        counts[d.kind] = counts.get(d.kind, 0) + 1
        for v in {s.vendor for s in d.sources}:
            tools[v] = tools.get(v, 0) + 1
        missing = [t for t in COVERAGE_TOOLS if d.kind == "computer" and not long_offline(d) and is_missing_from(d, t)]
        for t in missing:
            gaps[t] += 1
        rows.append(
            EnvDevice(
                id=d.id,
                hostname=d.hostname,
                kind=d.kind,
                role=_role_of(d),
                online=d.online,
                tools=sorted({s.vendor for s in d.sources}),
                links=_links_of(d),
                missing=missing,
            )
        )
    order = {"network": 0, "computer": 1, "camera": 2, "other": 3}
    rows.sort(key=lambda r: (order.get(r.kind, 4), r.hostname.lower()))
    return EnvironmentOut(
        client_id=client_id,
        client_name=client_name,
        counts=counts,
        tools=dict(sorted(tools.items())),
        gaps={t: n for t, n in gaps.items() if n},
        has_auvik="auvik" in tools,
        has_links=any(r.links for r in rows),
        truncated=len(rows) > MAX_DEVICES,
        devices=rows[:MAX_DEVICES],
    )


@router.get("/{client_id}", response_model=EnvironmentOut, summary="One client's devices, tool coverage and (from Auvik) network cabling")
async def client_environment(
    client_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession
) -> EnvironmentOut:
    owner = current_user.tenant_id
    scope, clients = await _scope(db, owner, client_id)  # 404 for a client that is not this company's
    master = _master_of(await db.get(Tenant, owner))
    loaded = await _load_cached(db, owner, scope, clients, master)
    return build_environment(client_id, clients.get(client_id), loaded)

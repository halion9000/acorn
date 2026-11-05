"""Remote management and remote access tools on client devices: what is installed where, what the owner decided about each (allowed, blocked, unreviewed), and an alert for any blocked one.

Everything is read from what CORE reports (the installed software of each device, matched against a catalog of known tools on CORE's side, so only the tools found are sent). See
``app/services/remote_tools.py`` for the catalog and the rules.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.inbox_core_feed import _verify_core_feed_token
from app.db.rls_scope import acting_as_tenant, cross_tenant_reads
from app.db.rls_sessions import adopt_tenant
from app.models.client_alias import ClientAlias
from app.models.remote_tool import ALL_CLIENTS, CustomRemoteTool, DeviceRemoteTool, RemoteToolRule, RemoteToolScan
from app.models.tenant import Tenant
from app.services import remote_tools as rt
from app.services.audit import emit_audit
from app.services.identity_detections import alert_values, save_findings  # noqa: F401  (save_findings: see _raise_alerts)

logger = logging.getLogger("aisoc.remote_tools")

router = APIRouter(prefix="/remote-tools", tags=["remote-tools"])
ingest_router = APIRouter(prefix="/inbox", tags=["inbox-core-feed"])

_VENDOR = r"^[a-z0-9][a-z0-9_-]{0,39}$"
_TOOL_KEY = r"^[a-z0-9_]{1,60}$"


# ---- reading --------------------------------------------------------------------------------------------------------------------------------------------------


async def _clients(db: Any, owner: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == owner))).all()
    return {r.id: r.name for r in rows}


async def _load_custom(db: Any, owner: uuid.UUID) -> list[CustomRemoteTool]:
    """The owner's own tools, made known to this request (see ``remote_tools.set_custom``). Every handler that names or lists tools calls this first."""
    rows = list((await db.execute(select(CustomRemoteTool).where(CustomRemoteTool.tenant_id == owner))).scalars().all())
    rt.set_custom([rt.build_custom(r.tool_key, r.name, r.category, r.match_text, r.publisher_text) for r in rows])
    return rows


async def _rules(db: Any, owner: uuid.UUID) -> dict[tuple[str, uuid.UUID | None], str]:
    rows = (await db.execute(select(RemoteToolRule).where(RemoteToolRule.tenant_id == owner))).scalars().all()
    return {(r.tool_key, None if r.client_id == ALL_CLIENTS else r.client_id): r.verdict for r in rows}


async def _sightings(db: Any, scope: list[uuid.UUID]) -> list[DeviceRemoteTool]:
    async with cross_tenant_reads(db):
        return list((await db.execute(select(DeviceRemoteTool).where(DeviceRemoteTool.tenant_id.in_(scope)))).scalars().all())


class ToolRow(BaseModel):
    key: str
    name: str
    category: str
    clients: int
    devices: int
    last_seen: datetime | None
    verdict: str  # what it is for every client without a rule of its own
    client_rules: int  # clients with a rule of their own
    blocked_devices: int
    allowed_devices: int
    unreviewed_devices: int
    # For a tool that is installed once per server (ScreenConnect): whether it has one, your own identifiers, and how many installs belong to another server.
    has_instances: bool = False
    trusted_instances: list[str] = []
    foreign_installs: int = 0


class Inventory(BaseModel):
    tools_found: int
    devices_with_tools: int
    devices_scanned: int
    blocked_devices: int
    last_scanned: datetime | None
    tools: list[ToolRow]


def build_inventory(
    sightings: list[Any], rules: dict[tuple[str, uuid.UUID | None], str], scans: list[Any], trusted: dict[str, list[str]] | None = None
) -> Inventory:
    """The numbers behind the page, from stored sightings (pure: tested without a database)."""
    trusted = trusted or {}
    by_tool: dict[str, list[Any]] = {}
    for s in sightings:
        if rt.tool_by_key(s.tool_key) is not None:
            by_tool.setdefault(s.tool_key, []).append(s)
    tools: list[ToolRow] = []
    blocked_devices: set[tuple[uuid.UUID, str]] = set()
    for key, rows in by_tool.items():
        tool = rt.tool_by_key(key)
        counts = {"allowed": 0, "blocked": 0, "unreviewed": 0}
        seen_device: set[tuple[uuid.UUID, str]] = set()
        for s in rows:
            v = rt.effective_verdict(key, s.tenant_id, rules)
            device = (s.tenant_id, rt.host_key(s.hostname))
            if device not in seen_device:  # a second install of the tool on the same device is still one device
                seen_device.add(device)
                counts[v] += 1
            if v == "blocked":
                blocked_devices.add(device)
        mine = trusted.get(key, [])
        foreign = sum(1 for s in rows if mine and getattr(s, "instance_id", "") and s.instance_id not in mine)
        tools.append(
            ToolRow(
                key=key,
                name=tool.name,  # type: ignore[union-attr]
                category=tool.category,  # type: ignore[union-attr]
                clients=len({s.tenant_id for s in rows}),
                devices=len(seen_device),
                last_seen=max((s.last_seen for s in rows), default=None),
                verdict=rules.get((key, None), "unreviewed"),
                client_rules=sum(1 for (k, c) in rules if k == key and c is not None),
                blocked_devices=counts["blocked"],
                allowed_devices=counts["allowed"],
                unreviewed_devices=counts["unreviewed"],
                has_instances=tool.instance_pattern is not None,  # type: ignore[union-attr]
                trusted_instances=mine,
                foreign_installs=foreign,
            )
        )
    tools.sort(key=lambda t: (-t.blocked_devices, -t.devices, t.name.lower()))
    return Inventory(
        tools_found=len(tools),
        devices_with_tools=len({(s.tenant_id, rt.host_key(s.hostname)) for s in sightings if rt.tool_by_key(s.tool_key) is not None}),
        devices_scanned=sum(int(x.devices_scanned) for x in scans),
        blocked_devices=len(blocked_devices),
        last_scanned=max((x.scanned_at for x in scans), default=None),
        tools=tools,
    )


@router.get("/inventory", response_model=Inventory, summary="Every remote management and remote access tool found on client devices, with what has been decided about each")
async def inventory(current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> Inventory:
    owner = current_user.tenant_id
    await _load_custom(db, owner)
    clients = await _clients(db, owner)
    scope = [owner, *clients]
    rules = await _rules(db, owner)
    sightings = await _sightings(db, scope)
    async with cross_tenant_reads(db):
        scans = list((await db.execute(select(RemoteToolScan).where(RemoteToolScan.tenant_id.in_(scope)))).scalars().all())
    owner_tenant = await db.get(Tenant, owner)
    return build_inventory(sightings, rules, scans, rt.trusted_instances(getattr(owner_tenant, "settings", None)))


def unreviewed_tools_by_client(sightings: list[Any], rules: dict[tuple[str, uuid.UUID | None], str]) -> dict[uuid.UUID, int]:
    """For each client: how many different tools found on its devices nobody has allowed or blocked yet (pure). Clients with none are absent."""
    seen: dict[uuid.UUID, set[str]] = {}
    for s in sightings:
        if rt.tool_by_key(s.tool_key) is not None and rt.effective_verdict(s.tool_key, s.tenant_id, rules) == "unreviewed":
            seen.setdefault(s.tenant_id, set()).add(s.tool_key)
    return {client: len(keys) for client, keys in seen.items()}


class CatalogEntry(BaseModel):
    key: str
    name: str
    category: str
    custom: bool = False


@router.get("/catalog", response_model=list[CatalogEntry], summary="The tools that are looked for, the built-in list and the ones added by hand")
async def catalog(current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> list[CatalogEntry]:
    await _load_custom(db, current_user.tenant_id)
    return [CatalogEntry(key=t.key, name=t.name, category=t.category) for t in rt.CATALOG] + [CatalogEntry(key=t.key, name=t.name, category=t.category, custom=True) for t in rt.custom_tools()]


class DeviceRow(BaseModel):
    client_id: uuid.UUID
    client_name: str | None
    hostname: str
    version: str | None
    first_seen: datetime
    last_seen: datetime
    verdict: str
    install_path: str | None = None
    program: str | None = None
    instance_id: str = ""
    # For an install that belongs to another server than yours (see the tool's own identifiers): True.
    foreign: bool = False




@router.get("/tools/{tool_key}/devices", response_model=list[DeviceRow], summary="The devices one tool was found on")
async def tool_devices(
    tool_key: str,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    client_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 2000,
) -> list[DeviceRow]:
    owner = current_user.tenant_id
    await _load_custom(db, owner)
    if rt.tool_by_key(tool_key) is None:
        raise HTTPException(status_code=404, detail="That is not a tool this page knows")
    clients = await _clients(db, owner)
    scope = [owner, *clients]
    if client_id is not None:
        if client_id not in scope:
            raise HTTPException(status_code=404, detail="Client not found")
        scope = [client_id]
    rules = await _rules(db, owner)
    mine = rt.trusted_instances(getattr(await db.get(Tenant, owner), "settings", None)).get(tool_key, [])
    rows = [s for s in await _sightings(db, scope) if s.tool_key == tool_key]
    rows.sort(key=lambda s: ((clients.get(s.tenant_id) or "").lower(), s.hostname.lower(), getattr(s, "instance_id", "") or ""))
    return [
        DeviceRow(
            client_id=s.tenant_id,
            client_name=clients.get(s.tenant_id),
            hostname=s.hostname,
            version=s.version,
            first_seen=s.first_seen,
            last_seen=s.last_seen,
            verdict=rt.effective_verdict(tool_key, s.tenant_id, rules),
            install_path=getattr(s, "install_path", None),
            program=getattr(s, "program", None),
            instance_id=getattr(s, "instance_id", "") or "",
            foreign=bool(mine and getattr(s, "instance_id", "") and s.instance_id not in mine),
        )
        for s in rows[:limit]
    ]


# ---- deciding -------------------------------------------------------------------------------------------------------------------------------------------------


class VerdictIn(BaseModel):
    verdict: str = Field(pattern="^(allowed|blocked|unreviewed)$")
    client_id: uuid.UUID | None = Field(default=None, description="Only this client; leave out for every client.")
    note: str | None = Field(default=None, max_length=400)


class VerdictOut(BaseModel):
    tool_key: str
    verdict: str
    client_id: uuid.UUID | None
    alerts_raised: int


class _Nothing:
    """A context manager that does nothing, for the managing company's own devices (no other tenant to act as)."""

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *a: object) -> bool:
        return False


def _in_tenant(db: Any, owner: uuid.UUID, tenant_id: uuid.UUID) -> Any:
    return acting_as_tenant(db, tenant_id) if tenant_id != owner else _Nothing()


def _alert_model() -> Any:
    from app.models.alert import Alert  # noqa: PLC0415

    return Alert


async def _save(db: Any, tenant_id: uuid.UUID, findings: list[Any], now: datetime) -> int:
    made = 0
    async with db.begin_nested():
        for f in findings:
            values = alert_values(tenant_id, f, now)
            values.update(
                category="remote_access",
                connector_type="remote-tools",
                tags=["remote-tool", "foreign-server" if f.rule_id == rt.FOREIGN_RULE_ID else "blocked", f.rule_id],
                raw_event={"source": "aisoc-remote-tools", "finding": {"uid": f"{f.rule_id}:{f.key}", "title": f.title}},
            )
            res = await db.execute(pg_insert(_alert_model()).values(**values).on_conflict_do_nothing(index_elements=["id"]))
            made += res.rowcount or 0
    return made


async def _raise_alerts(
    db: Any, owner: uuid.UUID, rows: list[Any], rules: dict[tuple[str, uuid.UUID | None], str], now: datetime, trusted: dict[str, list[str]] | None = None
) -> int:
    """Alerts for the blocked tools, and the installs that belong to another server than yours, among ``rows`` (stored sightings of any clients), each raised in its own client's tenant. One alert per device and
    tool (blocked) or per device, tool and server (another server's); a fixed id, so a repeat raises nothing."""
    made = 0
    if trusted is None:
        trusted = rt.trusted_instances(getattr(await db.get(Tenant, owner), "settings", None))
    by_tenant: dict[uuid.UUID, list[Any]] = {}
    for tenant_id, finding in [*rt.blocked_findings(rows, rules, now), *rt.foreign_findings(rows, trusted, now)]:
        by_tenant.setdefault(tenant_id, []).append(finding)
    for tenant_id, findings in by_tenant.items():
        try:
            async with _in_tenant(db, owner, tenant_id):
                made += await _save(db, tenant_id, findings, now)
        except Exception:  # noqa: BLE001 - one client's alerts failing must not lose the rest, or the report itself
            logger.warning("remote tool alerts failed for a client", exc_info=True)
    return made


@router.put("/tools/{tool_key}/verdict", response_model=VerdictOut, summary="Allow, block or leave unreviewed a tool, for every client or for one")
async def set_verdict(
    tool_key: str,
    body: VerdictIn,
    current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))],
    db: DBSession,
    request: Request = None,  # type: ignore[assignment]
) -> VerdictOut:
    owner = current_user.tenant_id
    await _load_custom(db, owner)
    tool = rt.tool_by_key(tool_key)
    if tool is None:
        raise HTTPException(status_code=404, detail="That is not a tool this page knows")
    clients = await _clients(db, owner)
    if body.client_id is not None and body.client_id not in clients and body.client_id != owner:
        raise HTTPException(status_code=404, detail="Client not found")
    scope_id = body.client_id or ALL_CLIENTS
    now = datetime.now(UTC)
    existing = (
        await db.execute(select(RemoteToolRule).where(RemoteToolRule.tenant_id == owner, RemoteToolRule.tool_key == tool_key, RemoteToolRule.client_id == scope_id))
    ).scalar_one_or_none()
    before = existing.verdict if existing is not None else "unreviewed"
    note = " ".join((body.note or "").split()) or None
    if body.verdict == "unreviewed" and body.client_id is not None:
        # "Unreviewed" for one client means "no rule of its own": it goes back to following the rule for every client.
        await db.execute(delete(RemoteToolRule).where(RemoteToolRule.tenant_id == owner, RemoteToolRule.tool_key == tool_key, RemoteToolRule.client_id == scope_id))
    else:
        stmt = pg_insert(RemoteToolRule).values(tenant_id=owner, tool_key=tool_key, client_id=scope_id, verdict=body.verdict, note=note, decided_by=current_user.user_id, decided_at=now)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["tenant_id", "tool_key", "client_id"], set_={"verdict": body.verdict, "note": note, "decided_by": current_user.user_id, "decided_at": now}
            )
        )
    await db.flush()
    raised = 0
    if body.verdict == "blocked":
        scope = [body.client_id] if body.client_id is not None else [owner, *clients]
        rows = [s for s in await _sightings(db, scope) if s.tool_key == tool_key]
        raised = await _raise_alerts(db, owner, rows, await _rules(db, owner), now)
    if before != body.verdict:
        await emit_audit(
            db=db,
            tenant_id=owner,
            actor_id=current_user.user_id,
            action="remote_tool:verdict_changed",
            resource="remote_tool",
            resource_id=tool_key,
            changes={"tool": tool.name, "client": str(body.client_id) if body.client_id else "all", "before": before, "after": body.verdict, "note": note},
            request=request,
        )
    await db.commit()
    return VerdictOut(tool_key=tool_key, verdict=body.verdict, client_id=body.client_id, alerts_raised=raised)


class InstancesIn(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=20, description="The server identifiers that are yours, as they appear in the install (ScreenConnect: the 16 characters in 'ScreenConnect Client (...)').")


class InstancesOut(BaseModel):
    tool_key: str
    ids: list[str]
    alerts_raised: int


@router.put(
    "/tools/{tool_key}/instances",
    response_model=InstancesOut,
    summary="Say which server identifiers of a tool are yours; an install that belongs to any other raises a critical alert",
)
async def set_instances(
    tool_key: str,
    body: InstancesIn,
    current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))],
    db: DBSession,
    request: Request = None,  # type: ignore[assignment]
) -> InstancesOut:
    await _load_custom(db, current_user.tenant_id)
    tool = rt.tool_by_key(tool_key)
    if tool is None:
        raise HTTPException(status_code=404, detail="That is not a tool this page knows")
    if tool.instance_pattern is None:
        raise HTTPException(status_code=422, detail=f"{tool.name} installs do not name a server, so there are no identifiers to set")
    try:
        chosen = rt.normalize_instance_ids(body.ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{exc} is not a server identifier (it is 8 to 40 letters a to f and digits)") from None
    owner = current_user.tenant_id
    tenant = await db.get(Tenant, owner)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    before = rt.trusted_instances(tenant.settings).get(tool_key, [])
    tenant.settings = rt.with_trusted_instances(tenant.settings, tool_key, chosen)
    await db.flush()
    raised = 0
    if chosen:
        clients = await _clients(db, owner)
        rows = [s for s in await _sightings(db, [owner, *clients]) if s.tool_key == tool_key]
        raised = await _raise_alerts(db, owner, rows, await _rules(db, owner), datetime.now(UTC), trusted={tool_key: chosen})
    if before != chosen:
        await emit_audit(
            db=db,
            tenant_id=owner,
            actor_id=current_user.user_id,
            action="remote_tool:instances_changed",
            resource="remote_tool",
            resource_id=tool_key,
            changes={"tool": tool.name, "before": before, "after": chosen},
            request=request,
        )
    await db.commit()
    return InstancesOut(tool_key=tool_key, ids=chosen, alerts_raised=raised)


# ---- tools the owner adds by hand -----------------------------------------------------------------------------------------------------------------------------


class CustomIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: str = Field(max_length=30)
    match: str = Field(max_length=80, description="A piece of the program's name as the device lists it.")
    publisher: str | None = Field(default=None, max_length=80)


class CustomOut(BaseModel):
    key: str
    name: str
    category: str
    match: str
    publisher: str | None
    created_at: datetime | None = None


def _custom_out(r: Any) -> CustomOut:
    return CustomOut(key=r.tool_key, name=r.name, category=r.category, match=r.match_text, publisher=r.publisher_text, created_at=getattr(r, "created_at", None))


@router.get("/custom", response_model=list[CustomOut], summary="The tools added by hand")
async def list_custom(current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> list[CustomOut]:
    rows = await _load_custom(db, current_user.tenant_id)
    return [_custom_out(r) for r in sorted(rows, key=lambda r: r.name.lower())]


@router.post("/custom", response_model=CustomOut, status_code=201, summary="Add a remote tool to the catalog by hand")
async def add_custom(
    body: CustomIn,
    current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))],
    db: DBSession,
    request: Request = None,  # type: ignore[assignment]
) -> CustomOut:
    owner = current_user.tenant_id
    existing = await _load_custom(db, owner)
    try:
        name, category, match, publisher = rt.validate_custom(body.name, body.category, body.match, body.publisher)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if len(existing) >= rt.MAX_CUSTOM:
        raise HTTPException(status_code=422, detail=f"At most {rt.MAX_CUSTOM} tools can be added by hand")
    builtin = rt.covered_by_builtin(match)
    if builtin is not None:
        raise HTTPException(status_code=409, detail=f"{builtin.name} is already in the list and a program called that is found already")
    key = rt.slug_key(name)
    if not key or any(r.tool_key == key for r in existing) or rt.tool_by_key(key) is not None:
        raise HTTPException(status_code=409, detail="A tool with that name is already in the list; give it a different name")
    row = CustomRemoteTool(tenant_id=owner, tool_key=key, name=name, category=category, match_text=match, publisher_text=publisher, created_by=current_user.user_id)
    db.add(row)
    await db.flush()
    await emit_audit(
        db=db,
        tenant_id=owner,
        actor_id=current_user.user_id,
        action="remote_tool:custom_added",
        resource="remote_tool",
        resource_id=key,
        changes={"name": name, "category": category, "match": match, "publisher": publisher},
        request=request,
    )
    await db.commit()
    return _custom_out(row)


@router.delete("/custom/{tool_key}", status_code=204, summary="Remove a tool that was added by hand, with what was found for it")
async def remove_custom(
    tool_key: str,
    current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))],
    db: DBSession,
    request: Request = None,  # type: ignore[assignment]
) -> None:
    owner = current_user.tenant_id
    existing = await _load_custom(db, owner)
    row = next((r for r in existing if r.tool_key == tool_key), None)
    if row is None:
        raise HTTPException(status_code=404, detail="That is not a tool you added")
    clients = await _clients(db, owner)
    async with cross_tenant_reads(db):
        await db.execute(delete(DeviceRemoteTool).where(DeviceRemoteTool.tenant_id.in_([owner, *clients]), DeviceRemoteTool.tool_key == tool_key))
    await db.execute(delete(RemoteToolRule).where(RemoteToolRule.tenant_id == owner, RemoteToolRule.tool_key == tool_key))
    await db.execute(delete(CustomRemoteTool).where(CustomRemoteTool.tenant_id == owner, CustomRemoteTool.tool_key == tool_key))
    await emit_audit(
        db=db,
        tenant_id=owner,
        actor_id=current_user.user_id,
        action="remote_tool:custom_removed",
        resource="remote_tool",
        resource_id=tool_key,
        changes={"name": row.name},
        request=request,
    )
    await db.commit()


# ---- CORE reports ---------------------------------------------------------------------------------------------------------------------------------------------


class FoundIn(BaseModel):
    hostname: str = Field(min_length=1, max_length=255)
    tool_key: str = Field(pattern=_TOOL_KEY)
    version: str | None = Field(default=None, max_length=60)
    program: str | None = Field(default=None, max_length=255, description="The program's name as the device lists it.")
    path: str | None = Field(default=None, max_length=500, description="Where it is installed, when the tool that lists the software says.")


class RemoteToolsReport(BaseModel):
    vendor: str = Field(pattern=_VENDOR, description="The tool the software list came from (ninjaone).")
    vendor_client_id: str | None = Field(default=None, max_length=200)
    devices_scanned: int = Field(ge=0, le=200000, description="How many of the client's devices were looked at in this scan, with or without a tool on them.")
    items: list[FoundIn] = Field(default_factory=list, max_length=5000)


class ReportOut(BaseModel):
    stored: int
    removed: int
    unknown_tools: int
    unmapped: bool
    alerts_raised: int


async def apply_report(db: Any, owner: uuid.UUID, report: RemoteToolsReport, now: datetime | None = None) -> ReportOut:
    """Replace what is stored for one client and source with what this scan found, then alert on blocked tools. A scan that looked at no devices never removes anything (nothing was checked)."""
    now = now or datetime.now(UTC)
    await _load_custom(db, owner)
    target = owner
    if report.vendor_client_id:
        alias = (
            await db.execute(select(ClientAlias).where(ClientAlias.tenant_id == owner, ClientAlias.vendor == report.vendor, ClientAlias.vendor_client_id == report.vendor_client_id))
        ).scalar_one_or_none()
        children = set((await db.execute(select(Tenant.id).where(Tenant.parent_tenant_id == owner))).scalars().all())
        if alias is None or alias.ignored or alias.child_tenant_id is None or alias.child_tenant_id not in children:
            return ReportOut(stored=0, removed=0, unknown_tools=0, unmapped=True, alerts_raised=0)  # not mapped to a client yet: it arrives again after the mapping
        target = alias.child_tenant_id
    unknown = sum(1 for i in report.items if rt.tool_by_key(i.tool_key) is None)
    wanted: dict[tuple[str, str, str], FoundIn] = {}
    for i in report.items:
        if rt.tool_by_key(i.tool_key) is not None:
            # Two installs of one tool on one device are two rows when they belong to different servers; the same install listed twice is one.
            wanted[(rt.host_key(i.hostname), i.tool_key, rt.instance_of(i.tool_key, i.program, i.path))] = i
    stored = removed = 0
    async with _in_tenant(db, owner, target):
        held = (await db.execute(select(DeviceRemoteTool).where(DeviceRemoteTool.tenant_id == target, DeviceRemoteTool.vendor == report.vendor))).scalars().all()
        for (hk, tk, inst), item in wanted.items():
            stmt = pg_insert(DeviceRemoteTool).values(
                tenant_id=target, hostname_key=hk, tool_key=tk, instance_id=inst, hostname=item.hostname, vendor=report.vendor, version=item.version, program=item.program, install_path=item.path, first_seen=now, last_seen=now
            )
            await db.execute(
                stmt.on_conflict_do_update(
                    index_elements=["tenant_id", "hostname_key", "tool_key", "instance_id"],
                    set_={"hostname": item.hostname, "vendor": report.vendor, "version": item.version, "program": item.program, "install_path": item.path, "last_seen": now},
                )
            )
            stored += 1
        if report.devices_scanned > 0:
            for row in held:
                if (row.hostname_key, row.tool_key, getattr(row, "instance_id", "") or "") not in wanted:
                    await db.execute(
                        delete(DeviceRemoteTool).where(
                            DeviceRemoteTool.tenant_id == target,
                            DeviceRemoteTool.hostname_key == row.hostname_key,
                            DeviceRemoteTool.tool_key == row.tool_key,
                            DeviceRemoteTool.instance_id == (getattr(row, "instance_id", "") or ""),
                        )
                    )
                    removed += 1
        scan = pg_insert(RemoteToolScan).values(tenant_id=target, vendor=report.vendor, scanned_at=now, devices_scanned=report.devices_scanned)
        await db.execute(scan.on_conflict_do_update(index_elements=["tenant_id", "vendor"], set_={"scanned_at": now, "devices_scanned": report.devices_scanned}))
    rules = await _rules(db, owner)
    sightings = await _sightings(db, [target])
    raised = await _raise_alerts(db, owner, sightings, rules, now)
    return ReportOut(stored=stored, removed=removed, unknown_tools=unknown, unmapped=False, alerts_raised=raised)


@ingest_router.post("/core-feed/{tenant_token}/remote-tools", response_model=ReportOut)
async def report_core_feed_remote_tools(tenant_token: str, body: RemoteToolsReport, db: DBSession) -> ReportOut:
    """Record the remote tools a scan of one client's devices found (CORE sends the matches only)."""
    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    out = await apply_report(db, owner, body)
    await db.commit()
    return out


class CatalogForCore(BaseModel):
    key: str
    name: str
    patterns: list[str]


@ingest_router.get("/core-feed/{tenant_token}/remote-tools/catalog", response_model=list[CatalogForCore])
async def core_feed_remote_tools_catalog(tenant_token: str, db: DBSession) -> list[CatalogForCore]:
    """The tools and the patterns that recognise them in a program name, so CORE matches on its side and sends only the matches (one list, kept here)."""
    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    await _load_custom(db, owner)
    return [CatalogForCore(key=t.key, name=t.name, patterns=list(t.patterns)) for t in [*rt.CATALOG, *rt.custom_tools()]]

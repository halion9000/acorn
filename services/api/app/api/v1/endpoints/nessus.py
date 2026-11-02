"""Uploaded Nessus scans per client: upload a .nessus export, see its findings, delete it.

The file is sent as the raw request body (no multipart): ``POST /nessus/scans?client_id=...&name=...`` with the file's bytes. It is parsed with a safe streaming parser (app/services/nessus_import.py),
which refuses anything that is not a plain Nessus export.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.db.rls_scope import cross_tenant_reads
from app.models.device import Device
from app.models.nessus import NessusFinding, NessusScan
from app.models.tenant import Tenant
from app.services.audit import emit_audit
from app.services.nessus_import import MAX_BYTES, NessusFileError, parse_nessus
from app.services.nessus_store import DeviceRef, store_scan

router = APIRouter(prefix="/nessus", tags=["nessus"])
SEVERITY = {1: "low", 2: "medium", 3: "high", 4: "critical"}


class ScanOut(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    client_name: str
    name: str
    description: str | None
    notes: str | None
    scan_type: str
    uploaded_by: str | None
    uploaded_at: datetime
    hosts: int
    matched_hosts: int
    critical: int
    high: int
    medium: int
    low: int


class FindingOut(BaseModel):
    host_name: str
    host_ip: str | None
    host_os: str | None
    device_id: uuid.UUID | None
    plugin_id: str
    name: str
    severity: str
    port: int
    protocol: str
    service: str
    cvss: float | None
    cves: list[str]
    exploit: bool
    synopsis: str
    solution: str


class ScanDetail(ScanOut):
    findings: list[FindingOut]
    total_findings: int
    page: int
    pages: int


async def load_devices(db: Any, tenant_id: uuid.UUID) -> list[DeviceRef]:
    """The client's devices, for matching scanned hosts to them."""
    rows = (await db.execute(select(Device.id, Device.hostname, Device.ip_addresses).where(Device.tenant_id == tenant_id))).all()
    return [DeviceRef(id=r.id, hostname=r.hostname or "", ips=tuple(r.ip_addresses or ())) for r in rows]


async def _clients(db: Any, owner: uuid.UUID) -> dict[uuid.UUID, str]:
    """The owner itself and its clients, by name."""
    async with cross_tenant_reads(db):
        rows = (await db.execute(select(Tenant.id, Tenant.name).where((Tenant.parent_tenant_id == owner) | (Tenant.id == owner)))).all()
    return {r.id: (f"{r.name} (own)" if r.id == owner else r.name) for r in rows}


def _out(scan: NessusScan, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": scan.id,
        "client_id": scan.tenant_id,
        "client_name": names.get(scan.tenant_id, ""),
        "name": scan.name,
        "description": scan.description,
        "notes": scan.notes,
        "scan_type": scan.scan_type,
        "uploaded_by": scan.uploaded_by,
        "uploaded_at": scan.uploaded_at,
        "hosts": scan.hosts,
        "matched_hosts": scan.matched_hosts,
        "critical": scan.critical,
        "high": scan.high,
        "medium": scan.medium,
        "low": scan.low,
    }


@router.post("/scans", response_model=ScanOut, status_code=status.HTTP_201_CREATED, summary="Upload a .nessus export for a client")
async def upload_scan(
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))],
    db: DBSession,
    client_id: uuid.UUID,
    name: str | None = Query(default=None, max_length=200),
    description: str | None = Query(default=None, max_length=300),
    notes: str | None = Query(default=None, max_length=4000),
    scan_type: str | None = Query(default=None, pattern="^(lan|wan|other)$"),
) -> ScanOut:
    owner = current_user.tenant_id
    names = await _clients(db, owner)
    if client_id not in names:
        raise HTTPException(status_code=404, detail="Client not found")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    data = await request.body()
    try:
        parsed = parse_nessus(data)
    except NessusFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    devices = await load_devices(db, client_id)
    scan = await store_scan(db, client_id, parsed, uploaded_by=current_user.email, devices=devices, name=name, description=description, notes=notes, scan_type=scan_type)
    await emit_audit(
        db=db,
        tenant_id=owner,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
        action="nessus:scan_uploaded",
        resource="nessus_scan",
        resource_id=str(scan.id),
        changes={"client_id": str(client_id), "name": scan.name, "hosts": scan.hosts, "critical": scan.critical, "high": scan.high},
    )
    await db.commit()
    return ScanOut(**_out(scan, names))


@router.get("/scans", response_model=list[ScanOut], summary="Uploaded scans, newest first")
async def list_scans(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, client_id: uuid.UUID | None = None
) -> list[ScanOut]:
    names = await _clients(db, current_user.tenant_id)
    if client_id is not None and client_id not in names:
        raise HTTPException(status_code=404, detail="Client not found")
    async with cross_tenant_reads(db):
        q = select(NessusScan).where(NessusScan.tenant_id.in_([client_id] if client_id else list(names))).order_by(NessusScan.uploaded_at.desc()).limit(200)
        rows = (await db.execute(q)).scalars().all()
    return [ScanOut(**_out(s, names)) for s in rows]


@router.get("/scans/{scan_id}", response_model=ScanDetail, summary="One scan with its findings, worst first")
async def scan_detail(
    scan_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    severity: str | None = Query(default=None, pattern="^(critical|high|medium|low)$"),
    host: str | None = Query(default=None, max_length=255),
    page: int = Query(1, ge=1, le=100_000),
    page_size: int = Query(50, ge=1, le=200),
) -> ScanDetail:
    names = await _clients(db, current_user.tenant_id)
    async with cross_tenant_reads(db):
        scan = (await db.execute(select(NessusScan).where(NessusScan.id == scan_id, NessusScan.tenant_id.in_(list(names))))).scalar_one_or_none()
        if scan is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        conds = [NessusFinding.scan_id == scan_id]
        if severity:
            conds.append(NessusFinding.severity == {v: k for k, v in SEVERITY.items()}[severity])
        if host:
            conds.append(NessusFinding.host_name.ilike(f"%{host.strip()}%"))
        total = (await db.execute(select(func.count()).select_from(NessusFinding).where(*conds))).scalar_one()
        rows = (
            await db.execute(
                select(NessusFinding)
                .where(*conds)
                .order_by(NessusFinding.severity.desc(), NessusFinding.exploit.desc(), NessusFinding.cvss.desc().nullslast(), NessusFinding.host_name)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
    findings = [
        FindingOut(
            host_name=f.host_name,
            host_ip=f.host_ip,
            host_os=f.host_os,
            device_id=f.device_id,
            plugin_id=f.plugin_id,
            name=f.name,
            severity=SEVERITY[f.severity],
            port=f.port,
            protocol=f.protocol,
            service=f.service,
            cvss=f.cvss,
            cves=list(f.cves or []),
            exploit=f.exploit,
            synopsis=f.synopsis,
            solution=f.solution,
        )
        for f in rows
    ]
    return ScanDetail(**_out(scan, names), findings=findings, total_findings=total, page=page, pages=max(1, -(-total // page_size)))


@router.delete("/scans/{scan_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None, summary="Delete an uploaded scan and its findings")
async def delete_scan(scan_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession) -> None:
    names = await _clients(db, current_user.tenant_id)
    async with cross_tenant_reads(db):
        scan = (await db.execute(select(NessusScan).where(NessusScan.id == scan_id, NessusScan.tenant_id.in_(list(names))))).scalar_one_or_none()
        if scan is None:
            raise HTTPException(status_code=404, detail="Scan not found")
        summary = {"client_id": str(scan.tenant_id), "name": scan.name, "hosts": scan.hosts, "critical": scan.critical, "high": scan.high}
        await db.delete(scan)  # its findings go with it (ON DELETE CASCADE)
        await emit_audit(
            db=db,
            tenant_id=current_user.tenant_id,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            action="nessus:scan_deleted",
            resource="nessus_scan",
            resource_id=str(scan_id),
            changes=summary,
        )
        await db.commit()

"""Keeping an uploaded Nessus scan: matching each scanned host to a machine in the client's device list, and storing the scan with its findings."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models.nessus import NessusFinding, NessusScan
from app.services.nessus_import import Host, ParsedScan

CHUNK = 1000


@dataclass(frozen=True)
class DeviceRef:
    id: uuid.UUID
    hostname: str
    ips: tuple[str, ...] = ()


def _names(host: Host) -> set[str]:
    """Every way the scanner may have written the machine's name: as given, its fqdn, and each one without its domain."""
    out: set[str] = set()
    for raw in (host.name, host.fqdn):
        name = (raw or "").strip().lower().rstrip(".")
        if name:
            out.add(name)
            out.add(name.split(".")[0])
    return out


def match_device(host: Host, devices: list[DeviceRef]) -> uuid.UUID | None:
    """The one device this host is, by name first and then by address. More than one candidate (two machines with the same short name, or two on one address) is not guessed: None."""
    names = _names(host)
    by_name = {d.id for d in devices if d.hostname.strip().lower().split(".")[0] in names or d.hostname.strip().lower() in names}
    if len(by_name) == 1:
        return next(iter(by_name))
    if len(by_name) > 1:
        return None
    ips = {i for i in (host.ip, host.name) if i}
    by_ip = {d.id for d in devices if ips & set(d.ips)}
    return next(iter(by_ip)) if len(by_ip) == 1 else None


async def store_scan(
    db,
    tenant_id: uuid.UUID,
    parsed: ParsedScan,
    *,
    uploaded_by: str | None,
    devices: list[DeviceRef],
    name: str | None = None,
    description: str | None = None,
    notes: str | None = None,
    scan_type: str | None = None,
) -> NessusScan:
    """Store the scan and every finding of every host. ``scan_type`` overrides the type worked out from the addresses (lan, wan or other)."""
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    matched = 0
    scan = NessusScan(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=(name or parsed.report_name or "Nessus scan")[:200],
        description=(description or "").strip()[:300] or None,
        notes=(notes or "").strip() or None,
        scan_type=scan_type if scan_type in ("lan", "wan", "other") else parsed.scan_type,
        uploaded_by=uploaded_by,
        hosts=len(parsed.hosts),
    )
    db.add(scan)
    await db.flush()
    batch: list[NessusFinding] = []
    for host in parsed.hosts:
        device_id = match_device(host, devices)
        matched += 1 if device_id else 0
        for f in host.findings:
            counts[f.severity] += 1
            batch.append(
                NessusFinding(
                    scan_id=scan.id,
                    tenant_id=tenant_id,
                    host_name=host.name,
                    host_ip=host.ip,
                    host_fqdn=host.fqdn,
                    host_os=host.os,
                    device_id=device_id,
                    plugin_id=f.plugin_id,
                    name=f.name,
                    severity=f.severity,
                    port=f.port,
                    protocol=f.protocol,
                    service=f.service,
                    cvss=f.cvss,
                    cves=f.cves,
                    exploit=f.exploit_available,
                    synopsis=f.synopsis,
                    solution=f.solution,
                )
            )
            if len(batch) >= CHUNK:
                db.add_all(batch)
                await db.flush()
                batch = []
    if batch:
        db.add_all(batch)
    scan.matched_hosts = matched
    scan.critical, scan.high, scan.medium, scan.low = counts[4], counts[3], counts[2], counts[1]
    await db.flush()
    return scan

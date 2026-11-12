"""The vulnerabilities a tool finds at each client, one line each.

- ``POST /api/v1/inbox/core-feed/{token}/vulnerabilities``: CORE sends one client's list (a snapshot, in chunks), authenticated by the secret in the path like the other CORE feeds. The final
  chunk removes what is no longer listed, so a vulnerability that was fixed leaves the page.
- ``GET /api/v1/client-vulnerabilities``: the lines for one client or for all the caller's clients together, worst first, with the counts that go above the table.

A line is one CVE in one version of one program at one client: how serious, whether an exploit is known, how many of the client's machines have it and which.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import UnmappedClient
from app.api.v1.endpoints.inbox_core_feed import _verify_core_feed_token
from app.api.v1.endpoints.signins import targets_by_tenant
from app.db.rls_scope import acting_as_tenant
from app.db.rls_sessions import adopt_tenant
from app.models.client_vulnerability import ClientVulnerability
from app.models.tenant import Tenant

ingest_router = APIRouter(prefix="/inbox", tags=["inbox-core-feed"])
router = APIRouter(prefix="/client-vulnerabilities", tags=["client-vulnerabilities"])

_VENDOR = r"^[a-z0-9][a-z0-9_-]{0,39}$"
SEVERITIES = ("critical", "high", "medium", "low")
MAX_ITEMS = 1000
DEVICE_NAMES_KEPT = 25
PAGE_MAX = 500
SUMMARY_MAX = 300


class VulnerabilityIn(BaseModel):
    cve: str = Field(min_length=1, max_length=60)
    software: str = Field(min_length=1, max_length=200)
    version: str = Field(default="", max_length=100)
    severity: str = Field(pattern="^(critical|high|medium|low)$")
    cvss: float | None = Field(default=None, ge=0, le=10)
    exploited: bool = False
    devices: int = Field(default=0, ge=0, le=1_000_000)
    device_names: list[Annotated[str, Field(max_length=120)]] = Field(default_factory=list, max_length=DEVICE_NAMES_KEPT)
    summary: str = Field(
        default="", max_length=SUMMARY_MAX, description="What the vulnerability is, in a sentence, when the tool gives one."
    )


class VulnerabilitiesReport(BaseModel):
    vendor: str = Field(pattern=_VENDOR)
    vendor_client_id: str = Field(min_length=1, max_length=200)
    snapshot_id: uuid.UUID = Field(description="One id for every chunk of one client's list.")
    last: bool = Field(default=True, description="True on the final chunk: vulnerabilities not in this list are then removed.")
    items: list[VulnerabilityIn] = Field(max_length=MAX_ITEMS)


class _OneClient:
    """Lets the shared client mapping place a report that belongs to one client, as a list of one item."""

    def __init__(self, report: VulnerabilitiesReport) -> None:
        self.vendor = report.vendor
        self.items = [report]


class VulnerabilitiesResponse(BaseModel):
    accepted: int
    unmapped: int = 0
    ignored: int = 0
    removed: int = 0
    unmapped_clients: list[UnmappedClient] = Field(default_factory=list)


def _row(tid: uuid.UUID, source: str, v: VulnerabilityIn, snapshot: uuid.UUID, now: datetime) -> dict[str, Any]:
    names = [n.strip() for n in v.device_names if n.strip()]
    return {
        "tenant_id": tid,
        "source": source,
        "cve_id": v.cve.strip().upper(),
        "software": v.software.strip(),
        "version": v.version.strip(),
        "severity": v.severity,
        "cvss": v.cvss,
        "exploited": v.exploited,
        "devices": max(v.devices, len(names)),
        "device_names": "\n".join(names),
        "summary": " ".join(v.summary.split()),
        "last_seen": now,
        "snapshot_id": snapshot,
    }


async def apply_vulnerabilities(
    db: Any, owner: uuid.UUID, report: VulnerabilitiesReport, now: datetime | None = None
) -> VulnerabilitiesResponse:
    """Store one client's list (or a chunk of it); on the last chunk, what is no longer listed is removed. An entry seen before keeps its first-seen time. The caller owns the transaction."""
    now = now or datetime.now(UTC)
    by_tenant, unmapped, ignored, waiting = await targets_by_tenant(db, owner, _OneClient(report))
    accepted = removed = 0
    for tid in by_tenant:
        async with acting_as_tenant(db, tid):
            # The same entry twice in one chunk would make the insert fail: the last one wins.
            rows = {
                (r["cve_id"], r["software"], r["version"]): r
                for r in (_row(tid, report.vendor, v, report.snapshot_id, now) for v in report.items)
            }
            if rows:
                values = [{**r, "first_seen": now} for r in rows.values()]
                stmt = pg_insert(ClientVulnerability).values(values)
                keys = ("tenant_id", "source", "cve_id", "software", "version", "first_seen")
                await db.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["tenant_id", "source", "cve_id", "software", "version"],
                        set_={c: stmt.excluded[c] for c in values[0] if c not in keys},
                    )
                )
                accepted += len(values)
            if report.last:
                res = await db.execute(
                    delete(ClientVulnerability).where(
                        ClientVulnerability.tenant_id == tid,
                        ClientVulnerability.source == report.vendor,
                        ClientVulnerability.snapshot_id != report.snapshot_id,
                    )
                )
                removed += res.rowcount or 0
    return VulnerabilitiesResponse(accepted=accepted, unmapped=unmapped, ignored=ignored, removed=removed, unmapped_clients=waiting)


@ingest_router.post("/core-feed/{tenant_token}/vulnerabilities", response_model=VulnerabilitiesResponse)
async def report_core_feed_vulnerabilities(tenant_token: str, body: VulnerabilitiesReport, db: DBSession) -> VulnerabilitiesResponse:
    """Record one client's vulnerabilities (a list, in chunks): what is missing from the final chunk is removed."""
    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    result = await apply_vulnerabilities(db, owner, body)
    await db.commit()
    return result


# ---- reading -------------------------------------------------------------------------------------------------------------------------------------------


class VulnerabilityOut(BaseModel):
    client_id: uuid.UUID
    client_name: str | None
    source: str
    cve: str
    software: str
    version: str
    severity: str
    cvss: float | None
    exploited: bool
    devices: int
    device_names: list[str]
    summary: str = ""
    first_seen: datetime
    last_seen: datetime


class VulnerabilityList(BaseModel):
    total: int
    exploited: int
    by_severity: dict[str, int]
    # How many clients have at least one line (after the filters).
    clients: int
    rows: list[VulnerabilityOut]


_RANK = case({s: i for i, s in enumerate(SEVERITIES)}, value=ClientVulnerability.severity, else_=len(SEVERITIES))


def rank_key(v: VulnerabilityOut) -> tuple[Any, ...]:
    """Worst first: the more serious, then one with a known exploit, then the one on more machines; the same order the database uses for each client."""
    return (
        SEVERITIES.index(v.severity) if v.severity in SEVERITIES else len(SEVERITIES),
        not v.exploited,
        -v.devices,
        v.cve,
        v.software,
        v.version,
        str(v.client_id),
    )


@router.get(
    "",
    response_model=VulnerabilityList,
    summary="The vulnerabilities found at one client, or at all the caller's clients, one line each, worst first",
)
async def list_client_vulnerabilities(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    client_id: uuid.UUID | None = Query(
        default=None, description="One client (or the caller's own organisation); left out, every client together."
    ),
    severity: str | None = Query(default=None, pattern="^(critical|high|medium|low)$"),
    exploited: bool | None = Query(default=None, description="True: only those with a known exploit."),
    q: str | None = Query(default=None, max_length=100, description="Part of a CVE id, a program name or a machine name."),
    limit: int = Query(default=200, ge=1, le=PAGE_MAX),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> VulnerabilityList:
    owner = current_user.tenant_id
    names = {r.id: r.name for r in (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == owner))).all()}
    if client_id is not None and client_id != owner and client_id not in names:
        return VulnerabilityList(total=0, exploited=0, by_severity={}, clients=0, rows=[])
    tenants = [client_id] if client_id is not None else [owner, *names]
    filters = []
    if severity:
        filters.append(ClientVulnerability.severity == severity)
    if exploited:
        filters.append(ClientVulnerability.exploited.is_(True))
    if q and q.strip():
        like = f"%{q.strip().replace('%', '').replace('_', '')}%"
        filters.append(
            or_(
                ClientVulnerability.cve_id.ilike(like),
                ClientVulnerability.software.ilike(like),
                ClientVulnerability.device_names.ilike(like),
                ClientVulnerability.summary.ilike(like),
            )
        )

    total = with_exploit = clients = 0
    by_severity: dict[str, int] = {}
    rows: list[VulnerabilityOut] = []
    for tid in tenants:
        async with contextlib.nullcontext() if tid == owner else acting_as_tenant(db, tid):
            where = (ClientVulnerability.tenant_id == tid, *filters)
            counted = (
                await db.execute(
                    select(ClientVulnerability.severity, func.count(), func.count().filter(ClientVulnerability.exploited.is_(True)))
                    .where(*where)
                    .group_by(ClientVulnerability.severity)
                )
            ).all()
            if not counted:
                continue
            clients += 1
            for sev, n, hit in counted:
                total += n
                with_exploit += hit
                by_severity[sev] = by_severity.get(sev, 0) + n
            # Only the lines that could be on the page asked for: the first (offset + limit) of each client, in the page's own order.
            found = (
                (
                    await db.execute(
                        select(ClientVulnerability)
                        .where(*where)
                        .order_by(
                            _RANK,
                            ClientVulnerability.exploited.desc(),
                            ClientVulnerability.devices.desc(),
                            ClientVulnerability.cve_id,
                            ClientVulnerability.software,
                            ClientVulnerability.version,
                        )
                        .limit(offset + limit)
                    )
                )
                .scalars()
                .all()
            )
        for v in found:
            rows.append(
                VulnerabilityOut(
                    client_id=tid,
                    client_name=names.get(tid),
                    source=v.source,
                    cve=v.cve_id,
                    software=v.software,
                    version=v.version,
                    severity=v.severity,
                    cvss=v.cvss,
                    exploited=v.exploited,
                    devices=v.devices,
                    device_names=[n for n in v.device_names.split("\n") if n],
                    summary=v.summary or "",
                    first_seen=v.first_seen,
                    last_seen=v.last_seen,
                )
            )
    rows.sort(key=rank_key)
    return VulnerabilityList(
        total=total, exploited=with_exploit, by_severity=by_severity, clients=clients, rows=rows[offset : offset + limit]
    )

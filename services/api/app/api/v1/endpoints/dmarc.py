"""DMARC reports per client: what receivers saw being sent as each client's domains, and the setup lines for pointing a client's reports at the shared mailbox.

Reads only. The reports arrive through the shared mailbox (app/workers/dmarc_ingest_worker.py); nothing here sends mail or changes DNS.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.core.config import settings
from app.db.rls_scope import cross_tenant_reads
from app.models.dmarc import DmarcIngestState, DmarcReport
from app.models.identity_source import IdentitySource
from app.models.signin import IdentityMfaUser
from app.models.tenant import Tenant
from app.services.domain_posture import candidate_domains

router = APIRouter(prefix="/dmarc", tags=["dmarc"])

_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class Status(BaseModel):
    configured: bool
    mailbox: str | None
    last_run_at: datetime | None
    last_error: str | None
    stored: int
    rejected: int
    unmatched_reports: int


class DomainRow(BaseModel):
    client_id: str
    client_name: str
    matched: bool
    domain: str
    reports: int
    total: int
    passed: int
    failed: int
    pass_rate: float | None
    policy: str
    last_report: datetime


class Overview(BaseModel):
    days: int
    status: Status
    domains: list[DomainRow]


class DayPoint(BaseModel):
    day: str
    total: int
    passed: int
    failed: int


class FailingSource(BaseModel):
    ip: str
    count: int
    header_from: str
    envelope_from: str
    disposition: str


class DomainDetail(BaseModel):
    domain: str
    days: int
    reports: int
    total: int
    passed: int
    failed: int
    policy: str
    series: list[DayPoint]
    failing_sources: list[FailingSource]


class SetupLine(BaseModel):
    client_id: str
    client_name: str
    domain: str
    alias: str
    client_dmarc_rua: str
    authorization_record_name: str
    authorization_record_value: str


class Setup(BaseModel):
    mailbox: str | None
    mailbox_domain: str | None
    lines: list[SetupLine]


def _configured() -> bool:
    return bool(settings.DMARC_MAILBOX.strip() and settings.DMARC_OWNER_TENANT_ID.strip())


async def _children(db: Any, owner: Any) -> dict[Any, Tenant]:
    async with cross_tenant_reads(db):
        rows = (await db.execute(select(Tenant).where(Tenant.parent_tenant_id == owner))).scalars().all()
    return {t.id: t for t in rows}


async def _status(db: Any, owner: Any) -> Status:
    async with cross_tenant_reads(db):
        state = (await db.execute(select(DmarcIngestState).where(DmarcIngestState.tenant_id == owner))).scalar_one_or_none()
        unmatched = len((await db.execute(select(DmarcReport.id).where(DmarcReport.tenant_id == owner, DmarcReport.matched.is_(False)))).scalars().all())
    return Status(
        configured=_configured(),
        mailbox=settings.DMARC_MAILBOX.strip() or None,
        last_run_at=state.last_run_at if state else None,
        last_error=state.last_error if state else None,
        stored=state.stored if state else 0,
        rejected=state.rejected if state else 0,
        unmatched_reports=unmatched,
    )


@router.get("/overview", response_model=Overview, summary="Each client domain's DMARC results over the last N days")
async def overview(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, days: int = Query(30, ge=1, le=365)
) -> Overview:
    owner = current_user.tenant_id
    clients = await _children(db, owner)
    async with cross_tenant_reads(db):
        owner_name = (await db.execute(select(Tenant.name).where(Tenant.id == owner))).scalar_one_or_none() or "This company"
    since = datetime.now(UTC) - timedelta(days=days)
    async with cross_tenant_reads(db):
        reports = (
            await db.execute(
                select(DmarcReport).where(DmarcReport.tenant_id.in_([owner, *clients]), DmarcReport.end_at >= since).order_by(DmarcReport.end_at.desc())
            )
        ).scalars().all()
    groups: dict[tuple[Any, str], list[DmarcReport]] = defaultdict(list)
    for r in reports:
        groups[(r.tenant_id, r.domain)].append(r)
    rows: list[DomainRow] = []
    for (tenant_id, domain), items in groups.items():
        total, passed = sum(i.total for i in items), sum(i.passed for i in items)
        rows.append(
            DomainRow(
                client_id=str(tenant_id),
                # the managing company's own domain is matched too (to itself); only a domain nobody could be matched to is "not matched"
                client_name=clients[tenant_id].name if tenant_id in clients else (f"{owner_name} (own)" if all(i.matched for i in items) else "Not matched to a client"),
                matched=all(i.matched for i in items),
                domain=domain,
                reports=len(items),
                total=total,
                passed=passed,
                failed=total - passed,
                pass_rate=round(passed * 100.0 / total, 1) if total else None,
                policy=items[0].policy,  # the newest report's published policy
                last_report=items[0].end_at,
            )
        )
    rows.sort(key=lambda r: (r.pass_rate if r.pass_rate is not None else 101.0, r.client_name, r.domain))  # the worst first
    return Overview(days=days, status=await _status(db, owner), domains=rows)


@router.get("/domains/{domain}", response_model=DomainDetail, summary="One domain: its daily results and the sources failing DMARC")
async def domain_detail(
    domain: str, current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, days: int = Query(30, ge=1, le=365)
) -> DomainDetail:
    domain = domain.strip().lower().rstrip(".")
    if not _DOMAIN.match(domain):
        raise HTTPException(status_code=422, detail="That is not a domain name.")
    owner = current_user.tenant_id
    clients = await _children(db, owner)
    since = datetime.now(UTC) - timedelta(days=days)
    async with cross_tenant_reads(db):
        reports = (
            await db.execute(
                select(DmarcReport)
                .where(DmarcReport.tenant_id.in_([owner, *clients]), DmarcReport.domain == domain, DmarcReport.end_at >= since)
                .order_by(DmarcReport.end_at.desc())
            )
        ).scalars().all()
    if not reports:
        raise HTTPException(status_code=404, detail="No reports for that domain in this period.")
    daily: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    failing: Counter[tuple[str, str, str, str]] = Counter()
    for r in reports:
        day = r.end_at.astimezone(UTC).date().isoformat() if r.end_at.tzinfo else r.end_at.date().isoformat()
        daily[day][0] += r.total
        daily[day][1] += r.passed
        daily[day][2] += r.failed
        for row in r.rows or []:
            if not row.get("pass"):
                failing[(str(row.get("ip", "")), str(row.get("header_from", "")), str(row.get("envelope_from", "")), str(row.get("disposition", "")))] += int(row.get("count", 0))
    total, passed = sum(r.total for r in reports), sum(r.passed for r in reports)
    return DomainDetail(
        domain=domain,
        days=days,
        reports=len(reports),
        total=total,
        passed=passed,
        failed=total - passed,
        policy=reports[0].policy,
        series=[DayPoint(day=d, total=v[0], passed=v[1], failed=v[2]) for d, v in sorted(daily.items())],
        failing_sources=[FailingSource(ip=k[0], count=n, header_from=k[1], envelope_from=k[2], disposition=k[3]) for k, n in failing.most_common(25)],
    )


@router.get("/setup", response_model=Setup, summary="For each client domain: the address to put in its DMARC record and the DNS line that authorises it")
async def setup(current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> Setup:
    """Nothing is changed. Each client domain gets its own alias on the shared mailbox (so its reports are recognisable and can be retired alone) and the one DNS record, in YOUR zone, that lets receivers send a
    client domain's reports to you (receivers require it before reporting to a different domain)."""
    mailbox = settings.DMARC_MAILBOX.strip() or None
    mailbox_domain = mailbox.rpartition("@")[2].lower() if mailbox and "@" in mailbox else None
    owner = current_user.tenant_id
    clients = await _children(db, owner)
    lines: list[SetupLine] = []
    if mailbox_domain and clients:
        async with cross_tenant_reads(db):
            upns = (await db.execute(select(IdentityMfaUser.tenant_id, IdentityMfaUser.upn).where(IdentityMfaUser.tenant_id.in_(list(clients))))).all()
            mails = (await db.execute(select(IdentitySource.tenant_id, IdentitySource.email).where(IdentitySource.tenant_id.in_(list(clients))))).all()
        emails: dict[Any, list[str]] = defaultdict(list)
        for tenant_id, address in [*upns, *mails]:
            emails[tenant_id].append(address)
        for tenant_id, tenant in sorted(clients.items(), key=lambda kv: kv[1].name.lower()):
            alias = f"{re.sub(r'[^a-z0-9-]', '-', tenant.slug.lower())[:48].strip('-') or 'client'}@{mailbox_domain}"
            for domain in candidate_domains(emails.get(tenant_id, [])):
                lines.append(
                    SetupLine(
                        client_id=str(tenant_id),
                        client_name=tenant.name,
                        domain=domain,
                        alias=alias,
                        client_dmarc_rua=f"rua=mailto:{alias}",
                        authorization_record_name=f"{domain}._report._dmarc.{mailbox_domain}",
                        authorization_record_value="v=DMARC1",
                    )
                )
    return Setup(mailbox=mailbox, mailbox_domain=mailbox_domain, lines=lines)

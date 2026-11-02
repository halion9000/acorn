"""DMARC reports per client: what receivers saw being sent as each client's domains, and the setup lines for pointing a client's reports at the shared mailbox.

Reads only. The reports arrive through the shared mailbox (app/workers/dmarc_ingest_worker.py); nothing here sends mail or changes DNS.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
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
from app.services.dmarc_senders import identify_sender
from app.services.domain_posture import DohResolver, Resolver, candidate_domains

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
    # False when the domain has no mail records (MX), so it cannot receive or send mail and has nothing to report. True when it has some, or when that could not be told (a domain is never
    # hidden on a failed lookup).
    has_mx: bool = True


class Setup(BaseModel):
    mailbox: str | None
    mailbox_domain: str | None
    lines: list[SetupLine]


def alias_names(clients: dict[Any, Tenant]) -> dict[Any, str]:
    """A readable mailbox alias (the part before the @) for each client. It comes from the client's slug, with the random six-character tail the slug carries for uniqueness taken off, so
    ``acme-dental-1a2b3c`` becomes ``acme-dental``. Two clients that would end up with the same name keep their full slug, so no two clients ever share an alias."""

    def full(t: Tenant) -> str:
        return re.sub(r"[^a-z0-9-]", "-", t.slug.lower())[:48].strip("-") or "client"

    def short(t: Tenant) -> str:
        return re.sub(r"-[0-9a-f]{6}$", "", full(t)).strip("-") or full(t)

    counts = Counter(short(t) for t in clients.values())
    return {tid: (short(t) if counts[short(t)] == 1 else full(t)) for tid, t in clients.items()}


_MX_TTL_SECONDS = 3600
_MX_CACHE: dict[str, tuple[float, bool]] = {}


def get_resolver() -> Resolver:
    """The DNS resolver the mail-record check uses (replaced in tests)."""
    return DohResolver()


async def mail_domains(domains: list[str], resolver: Resolver, now: float | None = None) -> dict[str, bool]:
    """For each domain: does it have mail records (an MX that is not the "null MX" of RFC 7505, which says "no mail here")? A lookup that comes back empty is tried once more before the domain is called
    mail-less, and a lookup that fails outright counts as "has mail": a domain is hidden only when it is clearly mail-less. Answers are kept for an hour so the page stays quick."""
    stamp = time.monotonic() if now is None else now
    gate = asyncio.Semaphore(10)

    async def one(domain: str) -> tuple[str, bool]:
        cached = _MX_CACHE.get(domain)
        if cached and stamp - cached[0] < _MX_TTL_SECONDS:
            return domain, cached[1]
        async with gate:
            try:
                hosts = [h for h in await resolver.mx(domain) if h]
                if not hosts:
                    hosts = [h for h in await resolver.mx(domain) if h]
            except Exception:  # noqa: BLE001  # a failed lookup must never hide a domain
                return domain, True
        _MX_CACHE[domain] = (stamp, bool(hosts))
        return domain, bool(hosts)

    return dict(await asyncio.gather(*(one(d) for d in sorted(set(domains)))))


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


class Delivery(BaseModel):
    """What became of the mail, in the order a person cares about it. Every message counts in exactly one of these."""

    passed: int  # passed DMARC and was delivered
    failed_delivered: int  # failed DMARC but was delivered anyway (the policy is monitor-only)
    overridden: int  # delivered although the policy said otherwise: the receiver overrode it (forwarded, mailing list...)
    quarantined: int
    rejected: int


class FailureRates(BaseModel):
    dmarc: float | None
    dkim: float | None
    spf: float | None


class RatePoint(BaseModel):
    day: str
    total: int
    dmarc_fail: int
    dkim_fail: int
    spf_fail: int


class SenderRow(BaseModel):
    name: str
    identified: bool  # False: not a service we recognise, shown by its address
    emails: int
    passed: int
    failed: int
    status: str  # passing (nothing failed), failing (nothing passed) or partly


class SendingDomainRow(BaseModel):
    domain: str
    emails: int
    passed: int
    failed: int
    status: str


class Insights(BaseModel):
    days: int
    domain: str | None
    emails: int
    delivery: Delivery
    rates: FailureRates
    series: list[RatePoint]
    senders: list[SenderRow]
    sending_domains: list[SendingDomainRow]


def _health(passed: int, failed: int) -> str:
    return "passing" if failed == 0 else "failing" if passed == 0 else "partly"


def _pct(part: int, whole: int) -> float | None:
    return round(part * 100.0 / whole, 1) if whole else None


def delivery_class(row: dict[str, Any]) -> str:
    """Which of the five outcomes one source line belongs to. What the receiver DID decides it first (quarantine, reject); for delivered mail an override reason says the policy was set aside, and
    otherwise it is delivered because it passed or because the policy only monitors."""
    disposition = str(row.get("disposition", "none")).lower()
    if disposition == "quarantine":
        return "quarantined"
    if disposition == "reject":
        return "rejected"
    if row.get("reason"):
        return "overridden"
    return "passed" if row.get("pass") else "failed_delivered"


@router.get("/insights", response_model=Insights, summary="Delivery, failure rates over time, top senders and top sending domains")
async def insights(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    days: int = Query(30, ge=1, le=365),
    domain: str | None = Query(default=None, max_length=255),
    client_id: str | None = Query(default=None, max_length=64),
) -> Insights:
    """Everything the Valimail-style overview shows, computed from the stored reports: for all clients, one client, or one domain. Counts are messages, not reports."""
    owner = current_user.tenant_id
    clients = await _children(db, owner)
    wanted = [owner, *clients]
    if client_id:
        try:
            only = uuid.UUID(client_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="That is not a client id.") from None
        if only not in wanted:
            raise HTTPException(status_code=404, detail="Client not found")
        wanted = [only]
    where = [DmarcReport.tenant_id.in_(wanted), DmarcReport.end_at >= datetime.now(UTC) - timedelta(days=days)]
    clean = None
    if domain:
        clean = domain.strip().lower().rstrip(".")
        if not _DOMAIN.match(clean):
            raise HTTPException(status_code=422, detail="That is not a domain name.")
        where.append(DmarcReport.domain == clean)
    async with cross_tenant_reads(db):
        reports = (await db.execute(select(DmarcReport).where(*where))).scalars().all()

    delivery: Counter[str] = Counter()
    daily: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    senders: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    from_domains: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    total = dmarc_fail = dkim_fail = spf_fail = 0
    for r in reports:
        day = r.end_at.astimezone(UTC).date().isoformat() if r.end_at.tzinfo else r.end_at.date().isoformat()
        for row in r.rows or []:
            count = int(row.get("count", 0))
            ok = bool(row.get("pass"))
            total += count
            delivery[delivery_class(row)] += count
            d = daily[day]
            d[0] += count
            if not ok:
                dmarc_fail += count
                d[1] += count
            if not row.get("dkim"):
                dkim_fail += count
                d[2] += count
            if not row.get("spf"):
                spf_fail += count
                d[3] += count
            name = identify_sender(list(row.get("spf_domains") or []), list(row.get("dkim_domains") or []))
            key = (name, "named") if name else (str(row.get("ip") or "unknown"), "address")
            senders[key][0 if ok else 1] += count
            from_domains[str(row.get("header_from") or r.domain)][0 if ok else 1] += count

    def top_senders() -> list[SenderRow]:
        rows = [
            SenderRow(name=name if kind == "named" else f"Unknown ({name})", identified=kind == "named", emails=p + f, passed=p, failed=f, status=_health(p, f))
            for (name, kind), (p, f) in senders.items()
        ]
        return sorted(rows, key=lambda s: -s.emails)[:10]

    return Insights(
        days=days,
        domain=clean,
        emails=total,
        delivery=Delivery(
            passed=delivery["passed"], failed_delivered=delivery["failed_delivered"], overridden=delivery["overridden"], quarantined=delivery["quarantined"], rejected=delivery["rejected"]
        ),
        rates=FailureRates(dmarc=_pct(dmarc_fail, total), dkim=_pct(dkim_fail, total), spf=_pct(spf_fail, total)),
        series=[RatePoint(day=k, total=v[0], dmarc_fail=v[1], dkim_fail=v[2], spf_fail=v[3]) for k, v in sorted(daily.items())],
        senders=top_senders(),
        sending_domains=sorted(
            (SendingDomainRow(domain=k, emails=p + f, passed=p, failed=f, status=_health(p, f)) for k, (p, f) in from_domains.items()), key=lambda s: -s.emails
        )[:10],
    )


@router.get("/setup", response_model=Setup, summary="For each client domain: the address to put in its DMARC record and the DNS line that authorises it")
async def setup(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, resolver: Annotated[Resolver, Depends(get_resolver)]
) -> Setup:
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
        locals_by_client = alias_names(clients)
        for tenant_id, tenant in sorted(clients.items(), key=lambda kv: kv[1].name.lower()):
            alias = f"{locals_by_client[tenant_id]}.dmarc@{mailbox_domain}"  # e.g. lonestar.dmarc@: the name says what the address is for
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
    if lines:
        has_mail = await mail_domains([ln.domain for ln in lines], resolver)
        for ln in lines:
            ln.has_mx = has_mail.get(ln.domain, True)
    return Setup(mailbox=mailbox, mailbox_domain=mailbox_domain, lines=lines)

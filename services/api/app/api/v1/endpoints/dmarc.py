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
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.core.config import settings
from app.db.rls_scope import cross_tenant_reads
from app.models.dmarc import DmarcIngestState, DmarcReport, TlsReport
from app.models.identity_source import IdentitySource
from app.models.signin import IdentityMfaUser
from app.models.tenant import Tenant
from app.services import bimi as bimi_check
from app.services import blocklist, safe_fetch
from app.services import reputation as reputation_service
from app.services.dmarc_senders import identify_sender
from app.services.domain_posture import DohResolver, DomainPosture, Resolver, candidate_domains, check_domain
from app.services.ip_country import country_of
from app.services.lookalike import generate as generate_lookalikes
from app.services.lookalike import scan as scan_lookalikes

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
    # The record that asks receivers for TLS reports (TLS-RPT, RFC 8460). Unlike DMARC it needs no authorisation record in the shared mailbox's zone.
    tls_rpt_name: str = ""
    tls_rpt_value: str = ""


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
    at_risk: list[SenderRow]  # senders whose mail fails DMARC: what an enforcing policy (quarantine or reject) would start to block
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


async def _scoped_reports(current_user: AuthUser, db: Any, days: int, domain: str | None, client_id: str | None) -> tuple[list[DmarcReport], str | None]:
    """The stored reports the caller may see (their own and their clients'), narrowed to one client or domain; the domain as cleaned. 422 for a malformed filter, 404 for a client that is not theirs."""
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
    return list(reports), clean


class CountryRow(BaseModel):
    code: str  # two-letter country code
    emails: int
    passed: int
    failed: int


class Countries(BaseModel):
    days: int
    emails: int
    countries: list[CountryRow]
    unknown: int  # messages from addresses whose country could not be found (private, or the lookup did not answer)
    not_looked_up: int  # messages from the quieter addresses beyond the busiest MAX_LOOKUPS, not asked about


MAX_LOOKUPS = 60


@router.get("/countries", response_model=Countries, summary="Where the mail was sent from, by country")
async def countries(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    resolver: Annotated[Resolver, Depends(get_resolver)],
    days: int = Query(30, ge=1, le=365),
    domain: str | None = Query(default=None, max_length=255),
    client_id: str | None = Query(default=None, max_length=64),
) -> Countries:
    """Country of each sending address, looked up for the busiest addresses only (a quiet tail is reported as not looked up rather than guessed or fetched one by one)."""
    reports, _ = await _scoped_reports(current_user, db, days, domain, client_id)
    by_ip: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    total = 0
    for r in reports:
        for row in r.rows or []:
            count = int(row.get("count", 0))
            total += count
            by_ip[str(row.get("ip") or "")][0 if row.get("pass") else 1] += count
    busiest = sorted(by_ip.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))[:MAX_LOOKUPS]
    found = await asyncio.gather(*(country_of(ip, resolver) for ip, _ in busiest))
    per: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    unknown = 0
    for (_, (p, f)), code in zip(busiest, found, strict=True):
        if code is None:
            unknown += p + f
        else:
            per[code][0] += p
            per[code][1] += f
    looked = sum(p + f for _, (p, f) in busiest)
    return Countries(
        days=days,
        emails=total,
        countries=sorted((CountryRow(code=c, emails=p + f, passed=p, failed=f) for c, (p, f) in per.items()), key=lambda c: -c.emails),
        unknown=unknown,
        not_looked_up=total - looked,
    )


class ReportCard(BaseModel):
    domain: str
    days: int
    total: int
    pass_rate: float | None
    policy: str
    posture: DomainPosture  # the live DNS check: mail records, SPF, DMARC, DKIM
    advice: list[str]  # plain-language next steps, most useful first


MIN_MAIL_TO_JUDGE = 100


def report_card_advice(policy: str, pass_rate: float | None, total: int, posture: DomainPosture) -> list[str]:
    """What to do next for one domain, from its published policy, how much of its mail passes, and what DNS says. Rules only: no guessing about senders."""
    out: list[str] = []
    has_mail = bool(posture.mx)
    if not has_mail:
        out.append("This domain has no mail records, so it should not send mail. Publishing a reject policy and an SPF record that allows nobody stops others pretending to be it.")
    if total < MIN_MAIL_TO_JUDGE or pass_rate is None:
        out.append(f"Only {total:,} messages so far, which is too few to judge. Wait for more reports before changing the policy.")
    elif policy == "none":
        if pass_rate >= 98:
            out.append(f"{pass_rate}% of mail passes and the policy only monitors. It is reasonable to start enforcing: move to quarantine for a small share first (p=quarantine; pct=25), then raise it.")
        else:
            out.append(f"Only {pass_rate}% of mail passes. Find the failing senders (the list below) and fix or remove them before enforcing, or real mail will be quarantined.")
    elif policy == "quarantine":
        if pass_rate >= 99.5:
            out.append(f"{pass_rate}% passes under quarantine. The next step is reject, which stops pretenders completely.")
        elif pass_rate < 95:
            out.append(f"{pass_rate}% passes while failing mail is being quarantined. Check that the failures are not real mail going to spam.")
    elif policy == "reject" and pass_rate is not None and pass_rate < 95:
        out.append(f"{pass_rate}% passes under a reject policy. Real mail may be bouncing: check the failing senders now.")
    elif policy == "reject":
        out.append("Fully enforced: this is the strongest setting. Keep watching the failing list for new senders.")
    # The policy is already covered above (and known better from the reports), so a DMARC finding is only added when the record itself is missing or unreadable.
    for f, covered in ((posture.spf, False), (posture.dmarc, posture.dmarc.record is not None)):
        if f.status != "good" and not covered:
            out.extend(f.issues or [f.summary])
    return out


@router.get("/domains/{domain}/card", response_model=ReportCard, summary="One domain's report card: results, live DNS check and next steps")
async def domain_report_card(
    domain: str,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    resolver: Annotated[Resolver, Depends(get_resolver)],
    days: int = Query(30, ge=1, le=365),
) -> ReportCard:
    """Only a domain that has reports in the caller's data is checked (so this cannot be used to probe arbitrary domains)."""
    reports, clean = await _scoped_reports(current_user, db, days, domain, None)
    if not reports or clean is None:
        raise HTTPException(status_code=404, detail="No reports for that domain in this period.")
    total = sum(r.total for r in reports)
    passed = sum(r.passed for r in reports)
    newest = max(reports, key=lambda r: r.end_at)
    posture = await check_domain(clean, resolver)
    rate = _pct(passed, total)
    return ReportCard(domain=clean, days=days, total=total, pass_rate=rate, policy=newest.policy, posture=posture, advice=report_card_advice(newest.policy, rate, total, posture))


class LookalikeRow(BaseModel):
    domain: str
    kind: str
    has_mail: bool  # can receive (and so send) mail: the ones that can pretend to be the client


class Lookalikes(BaseModel):
    domain: str
    checked: int  # how many lookalike names were generated and asked about
    found: list[LookalikeRow]


@router.get("/domains/{domain}/lookalikes", response_model=Lookalikes, summary="Look-alike domains of one of the caller's domains that exist in DNS")
async def domain_lookalikes(
    domain: str,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    resolver: Annotated[Resolver, Depends(get_resolver)],
) -> Lookalikes:
    """Only a domain with reports in the caller's data is scanned. Read-only DNS questions about the lookalike names; no connection is made to them."""
    reports, clean = await _scoped_reports(current_user, db, 365, domain, None)
    if not reports or clean is None:
        raise HTTPException(status_code=404, detail="No reports for that domain.")
    found = await scan_lookalikes(clean, resolver)
    return Lookalikes(domain=clean, checked=len(generate_lookalikes(clean)), found=[LookalikeRow(domain=x.domain, kind=x.kind, has_mail=x.has_mail) for x in found])


def get_cert_fetcher() -> bimi_check.Fetcher:
    """How the BIMI certificate is fetched (replaced in tests)."""
    return bimi_check.public_https_fetch


@router.get("/domains/{domain}/bimi", response_model=bimi_check.Bimi, summary="BIMI brand-logo check for one of the caller's domains")
async def domain_bimi(
    domain: str,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    resolver: Annotated[Resolver, Depends(get_resolver)],
    fetch: Annotated[bimi_check.Fetcher, Depends(get_cert_fetcher)],
) -> bimi_check.Bimi:
    """Only a domain with reports in the caller's data is checked. The certificate address in its public record is fetched with care (https, public address, no redirects, size limit)."""
    reports, clean = await _scoped_reports(current_user, db, 365, domain, None)
    if not reports or clean is None:
        raise HTTPException(status_code=404, detail="No reports for that domain.")
    return await bimi_check.check(clean, resolver, fetch)


class ListRow(BaseModel):
    list_name: str
    status: str  # listed, clear, refused (the list will not answer us) or no_answer (the lookup failed)
    detail: str


class AddressBlocklists(BaseModel):
    ip: str
    emails: int
    results: list[ListRow]


class Blocklists(BaseModel):
    domain: str
    domain_results: list[ListRow]
    addresses: list[AddressBlocklists]
    listed: int
    not_checked: int  # answers that were refused or did not arrive: these are not "clear"


MAX_BLOCKLIST_ADDRESSES = 20


def get_blocklist_lookup() -> blocklist.Lookup:
    """How blocklists are asked: the server's own resolver (replaced in tests)."""
    return blocklist.system_lookup


def _rows(results: list[blocklist.ListResult]) -> list[ListRow]:
    return [ListRow(list_name=r.list_name, status=r.status, detail=r.detail) for r in results]


@router.get("/domains/{domain}/blocklists", response_model=Blocklists, summary="Blocklist status of one of the caller's domains and its busiest sending addresses")
async def domain_blocklists(
    domain: str,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    lookup: Annotated[blocklist.Lookup, Depends(get_blocklist_lookup)],
    days: int = Query(30, ge=1, le=365),
) -> Blocklists:
    """The domain on the domain lists, and the busiest public sending addresses (from its reports) on the address lists. A list that refuses or does not answer is reported as that, never as clear."""
    reports, clean = await _scoped_reports(current_user, db, days, domain, None)
    if not reports or clean is None:
        raise HTTPException(status_code=404, detail="No reports for that domain in this period.")
    volume: Counter[str] = Counter()
    for r in reports:
        for row in r.rows or []:
            volume[str(row.get("ip") or "")] += int(row.get("count", 0))
    busiest = [(ip, n) for ip, n in volume.most_common() if blocklist.reverse_ipv4(ip)][:MAX_BLOCKLIST_ADDRESSES]
    domain_results, *per_ip = await asyncio.gather(blocklist.check_domain(clean, lookup), *(blocklist.check_ip(ip, lookup) for ip, _ in busiest))
    addresses = [AddressBlocklists(ip=ip, emails=n, results=_rows(res)) for (ip, n), res in zip(busiest, per_ip, strict=True)]
    everything = [*domain_results, *(r for res in per_ip for r in res)]
    return Blocklists(
        domain=clean,
        domain_results=_rows(domain_results),
        addresses=addresses,
        listed=sum(1 for r in everything if r.status == "listed"),
        not_checked=sum(1 for r in everything if r.status in ("refused", "no_answer")),
    )


class ReputationFact(BaseModel):
    label: str
    text: str
    tone: str  # good, warn, bad or unknown


class Reputation(BaseModel):
    domain: str
    facts: list[ReputationFact]


def get_rdap_fetcher() -> Callable[[str], Awaitable[bytes]]:
    """How the public registration record is fetched (replaced in tests): https to a public address, a few redirects (the lookup service hands over to the registry)."""

    async def fetch(url: str) -> bytes:
        return await safe_fetch.fetch(url, max_bytes=500_000, max_redirects=3, accept="application/rdap+json, application/json")

    return fetch


@router.get("/domains/{domain}/reputation", response_model=Reputation, summary="Facts that bear on one of the caller's domains' reputation (registration age, expiry, its own mail)")
async def domain_reputation(
    domain: str,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    fetch: Annotated[Callable[[str], Awaitable[bytes]], Depends(get_rdap_fetcher)],
    days: int = Query(30, ge=1, le=365),
) -> Reputation:
    """Only a domain with reports in the caller's data is looked up. No single score: a few facts, each marked good, warning, bad or unknown. A registration record that cannot be fetched or read is unknown."""
    reports, clean = await _scoped_reports(current_user, db, days, domain, None)
    if not reports or clean is None:
        raise HTTPException(status_code=404, detail="No reports for that domain in this period.")
    total = sum(r.total for r in reports)
    passed = sum(r.passed for r in reports)
    registration, problem = None, None
    try:
        registration = reputation_service.parse_rdap(await fetch(reputation_service.RDAP_URL.format(domain=clean)))
    except safe_fetch.FetchRefused as e:
        problem = f"The registration record could not be fetched: {e}"
    except ValueError as e:
        problem = str(e)
    newest = max(reports, key=lambda r: r.end_at)
    items = reputation_service.facts(registration, problem, newest.policy, _pct(passed, total), total, total - passed)
    return Reputation(domain=clean, facts=[ReputationFact(label=f.label, text=f.text, tone=f.tone) for f in items])


class TlsFailureKind(BaseModel):
    type: str
    count: int


class TlsDomainRow(BaseModel):
    domain: str
    client_id: str
    matched: bool
    reports: int
    success: int
    failure: int
    success_rate: float | None
    failures: list[TlsFailureKind]  # why sessions failed, most common first
    last_report: datetime


class TlsOverview(BaseModel):
    days: int
    domains: list[TlsDomainRow]


@router.get("/tls", response_model=TlsOverview, summary="TLS reports per domain: how many TLS-protected connections to the domain's mail servers worked, and why the rest failed")
async def tls_overview(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    days: int = Query(30, ge=1, le=365),
) -> TlsOverview:
    owner = current_user.tenant_id
    clients = await _children(db, owner)
    since = datetime.now(UTC) - timedelta(days=days)
    async with cross_tenant_reads(db):
        rows = (await db.execute(select(TlsReport).where(TlsReport.tenant_id.in_([owner, *clients]), TlsReport.end_at >= since))).scalars().all()
    groups: dict[tuple[uuid.UUID, str], list[TlsReport]] = defaultdict(list)
    for r in rows:
        groups[(r.tenant_id, r.domain)].append(r)
    out: list[TlsDomainRow] = []
    for (tenant_id, domain), items in groups.items():
        success, failure = sum(i.success for i in items), sum(i.failure for i in items)
        kinds: Counter[str] = Counter()
        for i in items:
            for f in i.failures or []:
                kinds[str(f.get("type", ""))] += int(f.get("count", 0))
        out.append(
            TlsDomainRow(
                domain=domain,
                client_id=str(tenant_id),
                matched=all(i.matched for i in items),
                reports=len(items),
                success=success,
                failure=failure,
                success_rate=_pct(success, success + failure),
                failures=[TlsFailureKind(type=k, count=n) for k, n in kinds.most_common(5) if k],
                last_report=max(i.end_at for i in items),
            )
        )
    out.sort(key=lambda r: (r.success_rate if r.success_rate is not None else 101.0, r.domain))  # the worst first
    return TlsOverview(days=days, domains=out)


@router.get("/insights", response_model=Insights, summary="Delivery, failure rates over time, top senders and top sending domains")
async def insights(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    days: int = Query(30, ge=1, le=365),
    domain: str | None = Query(default=None, max_length=255),
    client_id: str | None = Query(default=None, max_length=64),
) -> Insights:
    """Everything the Valimail-style overview shows, computed from the stored reports: for all clients, one client, or one domain. Counts are messages, not reports."""
    reports, clean = await _scoped_reports(current_user, db, days, domain, client_id)

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

    sender_rows = [
        SenderRow(name=name if kind == "named" else f"Unknown ({name})", identified=kind == "named", emails=p + f, passed=p, failed=f, status=_health(p, f))
        for (name, kind), (p, f) in senders.items()
    ]
    # At risk: any sender (not only the busiest) with failures, most failing messages first. A sender with a handful of failures among thousands is still listed: the count says how small it is.
    at_risk = sorted((x for x in sender_rows if x.failed > 0), key=lambda x: -x.failed)[:10]

    return Insights(
        days=days,
        domain=clean,
        emails=total,
        delivery=Delivery(
            passed=delivery["passed"], failed_delivered=delivery["failed_delivered"], overridden=delivery["overridden"], quarantined=delivery["quarantined"], rejected=delivery["rejected"]
        ),
        rates=FailureRates(dmarc=_pct(dmarc_fail, total), dkim=_pct(dkim_fail, total), spf=_pct(spf_fail, total)),
        series=[RatePoint(day=k, total=v[0], dmarc_fail=v[1], dkim_fail=v[2], spf_fail=v[3]) for k, v in sorted(daily.items())],
        senders=sorted(sender_rows, key=lambda x: -x.emails)[:10],
        at_risk=at_risk,
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
                        tls_rpt_name=f"_smtp._tls.{domain}",
                        tls_rpt_value=f"v=TLSRPTv1; rua=mailto:{alias}",
                    )
                )
    if lines:
        has_mail = await mail_domains([ln.domain for ln in lines], resolver)
        for ln in lines:
            ln.has_mx = has_mail.get(ln.domain, True)
    return Setup(mailbox=mailbox, mailbox_domain=mailbox_domain, lines=lines)

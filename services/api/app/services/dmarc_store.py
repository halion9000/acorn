"""Keeping DMARC aggregate reports per client: finding which client a report's domain belongs to, and storing each report once.

A client's domains are not typed in anywhere: they are the e-mail domains of the people A.C.O.R.N already holds for it (see domain_posture.candidate_domains). A report about ``client.com`` goes
to the client whose people use that domain most. When no client matches (or two match equally) the report is kept under the owner's own tenant with ``matched`` False, so nothing is lost and a
person can see what is waiting to be matched.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.rls_scope import cross_tenant_reads
from app.models.dmarc import DmarcReport, TlsReport
from app.models.signin import IdentityMfaUser
from app.models.identity_source import IdentitySource
from app.models.tenant import Tenant
from app.services.dmarc_report import DmarcReport as ParsedReport
from app.services.tls_report import TlsPolicy
from app.services.tls_report import TlsReport as ParsedTls

MAX_ROWS_STORED = 500


@dataclass(frozen=True)
class Stored:
    outcome: str  # "stored" or "duplicate"
    tenant_id: uuid.UUID
    matched: bool


async def _people_by_tenant(db, tenant_ids: set[uuid.UUID], domain: str) -> Counter[uuid.UUID]:
    counts: Counter[uuid.UUID] = Counter()
    suffix = f"%@{domain}"
    for column, tenant_column in ((IdentityMfaUser.upn, IdentityMfaUser.tenant_id), (IdentitySource.email, IdentitySource.tenant_id)):
        for tenant_id in (await db.execute(select(tenant_column).where(tenant_column.in_(tenant_ids), column.ilike(suffix)))).scalars().all():
            counts[tenant_id] += 1
    return counts


async def client_for_domain(db, owner_id: uuid.UUID, domain: str) -> uuid.UUID | None:
    """The client of ``owner_id`` whose people use ``domain`` most; the owner itself when it is the owner's OWN people who use it (the managing company's own domain); None when nobody does, or two
    clients are tied for it."""
    domain = domain.strip().lower().rstrip(".")
    if not domain:
        return None
    async with cross_tenant_reads(db):
        children = set((await db.execute(select(Tenant.id).where(Tenant.parent_tenant_id == owner_id))).scalars().all())
        counts = await _people_by_tenant(db, children, domain) if children else Counter()
        if not counts:
            own = await _people_by_tenant(db, {owner_id}, domain)
            return owner_id if own else None
    ranked = counts.most_common(2)
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def compact_rows(report: ParsedReport) -> list[dict]:
    """The report's per-source lines, biggest first, at most MAX_ROWS_STORED, as plain data for the database."""
    rows = sorted(report.records, key=lambda r: r.count, reverse=True)[:MAX_ROWS_STORED]
    return [
        {
            "ip": r.source_ip,
            "count": r.count,
            "disposition": r.disposition,
            "dkim": r.dkim_aligned,
            "spf": r.spf_aligned,
            "pass": r.dmarc_pass,
            "header_from": r.header_from,
            "envelope_from": r.envelope_from,
            "dkim_domains": r.dkim_domains,
            "spf_domains": r.spf_domains,
            "reason": r.reason,
        }
        for r in rows
    ]


async def store_report(db, owner_id: uuid.UUID, report: ParsedReport) -> Stored:
    """Store one parsed report under its client (or the owner when none matches). The same reporter's same report id for the same domain is stored once, however often it is read."""
    async with cross_tenant_reads(db):
        existing = (
            await db.execute(
                select(DmarcReport.id, DmarcReport.tenant_id, DmarcReport.matched).where(
                    DmarcReport.domain == report.domain, DmarcReport.reporter == report.reporter, DmarcReport.report_id == report.report_id
                )
            )
        ).first()
    if existing is not None:
        return Stored("duplicate", existing.tenant_id, existing.matched)
    client = await client_for_domain(db, owner_id, report.domain)
    tenant_id, matched = (client, True) if client is not None else (owner_id, False)
    row = DmarcReport(
        tenant_id=tenant_id,
        matched=matched,
        domain=report.domain,
        reporter=report.reporter,
        report_id=report.report_id,
        begin_at=report.begin,
        end_at=report.end,
        policy=report.policy,
        total=report.total,
        passed=report.passed,
        failed=report.failed,
        rows=compact_rows(report),
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        # Two readers stored the same report at once: the unique index decided.
        await db.rollback()
        return Stored("duplicate", tenant_id, matched)
    return Stored("stored", tenant_id, matched)


async def store_tls_policy(db, owner_id: uuid.UUID, report: ParsedTls, policy: TlsPolicy) -> Stored:
    """Store one policy of a TLS report under its client (or the owner when none matches), once however often the report is read."""
    async with cross_tenant_reads(db):
        existing = (
            await db.execute(
                select(TlsReport.id, TlsReport.tenant_id, TlsReport.matched).where(
                    TlsReport.domain == policy.domain, TlsReport.reporter == report.reporter, TlsReport.report_id == report.report_id, TlsReport.policy_type == policy.policy_type
                )
            )
        ).first()
    if existing is not None:
        return Stored("duplicate", existing.tenant_id, existing.matched)
    client = await client_for_domain(db, owner_id, policy.domain)
    tenant_id, matched = (client, True) if client is not None else (owner_id, False)
    db.add(
        TlsReport(
            tenant_id=tenant_id,
            matched=matched,
            domain=policy.domain,
            reporter=report.reporter,
            report_id=report.report_id,
            policy_type=policy.policy_type,
            begin_at=report.begin,
            end_at=report.end,
            success=policy.success,
            failure=policy.failure,
            failures=[{"type": t, "count": n} for t, n in policy.failures],
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return Stored("duplicate", tenant_id, matched)
    return Stored("stored", tenant_id, matched)

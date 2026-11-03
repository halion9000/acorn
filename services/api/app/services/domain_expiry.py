"""Alerts when a client's domain registration is about to end, or already has.

A lapsed domain stops the client's mail and website, and once it expires anyone can register it and receive mail meant for the client, so this is worth hearing about weeks ahead. The registration end date
comes from the public RDAP record (the same lookup the domain reputation check uses), kept per client and domain in ``domain_registrations`` and refreshed weekly, daily inside thirty days of the end, and
daily after a lookup that failed. A record that could not be read is kept as that, with the reason; it raises no alert (nothing is known) and is never treated as fine.

An alert is raised once per threshold crossed (thirty, fourteen, seven days, expired), not daily: its id is built from the client, the domain and the threshold.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services import reputation
from app.services.identity_detections import Finding, alert_values

logger = logging.getLogger("aisoc.domain_expiry")

RULE_ID = "aisoc-domain-expiry"
RULE_NAME = "Domain registration ending"
MAX_LOOKUPS_PER_PASS = 20  # a polite ceiling on the public service; the rest wait for the next pass
CONCURRENCY = 4
REFRESH_AFTER = timedelta(days=7)
REFRESH_NEAR_END_AFTER = timedelta(days=1)
REFRESH_AFTER_FAILURE = timedelta(days=1)
NEAR_END = timedelta(days=30)


@dataclass
class Known:
    """What is stored for one client domain."""

    tenant_id: uuid.UUID
    domain: str
    expires_at: datetime | None
    checked_at: datetime | None
    error: str | None = None


@dataclass
class Looked:
    expires_at: datetime | None
    registered: datetime | None
    error: str | None


def _utc(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def due_for_lookup(domains: list[tuple[uuid.UUID, str]], known: dict[tuple[uuid.UUID, str], Known], now: datetime) -> list[tuple[uuid.UUID, str]]:
    """The domains to look up this pass: never looked at first, then failures, then those nearest their end; at most ``MAX_LOOKUPS_PER_PASS``."""
    now = _utc(now)
    wanted: list[tuple[int, datetime, tuple[uuid.UUID, str]]] = []
    for key in domains:
        k = known.get(key)
        if k is None or k.checked_at is None:
            wanted.append((0, now, key))
            continue
        age = now - _utc(k.checked_at)
        if k.error is not None or k.expires_at is None:
            if age >= REFRESH_AFTER_FAILURE:
                wanted.append((1, _utc(k.checked_at), key))
        elif _utc(k.expires_at) - now <= NEAR_END:
            if age >= REFRESH_NEAR_END_AFTER:
                wanted.append((2, _utc(k.expires_at), key))
        elif age >= REFRESH_AFTER:
            wanted.append((3, _utc(k.checked_at), key))
    wanted.sort(key=lambda t: (t[0], t[1], str(t[2][0]), t[2][1]))
    return [key for _, _, key in wanted[:MAX_LOOKUPS_PER_PASS]]


async def look_up(domain: str, fetch: Callable[[str], Awaitable[bytes]]) -> Looked:
    """One RDAP lookup. A refusal, an unreadable record, or a record without an end date is an error with a short reason, never a guess."""
    try:
        registration = reputation.parse_rdap(await fetch(reputation.RDAP_URL.format(domain=domain)))
    except ValueError:
        return Looked(None, None, "The registration record was not understood.")
    except Exception as exc:  # noqa: BLE001  # a refused, slow or failed lookup is a reason, not a crash
        return Looked(None, None, f"The registration record could not be fetched ({type(exc).__name__}).")
    if registration.expires is None:
        return Looked(None, registration.registered, "The registration record has no expiry date.")
    return Looked(registration.expires, registration.registered, None)


def band(days_left: int) -> str | None:
    """The threshold a domain is inside: expired, 7, 14 or 30 days; None when comfortably far off."""
    if days_left < 0:
        return "expired"
    if days_left <= 7:
        return "7"
    if days_left <= 14:
        return "14"
    if days_left <= 30:
        return "30"
    return None


def detect_expiring(rows: list[Known], now: datetime) -> list[tuple[uuid.UUID, Finding]]:
    now = _utc(now)
    out: list[tuple[uuid.UUID, Finding]] = []
    for r in sorted(rows, key=lambda r: (str(r.tenant_id), r.domain)):
        if r.expires_at is None:
            continue
        ends = _utc(r.expires_at)
        days_left = (ends - now).days if ends >= now else -((now - ends).days + 1)
        b = band(days_left)
        if b is None:
            continue
        when = ends.strftime("%Y-%m-%d")
        if b == "expired":
            title = f"Domain {r.domain} has expired"
            severity = "high"
            summary = (
                f"The registration of {r.domain} ended on {when}. Its mail and website are down unless it is in a grace period, and once released anyone can register it and receive mail meant for the client. "
                "Renew it with the registrar now."
            )
        else:
            title = f"Domain {r.domain} expires in {max(days_left, 0)} day{'' if days_left == 1 else 's'}"
            severity = "high" if b == "7" else "medium" if b == "14" else "low"
            summary = f"The registration of {r.domain} ends on {when}. Renew it with the registrar; an auto-renew that quietly fails (an expired card) is the usual cause of a lapse."
        out.append(
            (
                r.tenant_id,
                Finding(
                    rule_id=RULE_ID,
                    rule_name=RULE_NAME,
                    title=title,
                    severity=severity,
                    tactic="Resource Development",
                    technique="T1584.001",
                    key=f"{r.domain}:{b}",
                    occurred_at=now,
                    summary=summary,
                    fields=[("Domain", r.domain), ("Registration ends", when), ("Checked", _utc(r.checked_at).strftime("%Y-%m-%d") if r.checked_at else "unknown")],
                ),
            )
        )
    return out


async def run_expiry_check(db: Any, fetch: Callable[[str], Awaitable[bytes]], now: datetime | None = None) -> tuple[int, int]:
    """Look up the domains that are due, store what was found, and raise alerts. Returns (lookups made, alerts that were new). Never raises."""
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.alert import Alert
    from app.models.dmarc import DmarcReport, DomainRegistration

    now = now or datetime.now(UTC)
    try:
        seen = (await db.execute(select(DmarcReport.tenant_id, DmarcReport.domain).where(DmarcReport.matched.is_(True), DmarcReport.end_at >= now - timedelta(days=90)).distinct())).all()
        domains = sorted({(t, d) for t, d in seen}, key=lambda k: (str(k[0]), k[1]))
        stored = (await db.execute(select(DomainRegistration))).scalars().all()
        known = {(s.tenant_id, s.domain): Known(s.tenant_id, s.domain, s.expires_at, s.checked_at, s.error) for s in stored}
        todo = due_for_lookup(domains, known, now)
        gate = asyncio.Semaphore(CONCURRENCY)

        async def one(key: tuple[uuid.UUID, str]) -> tuple[tuple[uuid.UUID, str], Looked]:
            async with gate:
                return key, await look_up(key[1], fetch)

        for (tenant_id, domain), got in await asyncio.gather(*(one(k) for k in todo)):
            values = {"tenant_id": tenant_id, "domain": domain, "registered": got.registered, "expires_at": got.expires_at, "checked_at": now, "error": got.error}
            await db.execute(
                pg_insert(DomainRegistration).values(**values).on_conflict_do_update(index_elements=["tenant_id", "domain"], set_={k: v for k, v in values.items() if k not in ("tenant_id", "domain")})
            )
            known[(tenant_id, domain)] = Known(tenant_id, domain, got.expires_at, now, got.error)
        made = 0
        async with db.begin_nested():
            for tenant_id, finding in detect_expiring([k for k in known.values() if (k.tenant_id, k.domain) in set(domains)], now):
                values = alert_values(tenant_id, finding, now)
                values.update(
                    category="domain",
                    connector_type="dmarc",
                    tags=["domain", "expiry", RULE_ID],
                    raw_event={"source": "aisoc-domain-expiry", "finding": {"uid": f"{RULE_ID}:{finding.key}", "title": finding.title}},
                )
                res = await db.execute(pg_insert(Alert).values(**values).on_conflict_do_nothing(index_elements=["id"]))
                made += res.rowcount or 0
        return len(todo), made
    except Exception:  # noqa: BLE001
        logger.warning("domain expiry check failed", exc_info=True)
        return 0, 0

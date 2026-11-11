"""BIMI check: does a domain publish a brand logo record, is the certificate it names valid and for how long, and is the domain's DMARC strong enough for mail clients to show the logo.

We only read. Issuing a Verified Mark Certificate needs a registered trademark and a certificate authority; what is useful here is knowing the logo will silently disappear when the certificate lapses.
The certificate address comes from a public DNS record anyone can write, so it is fetched with care: https only, a public address only, no redirects, a size limit and a short timeout.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography import x509
from cryptography.x509.oid import ObjectIdentifier
from pydantic import BaseModel

from app.services import safe_fetch
from app.services.domain_posture import Resolver, _tags
from app.services.safe_fetch import FetchRefused

MAX_CERT_BYTES = 200_000
EXPIRY_WARNING_DAYS = 30
_LOGOTYPE_OID = ObjectIdentifier("1.3.6.1.5.5.7.1.12")  # the logotype extension a Verified Mark Certificate carries

Fetcher = Callable[[str], Awaitable[bytes]]


class CertInfo(BaseModel):
    organization: str | None
    not_after: datetime
    days_left: int
    valid: bool
    is_vmc: bool  # carries the logotype extension of a Verified Mark Certificate


class Bimi(BaseModel):
    domain: str
    published: bool
    logo_url: str | None
    certificate_url: str | None
    dmarc_ready: bool
    certificate: CertInfo | None
    problems: list[str]  # what stops the logo showing, or is about to


@dataclass(frozen=True)
class BimiRecord:
    logo: str | None
    authority: str | None


def parse_record(txt: list[str]) -> BimiRecord | None:
    for t in txt:
        if t.strip().lower().startswith("v=bimi1"):
            tags = _tags(t.strip())
            return BimiRecord(tags.get("l") or None, tags.get("a") or None)
    return None


def dmarc_enforces(dmarc_txt: list[str]) -> tuple[bool, str]:
    """BIMI needs DMARC at quarantine or reject applied to all mail (pct 100)."""
    rec = next((t.strip() for t in dmarc_txt if t.strip().lower().startswith("v=dmarc1")), None)
    if rec is None:
        return False, "There is no DMARC record; BIMI needs one at quarantine or reject."
    tags = _tags(rec)
    policy = tags.get("p", "").lower()
    if policy not in ("quarantine", "reject"):
        return False, f"DMARC policy is '{policy or 'missing'}'; BIMI needs quarantine or reject."
    pct = tags.get("pct", "100")
    if pct.isdigit() and int(pct) < 100:
        return False, f"DMARC applies to only {pct}% of mail; BIMI needs 100%."
    return True, ""


def read_certificate(pem: bytes, now: datetime | None = None) -> CertInfo:
    """The first certificate in the file. Raises ValueError when it cannot be read as a certificate."""
    try:
        cert = x509.load_pem_x509_certificates(pem)[0]
    except (ValueError, IndexError):
        raise ValueError("The file is not a readable certificate (PEM).") from None
    moment = now or datetime.now(UTC)
    not_after = cert.not_valid_after_utc
    org = next((a.value for a in cert.subject if a.oid == x509.NameOID.ORGANIZATION_NAME), None)
    is_vmc = any(e.oid == _LOGOTYPE_OID for e in cert.extensions)
    return CertInfo(
        organization=str(org) if org else None,
        not_after=not_after,
        days_left=(not_after - moment).days,
        valid=cert.not_valid_before_utc <= moment <= not_after,
        is_vmc=is_vmc,
    )


async def public_https_fetch(url: str) -> bytes:
    """The certificate file: https, public address, no redirects, at most MAX_CERT_BYTES (see safe_fetch)."""
    return await safe_fetch.fetch(url, max_bytes=MAX_CERT_BYTES, max_redirects=0)


async def check(domain: str, resolver: Resolver, fetch: Fetcher = public_https_fetch, now: datetime | None = None) -> Bimi:
    bimi_txt, dmarc_txt = await asyncio.gather(resolver.txt(f"default._bimi.{domain}"), resolver.txt(f"_dmarc.{domain}"))
    record = parse_record(bimi_txt)
    ready, why = dmarc_enforces(dmarc_txt)
    problems: list[str] = []
    if not ready:
        problems.append(why)
    if record is None:
        return Bimi(
            domain=domain, published=False, logo_url=None, certificate_url=None, dmarc_ready=ready, certificate=None, problems=problems
        )
    if not record.logo or not record.logo.lower().startswith("https://"):
        problems.append("The record has no https logo address (l=).")
    cert: CertInfo | None = None
    if not record.authority:
        problems.append(
            "The record names no certificate (a=): most mail clients will not show the logo without a Verified Mark Certificate."
        )
    else:
        try:
            cert = read_certificate(await fetch(record.authority), now)
        except FetchRefused as e:
            problems.append(str(e))
        except ValueError as e:
            problems.append(str(e))
        if cert is not None:
            if not cert.valid:
                problems.append(f"The certificate is not valid now (it ended {cert.not_after.date()}). The logo will not show.")
            elif cert.days_left <= EXPIRY_WARNING_DAYS:
                problems.append(
                    f"The certificate expires in {cert.days_left} days ({cert.not_after.date()}). When it lapses the logo disappears without warning."
                )
            if not cert.is_vmc:
                problems.append("This is not a Verified Mark Certificate (it has no logotype extension).")
    return Bimi(
        domain=domain,
        published=True,
        logo_url=record.logo,
        certificate_url=record.authority,
        dmarc_ready=ready,
        certificate=cert,
        problems=problems,
    )

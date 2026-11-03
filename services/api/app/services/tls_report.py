"""Reading a TLS-RPT report (RFC 8460): the daily JSON a receiving mail server sends about how many TLS-protected connections to a domain's mail servers succeeded or failed, and why.

It arrives like a DMARC report (gzip or zip, in the same mailbox) but is JSON. Nothing in it is trusted: sizes and counts are capped, names are clipped, domains must look like domains.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.services.dmarc_report import DmarcReportError

MAX_POLICIES = 50
MAX_FAILURE_KINDS = 50
_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


@dataclass(frozen=True)
class TlsPolicy:
    domain: str
    policy_type: str  # sts, tlsa, no-policy-found
    success: int
    failure: int
    failures: list[tuple[str, int]] = field(default_factory=list)  # (what went wrong, how many sessions)


@dataclass(frozen=True)
class TlsReport:
    reporter: str
    report_id: str
    begin: datetime
    end: datetime
    policies: list[TlsPolicy]


def looks_like_tls_report(unpacked: bytes) -> bool:
    return unpacked.lstrip()[:1] == b"{"


def _clip(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2_000_000_000 else 0


def _when(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise DmarcReportError("The TLS report has no usable date range.") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_tls_report(unpacked: bytes) -> TlsReport:
    try:
        data = json.loads(unpacked)
    except ValueError:
        raise DmarcReportError("The TLS report is not valid JSON.") from None
    if not isinstance(data, dict) or not isinstance(data.get("policies"), list) or not isinstance(data.get("date-range"), dict):
        raise DmarcReportError("This is not a TLS report.")
    rng = data["date-range"]
    begin, end = _when(rng.get("start-datetime")), _when(rng.get("end-datetime"))
    report_id = _clip(data.get("report-id"), 255)
    if not report_id:
        raise DmarcReportError("The TLS report has no report id.")
    policies: list[TlsPolicy] = []
    for item in data["policies"][:MAX_POLICIES]:
        if not isinstance(item, dict) or not isinstance(item.get("policy"), dict) or not isinstance(item.get("summary"), dict):
            continue
        domain = _clip(item["policy"].get("policy-domain"), 255).lower().rstrip(".")
        if not _DOMAIN.match(domain):
            continue
        summary = item["summary"]
        failures = [
            (_clip(d.get("result-type"), 60), _count(d.get("failed-session-count")))
            for d in (item.get("failure-details") or [])[:MAX_FAILURE_KINDS]
            if isinstance(d, dict) and _clip(d.get("result-type"), 60)
        ]
        policies.append(
            TlsPolicy(domain, _clip(item["policy"].get("policy-type"), 30).lower() or "unknown", _count(summary.get("total-successful-session-count")), _count(summary.get("total-failure-session-count")), failures)
        )
    if not policies:
        raise DmarcReportError("The TLS report names no usable domain.")
    return TlsReport(_clip(data.get("organization-name"), 200), report_id, begin, end, policies)

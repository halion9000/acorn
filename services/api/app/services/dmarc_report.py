"""Reading a DMARC aggregate report (RFC 7489, the daily XML a mail receiver sends about mail claiming to be from a domain).

Reports arrive as an attachment: plain XML, gzip (Microsoft, Yahoo) or zip (Google). They come from the internet, so the input is treated as hostile:
* the decompressed size is capped, so a few kilobytes of zip cannot expand into gigabytes,
* a zip must hold exactly one file; its name is never used as a path,
* an XML with a DOCTYPE or ENTITY declaration is refused (a real report has neither),
* the number of records is capped and every text field is cut short.
A report that cannot be read raises ``DmarcReportError`` with a plain reason; the caller keeps the message for a person to look at and does not retry it forever.
"""

from __future__ import annotations

import gzip
import io
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from xml.etree import ElementTree as ET

MAX_COMPRESSED = 5 * 1024 * 1024
MAX_XML_BYTES = 20 * 1024 * 1024
MAX_RECORDS = 20_000


class DmarcReportError(ValueError):
    pass


@dataclass
class Record:
    source_ip: str
    count: int
    disposition: str  # none | quarantine | reject
    dkim_aligned: bool  # the DKIM result in the receiver's DMARC evaluation
    spf_aligned: bool
    header_from: str
    envelope_from: str
    dkim_domains: list[str] = field(default_factory=list)
    spf_domains: list[str] = field(default_factory=list)
    # Why the receiver overrode the published policy, when it did (forwarded, mailing_list, local_policy, sampled_out, trusted_forwarder, other), comma separated; empty when it did not.
    reason: str = ""

    @property
    def dmarc_pass(self) -> bool:
        """DMARC passes when either SPF or DKIM passes AND aligns with the From domain (the receiver's policy_evaluated says exactly that)."""
        return self.dkim_aligned or self.spf_aligned


@dataclass
class DmarcReport:
    reporter: str
    reporter_email: str
    report_id: str
    domain: str  # the domain the report is about (policy_published)
    begin: datetime
    end: datetime
    policy: str  # p= as the receiver saw it
    records: list[Record]

    @property
    def total(self) -> int:
        return sum(r.count for r in self.records)

    @property
    def passed(self) -> int:
        return sum(r.count for r in self.records if r.dmarc_pass)

    @property
    def failed(self) -> int:
        return self.total - self.passed


def _clip(value: str | None, limit: int) -> str:
    return (value or "").strip()[:limit]


def _int(value: str | None) -> int:
    try:
        return max(0, int(value)) if value else 0
    except ValueError:
        return 0


def _when(value: str | None) -> datetime:
    try:
        return datetime.fromtimestamp(int(value or ""), tz=UTC)
    except (ValueError, OverflowError, OSError):
        raise DmarcReportError("The report has no usable date range.") from None


def unpack(data: bytes) -> bytes:
    """The XML inside an attachment of any of the three kinds, with the size limits applied."""
    if len(data) > MAX_COMPRESSED:
        raise DmarcReportError("The attachment is larger than 5 MB.")
    if data[:2] == b"\x1f\x8b":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                out = gz.read(MAX_XML_BYTES + 1)
        except (OSError, EOFError):
            raise DmarcReportError("The gzip attachment is damaged.") from None
    elif data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                infos = [i for i in zf.infolist() if not i.is_dir()]
                if len(infos) != 1:
                    raise DmarcReportError("The zip attachment must hold exactly one file.")
                if infos[0].file_size > MAX_XML_BYTES:
                    raise DmarcReportError("The report inside the zip is larger than 20 MB.")
                with zf.open(infos[0]) as fh:
                    out = fh.read(MAX_XML_BYTES + 1)
        except zipfile.BadZipFile:
            raise DmarcReportError("The zip attachment is damaged.") from None
    else:
        out = data
    if len(out) > MAX_XML_BYTES:
        raise DmarcReportError("The report is larger than 20 MB once unpacked.")
    return out


def parse_report(attachment: bytes) -> DmarcReport:
    xml = unpack(attachment)
    low = xml[:500_000].lower()
    if b"<!doctype" in low or b"<!entity" in low:
        raise DmarcReportError("This is not a DMARC report: it contains a DOCTYPE or ENTITY declaration, which a real report never does.")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise DmarcReportError(f"The report is not valid XML ({exc}).") from None
    if root.tag != "feedback":
        raise DmarcReportError("This is not a DMARC aggregate report (no <feedback> element).")

    meta = root.find("report_metadata")
    pub = root.find("policy_published")
    if meta is None or pub is None:
        raise DmarcReportError("The report is missing its metadata or published policy.")
    domain = _clip(pub.findtext("domain"), 255).lower().rstrip(".")
    if not domain:
        raise DmarcReportError("The report does not say which domain it is about.")
    rng = meta.find("date_range")
    if rng is None:
        raise DmarcReportError("The report has no usable date range.")

    records: list[Record] = []
    for rec in root.findall("record"):
        if len(records) >= MAX_RECORDS:
            raise DmarcReportError(f"The report has more than {MAX_RECORDS:,} rows.")
        row = rec.find("row")
        if row is None:
            continue
        evaluated = row.find("policy_evaluated")
        ident = rec.find("identifiers")
        auth = rec.find("auth_results")
        records.append(
            Record(
                source_ip=_clip(row.findtext("source_ip"), 64),
                count=_int(row.findtext("count")),
                disposition=_clip(evaluated.findtext("disposition") if evaluated is not None else None, 20).lower() or "none",
                dkim_aligned=(evaluated.findtext("dkim") if evaluated is not None else "") == "pass",
                spf_aligned=(evaluated.findtext("spf") if evaluated is not None else "") == "pass",
                header_from=_clip(ident.findtext("header_from") if ident is not None else None, 255).lower(),
                envelope_from=_clip(ident.findtext("envelope_from") if ident is not None else None, 255).lower(),
                dkim_domains=[
                    d for d in (_clip(x.findtext("domain"), 255).lower() for x in (auth.findall("dkim") if auth is not None else [])) if d
                ][:10],
                spf_domains=[
                    d for d in (_clip(x.findtext("domain"), 255).lower() for x in (auth.findall("spf") if auth is not None else [])) if d
                ][:10],
                reason=",".join(
                    t
                    for t in (_clip(x.findtext("type"), 30).lower() for x in (evaluated.findall("reason") if evaluated is not None else []))
                    if t
                )[:120],
            )
        )
    return DmarcReport(
        reporter=_clip(meta.findtext("org_name"), 200),
        reporter_email=_clip(meta.findtext("email"), 255),
        report_id=_clip(meta.findtext("report_id"), 255),
        domain=domain,
        begin=_when(rng.findtext("begin")),
        end=_when(rng.findtext("end")),
        policy=_clip(pub.findtext("p"), 20).lower() or "none",
        records=records,
    )

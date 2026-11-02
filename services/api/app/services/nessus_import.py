"""Reading a Tenable Nessus export (.nessus, the v2 XML format) into hosts and findings.

The file comes from a person's upload, so it is treated as hostile input:
* a file with a DOCTYPE or an ENTITY declaration is refused outright (a real Nessus export has neither; they are how "billion laughs" and external-entity attacks are written),
* the file is read as a stream, one report item at a time, so a 100 MB export is not held in memory as a tree,
* the size, the number of hosts and the number of findings are capped,
* every text field is cut to a sane length.
Informational findings (severity 0) are left out: they are the scanner describing the host, not a problem.
"""

from __future__ import annotations

import io
import ipaddress
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

MAX_BYTES = 100 * 1024 * 1024
MAX_HOSTS = 5000
MAX_FINDINGS = 200_000

SEVERITY_NAMES = {1: "low", 2: "medium", 3: "high", 4: "critical"}


class NessusFileError(ValueError):
    """The file cannot be used; the message says why in words a person can act on."""


@dataclass
class Finding:
    plugin_id: str
    name: str
    severity: int  # 1 low .. 4 critical
    port: int
    protocol: str
    service: str
    cvss: float | None
    cves: list[str]
    exploit_available: bool
    synopsis: str
    solution: str


@dataclass
class Host:
    name: str
    ip: str | None
    fqdn: str | None
    os: str | None
    findings: list[Finding] = field(default_factory=list)


@dataclass
class ParsedScan:
    report_name: str
    hosts: list[Host]
    scan_type: str  # lan | wan | other

    @property
    def finding_count(self) -> int:
        return sum(len(h.findings) for h in self.hosts)


def _clip(value: str | None, limit: int) -> str:
    return (value or "").strip()[:limit]


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _int(value: str | None, default: int = 0) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def detect_scan_type(hosts: list[Host]) -> str:
    """lan when every host with an address is private, wan when every one is public, otherwise other (mixed, or no addresses to judge by)."""
    kinds: set[str] = set()
    for h in hosts:
        try:
            addr = ipaddress.ip_address(h.ip or h.name)
        except ValueError:
            continue
        kinds.add("lan" if (addr.is_private or addr.is_loopback or addr.is_link_local) else "wan")
    return kinds.pop() if len(kinds) == 1 else "other"


def parse_nessus(data: bytes) -> ParsedScan:
    if len(data) > MAX_BYTES:
        raise NessusFileError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    head = data[:4096].lower()
    if b"<!doctype" in data[:200_000].lower() or b"<!entity" in data[:200_000].lower():
        raise NessusFileError("This does not look like a Nessus export: it contains a DOCTYPE or ENTITY declaration, which a real export never does.")
    if b"nessusclientdata_v2" not in head and b"nessusclientdata_v2" not in data[:200_000].lower():
        raise NessusFileError("This is not a Nessus v2 export (.nessus). Export the scan from Nessus as 'Nessus' format.")

    hosts: list[Host] = []
    report_name = ""
    current: Host | None = None
    finding_total = 0
    try:
        for event, el in ET.iterparse(io.BytesIO(data), events=("start", "end")):
            tag = el.tag
            if event == "start":
                if tag == "Report":
                    report_name = _clip(el.get("name"), 200)
                elif tag == "ReportHost":
                    if len(hosts) >= MAX_HOSTS:
                        raise NessusFileError(f"The file has more than {MAX_HOSTS} hosts.")
                    current = Host(name=_clip(el.get("name"), 255), ip=None, fqdn=None, os=None)
                continue
            # end events
            if tag == "tag" and current is not None:
                key = el.get("name")
                text = _clip(el.text, 255)
                if key == "host-ip" and text:
                    current.ip = text
                elif key == "host-fqdn" and text:
                    current.fqdn = text
                elif key == "operating-system" and text:
                    current.os = text.splitlines()[0][:255]
                el.clear()
            elif tag == "ReportItem" and current is not None:
                severity = _int(el.get("severity"))
                if severity >= 1:
                    finding_total += 1
                    if finding_total > MAX_FINDINGS:
                        raise NessusFileError(f"The file has more than {MAX_FINDINGS:,} findings.")
                    cvss = _float(el.findtext("cvss3_base_score")) or _float(el.findtext("cvss_base_score"))
                    current.findings.append(
                        Finding(
                            plugin_id=_clip(el.get("pluginID"), 40),
                            name=_clip(el.get("pluginName"), 300),
                            severity=min(severity, 4),
                            port=_int(el.get("port")),
                            protocol=_clip(el.get("protocol"), 10),
                            service=_clip(el.get("svc_name"), 60),
                            cvss=cvss,
                            cves=[c for c in (_clip(x.text, 40) for x in el.findall("cve")) if c][:50],
                            exploit_available=(el.findtext("exploit_available") or "").strip().lower() == "true",
                            synopsis=_clip(el.findtext("synopsis"), 500),
                            solution=_clip(el.findtext("solution"), 1000),
                        )
                    )
                el.clear()
            elif tag == "ReportHost" and current is not None:
                hosts.append(current)
                current = None
                el.clear()
    except ET.ParseError as exc:
        raise NessusFileError(f"The file is not valid XML ({exc}).") from None
    if not hosts:
        raise NessusFileError("The file has no hosts in it.")
    return ParsedScan(report_name=report_name, hosts=hosts, scan_type=detect_scan_type(hosts))

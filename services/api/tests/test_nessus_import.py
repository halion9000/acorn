"""Reading a .nessus export: what it keeps, what it leaves out, and that hostile files are refused."""

import pytest
from app.services import nessus_import as ni
from app.services.nessus_import import NessusFileError, parse_nessus


def item(plugin, name, severity, port=443, cves=(), exploit="false", cvss="7.5", svc="www"):
    cve_xml = "".join(f"<cve>{c}</cve>" for c in cves)
    return (
        f'<ReportItem port="{port}" svc_name="{svc}" protocol="tcp" severity="{severity}" pluginID="{plugin}" pluginName="{name}">'
        f"<synopsis>Synopsis {plugin}</synopsis><solution>Fix {plugin}</solution><cvss3_base_score>{cvss}</cvss3_base_score>{cve_xml}"
        f"<exploit_available>{exploit}</exploit_available></ReportItem>"
    )


def host(name, items, ip=None, os="Windows 11\nline two"):
    ip = ip or name
    return (
        f'<ReportHost name="{name}"><HostProperties><tag name="host-ip">{ip}</tag><tag name="host-fqdn">{name}.example.test</tag>'
        f'<tag name="operating-system">{os}</tag></HostProperties>{"".join(items)}</ReportHost>'
    )


def doc(*hosts, report="Monthly scan"):
    return f'<?xml version="1.0"?><NessusClientData_v2><Policy/><Report name="{report}">{"".join(hosts)}</Report></NessusClientData_v2>'.encode()


def test_it_reads_hosts_findings_and_the_fields_a_report_needs():
    scan = parse_nessus(doc(host("10.0.0.5", [item("1001", "SMB signing off", 2), item("1002", "Old TLS", 3, cves=["CVE-2020-1", "CVE-2020-2"], exploit="true", cvss="9.8")])))
    assert scan.report_name == "Monthly scan" and len(scan.hosts) == 1
    h = scan.hosts[0]
    assert (h.name, h.ip, h.fqdn, h.os) == ("10.0.0.5", "10.0.0.5", "10.0.0.5.example.test", "Windows 11")
    second = h.findings[1]
    assert (second.plugin_id, second.severity, second.cvss, second.cves, second.exploit_available, second.solution) == ("1002", 3, 9.8, ["CVE-2020-1", "CVE-2020-2"], True, "Fix 1002")
    assert scan.finding_count == 2


def test_informational_findings_are_left_out_and_critical_is_the_top_severity():
    scan = parse_nessus(doc(host("10.0.0.5", [item("1", "Info", 0), item("2", "Low", 1), item("3", "Crit", 4), item("4", "Beyond", 9)])))
    assert [f.severity for f in scan.hosts[0].findings] == [1, 4, 4]


def test_the_scan_type_is_judged_from_the_addresses():
    assert parse_nessus(doc(host("10.0.0.5", [item("1", "x", 2)]), host("192.168.1.9", [item("1", "x", 2)]))).scan_type == "lan"
    assert parse_nessus(doc(host("8.8.8.8", [item("1", "x", 2)]), host("1.1.1.1", [item("1", "x", 2)]))).scan_type == "wan"
    assert parse_nessus(doc(host("10.0.0.5", [item("1", "x", 2)]), host("8.8.8.8", [item("1", "x", 2)]))).scan_type == "other"
    assert parse_nessus(doc(host("server-a", [item("1", "x", 2)], ip="not-an-ip"))).scan_type == "other"


@pytest.mark.parametrize(
    "bad",
    [
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><NessusClientData_v2><Report name="r"><ReportHost name="h"/></Report></NessusClientData_v2>',
        b'<?xml version="1.0"?><!doctype lolz><NessusClientData_v2/>',
        b'<NessusClientData_v2><!ENTITY x SYSTEM "file:///etc/passwd"></NessusClientData_v2>',
    ],
)
def test_a_file_with_a_doctype_or_entity_is_refused(bad):
    with pytest.raises(NessusFileError, match="DOCTYPE or ENTITY"):
        parse_nessus(bad)


def test_other_files_are_refused_with_a_reason():
    with pytest.raises(NessusFileError, match="not a Nessus v2"):
        parse_nessus(b"<html><body>hello</body></html>")
    with pytest.raises(NessusFileError, match="not valid XML"):
        parse_nessus(b"<NessusClientData_v2><Report name='r'><ReportHost name='h'></Report>")
    with pytest.raises(NessusFileError, match="no hosts"):
        parse_nessus(b'<NessusClientData_v2><Report name="r"></Report></NessusClientData_v2>')


def test_the_limits_are_enforced(monkeypatch):
    monkeypatch.setattr(ni, "MAX_BYTES", 100)
    with pytest.raises(NessusFileError, match="larger than"):
        parse_nessus(doc(host("10.0.0.5", [item("1", "x", 2)])))
    monkeypatch.setattr(ni, "MAX_BYTES", 10_000_000)
    monkeypatch.setattr(ni, "MAX_HOSTS", 1)
    with pytest.raises(NessusFileError, match="more than 1 hosts"):
        parse_nessus(doc(host("10.0.0.5", [item("1", "x", 2)]), host("10.0.0.6", [item("1", "x", 2)])))
    monkeypatch.setattr(ni, "MAX_HOSTS", 5000)
    monkeypatch.setattr(ni, "MAX_FINDINGS", 1)
    with pytest.raises(NessusFileError, match="more than 1 findings"):
        parse_nessus(doc(host("10.0.0.5", [item("1", "x", 2), item("2", "y", 2)])))


def test_long_text_is_cut_not_stored_whole():
    scan = parse_nessus(doc(host("10.0.0.5", [item("1", "N" * 5000, 2)])))
    assert len(scan.hosts[0].findings[0].name) == 300

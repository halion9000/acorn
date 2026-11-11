"""Reading a DMARC aggregate report: the figures, the three attachment kinds, and refusing hostile files."""

import gzip
import io
import zipfile
from datetime import UTC, datetime

import pytest
from app.services import dmarc_report as dr
from app.services.dmarc_report import DmarcReportError, parse_report

BEGIN, END = 1_762_041_600, 1_762_128_000  # 2025-11-02 00:00 and 2025-11-03 00:00 UTC


def record(ip, count, dkim="pass", spf="pass", disp="none", header_from="client.com"):
    return (
        f"<record><row><source_ip>{ip}</source_ip><count>{count}</count><policy_evaluated><disposition>{disp}</disposition><dkim>{dkim}</dkim><spf>{spf}</spf></policy_evaluated></row>"
        f"<identifiers><header_from>{header_from}</header_from><envelope_from>client.com</envelope_from></identifiers>"
        f"<auth_results><dkim><domain>client.com</domain><result>{dkim}</result></dkim><spf><domain>client.com</domain><result>{spf}</result></spf></auth_results></record>"
    )


def report(*records, domain="Client.COM.", policy="none"):
    return (
        '<?xml version="1.0"?><feedback><report_metadata><org_name>google.com</org_name><email>noreply-dmarc@google.com</email><report_id>123</report_id>'
        f"<date_range><begin>{BEGIN}</begin><end>{END}</end></date_range></report_metadata>"
        f"<policy_published><domain>{domain}</domain><p>{policy}</p></policy_published>{''.join(records)}</feedback>"
    ).encode()


def test_it_reads_the_report_and_counts_pass_and_fail():
    r = parse_report(
        report(
            record("1.2.3.4", 40),
            record("5.6.7.8", 6, dkim="fail", spf="pass"),
            record("9.9.9.9", 4, dkim="fail", spf="fail", disp="quarantine"),
        )
    )
    assert (r.reporter, r.reporter_email, r.report_id, r.domain, r.policy) == (
        "google.com",
        "noreply-dmarc@google.com",
        "123",
        "client.com",
        "none",
    )
    assert r.begin == datetime(2025, 11, 2, tzinfo=UTC) and r.end == datetime(2025, 11, 3, tzinfo=UTC)
    assert (r.total, r.passed, r.failed) == (50, 46, 4)
    bad = r.records[2]
    assert (bad.source_ip, bad.count, bad.disposition, bad.dmarc_pass) == ("9.9.9.9", 4, "quarantine", False)
    assert r.records[0].dkim_domains == ["client.com"] and r.records[0].header_from == "client.com"


def test_either_spf_or_dkim_passing_is_a_dmarc_pass():
    r = parse_report(report(record("1.1.1.1", 1, dkim="pass", spf="fail"), record("2.2.2.2", 1, dkim="fail", spf="pass")))
    assert all(x.dmarc_pass for x in r.records)


def test_gzip_and_zip_attachments_are_unpacked_like_plain_xml():
    xml = report(record("1.2.3.4", 3))
    assert parse_report(gzip.compress(xml)).total == 3
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("google.com!client.com!1!2.xml", xml)
    assert parse_report(buf.getvalue()).total == 3


def test_a_zip_with_two_files_or_a_bomb_is_refused(monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.xml", report(record("1.2.3.4", 1)))
        zf.writestr("b.xml", report(record("1.2.3.4", 1)))
    with pytest.raises(DmarcReportError, match="exactly one file"):
        parse_report(buf.getvalue())
    monkeypatch.setattr(dr, "MAX_XML_BYTES", 1000)
    with pytest.raises(DmarcReportError, match="larger than 20 MB"):
        parse_report(gzip.compress(b"<feedback>" + b"a" * 5000 + b"</feedback>"))
    monkeypatch.setattr(dr, "MAX_COMPRESSED", 10)
    with pytest.raises(DmarcReportError, match="larger than 5 MB"):
        parse_report(b"x" * 11)


@pytest.mark.parametrize(
    "bad", [b'<!DOCTYPE feedback [<!ENTITY a "aaaa">]><feedback/>', b"<feedback><!ENTITY x SYSTEM 'file:///etc/passwd'></feedback>"]
)
def test_a_doctype_or_entity_is_refused(bad):
    with pytest.raises(DmarcReportError, match="DOCTYPE or ENTITY"):
        parse_report(bad)


def test_broken_and_foreign_files_are_refused_with_a_reason():
    with pytest.raises(DmarcReportError, match="not valid XML"):
        parse_report(b"<feedback><report_metadata>")
    with pytest.raises(DmarcReportError, match="not a DMARC aggregate report"):
        parse_report(b"<html/>")
    with pytest.raises(DmarcReportError, match="damaged"):
        parse_report(b"\x1f\x8bnot really gzip")
    with pytest.raises(DmarcReportError, match="missing its metadata"):
        parse_report(b"<feedback/>")
    with pytest.raises(DmarcReportError, match="which domain"):
        parse_report(report(domain=" "))


def test_the_row_limit_is_enforced_and_long_text_is_cut(monkeypatch):
    monkeypatch.setattr(dr, "MAX_RECORDS", 1)
    with pytest.raises(DmarcReportError, match="more than 1 rows"):
        parse_report(report(record("1.1.1.1", 1), record("2.2.2.2", 1)))
    monkeypatch.setattr(dr, "MAX_RECORDS", 100)
    assert len(parse_report(report(record("x" * 500, 1))).records[0].source_ip) == 64


def test_the_receivers_override_reason_is_kept_per_source_line():
    xml = (
        '<?xml version="1.0"?><feedback><report_metadata><org_name>g</org_name><email>n@g.com</email><report_id>1</report_id>'
        f"<date_range><begin>{BEGIN}</begin><end>{END}</end></date_range></report_metadata><policy_published><domain>client.com</domain><p>reject</p></policy_published>"
        "<record><row><source_ip>1.2.3.4</source_ip><count>3</count><policy_evaluated><disposition>none</disposition><dkim>fail</dkim><spf>fail</spf>"
        "<reason><type>forwarded</type><comment>sent by a forwarder</comment></reason><reason><type>mailing_list</type></reason></policy_evaluated></row><identifiers><header_from>client.com</header_from></identifiers></record>"
        "<record><row><source_ip>5.6.7.8</source_ip><count>9</count><policy_evaluated><disposition>none</disposition><dkim>pass</dkim><spf>pass</spf></policy_evaluated></row><identifiers><header_from>client.com</header_from></identifiers></record>"
        "</feedback>"
    ).encode()
    r = parse_report(xml)
    assert r.records[0].reason == "forwarded,mailing_list"
    assert r.records[1].reason == ""  # no override: no reason

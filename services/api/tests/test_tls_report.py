"""Reading a TLS-RPT report: the counts and failure kinds per policy, and refusing anything that is not one."""

import gzip
import json
from datetime import UTC, datetime

import pytest
from app.services.dmarc_report import DmarcReportError, unpack
from app.services.tls_report import looks_like_tls_report, parse_tls_report


def doc(**over):
    base = {
        "organization-name": "Google Inc.",
        "date-range": {"start-datetime": "2026-11-01T00:00:00Z", "end-datetime": "2026-11-01T23:59:59Z"},
        "contact-info": "smtp-tls-reporting@google.com",
        "report-id": "2026-11-01T00:00:00Z_client.com",
        "policies": [
            {
                "policy": {"policy-type": "sts", "policy-domain": "Client.COM."},
                "summary": {"total-successful-session-count": 120, "total-failure-session-count": 5},
                "failure-details": [
                    {"result-type": "certificate-expired", "failed-session-count": 3},
                    {"result-type": "starttls-not-supported", "failed-session-count": 2},
                ],
            }
        ],
    }
    base.update(over)
    return json.dumps(base).encode()


def test_it_reads_the_counts_and_failure_kinds_per_policy():
    r = parse_tls_report(doc())
    assert (r.reporter, r.report_id) == ("Google Inc.", "2026-11-01T00:00:00Z_client.com")
    assert r.begin == datetime(2026, 11, 1, tzinfo=UTC) and r.end.hour == 23
    p = r.policies[0]
    assert (p.domain, p.policy_type, p.success, p.failure) == ("client.com", "sts", 120, 5)
    assert p.failures == [("certificate-expired", 3), ("starttls-not-supported", 2)]


def test_a_gzip_attachment_is_unpacked_and_recognised_as_a_tls_report_not_a_dmarc_one():
    data = unpack(gzip.compress(doc()))
    assert looks_like_tls_report(data) and parse_tls_report(data).policies
    assert not looks_like_tls_report(b"<?xml version='1.0'?><feedback/>") and not looks_like_tls_report(b"   <feedback/>")


@pytest.mark.parametrize("bad", [b"{not json", b"[]", b"{}", json.dumps({"policies": [], "date-range": {}}).encode()])
def test_anything_that_is_not_a_tls_report_is_refused_with_a_reason(bad):
    with pytest.raises(DmarcReportError):
        parse_tls_report(bad)


def test_a_missing_report_id_or_date_or_usable_domain_is_refused():
    with pytest.raises(DmarcReportError, match="report id"):
        parse_tls_report(doc(**{"report-id": " "}))
    with pytest.raises(DmarcReportError, match="date range"):
        parse_tls_report(doc(**{"date-range": {"start-datetime": "yesterday", "end-datetime": "today"}}))
    bad_domain = [{"policy": {"policy-type": "sts", "policy-domain": "not a domain"}, "summary": {}}]
    with pytest.raises(DmarcReportError, match="no usable domain"):
        parse_tls_report(doc(policies=bad_domain))


def test_counts_are_capped_and_garbage_counts_read_as_zero_and_a_bad_policy_does_not_hide_a_good_one():
    policies = [
        "not a dict",
        {
            "policy": {"policy-type": "tlsa", "policy-domain": "client.com"},
            "summary": {"total-successful-session-count": -4, "total-failure-session-count": "9"},
            "failure-details": [{"result-type": "x" * 200, "failed-session-count": 10**12}, {"failed-session-count": 3}],
        },
    ]
    p = parse_tls_report(doc(policies=policies)).policies
    assert len(p) == 1 and (p[0].success, p[0].failure) == (0, 0)
    assert p[0].failures == [("x" * 60, 0)]  # the kind is clipped, an absurd count is dropped, a kind with no name is skipped


def test_the_number_of_policies_is_limited():
    many = [
        {"policy": {"policy-type": "sts", "policy-domain": f"d{i}.example.com"}, "summary": {"total-successful-session-count": 1}}
        for i in range(80)
    ]
    assert len(parse_tls_report(doc(policies=many)).policies) == 50

"""Naming the service that sent mail from the domains it authenticated with."""

import pytest
from app.services.dmarc_senders import KNOWN_SENDERS, identify_sender


@pytest.mark.parametrize(
    "spf,dkim,expected",
    [
        (["spf.protection.outlook.com"], [], "Microsoft 365"),
        (["client.com"], ["client.onmicrosoft.com"], "Microsoft 365"),
        ([], ["s1._domainkey.sendgrid.net"], "SendGrid"),
        (["mail.hubspotemail.net"], ["client.com"], "HubSpot"),
        (["_spf.google.com"], [], "Google Workspace"),
        (["bounce.mcsv.net"], [], "Mailchimp"),
    ],
)
def test_a_known_service_is_named_from_its_spf_or_dkim_domain(spf, dkim, expected):
    assert identify_sender(spf, dkim) == expected


def test_a_domain_only_matches_itself_or_its_own_subdomains_not_a_lookalike():
    assert identify_sender(["sendgrid.net"], []) == "SendGrid"
    assert identify_sender(["em.sendgrid.net"], []) == "SendGrid"
    assert identify_sender(["notsendgrid.net"], []) is None
    assert identify_sender(["sendgrid.net.evil.example"], []) is None


def test_the_spf_domain_is_tried_before_the_dkim_one_and_case_and_a_trailing_dot_do_not_matter():
    assert identify_sender(["Bounce.SendGrid.NET."], ["client.hubspot.com"]) == "SendGrid"


def test_what_is_not_on_the_list_is_not_guessed():
    assert identify_sender(["client.com"], ["client.com"]) is None
    assert identify_sender([], []) is None
    assert identify_sender([""], [""]) is None


def test_the_list_has_no_duplicate_domains_pointing_at_different_names():
    seen: dict[str, str] = {}
    for domain, name in KNOWN_SENDERS:
        assert seen.setdefault(domain, name) == name, domain


# ---- more on the unknowns ---------------------------------------------------------------------------------------------------------------------------------


def test_a_sender_with_no_known_domain_is_still_named_from_a_well_known_address_range():
    from app.services.dmarc_senders import identify_by_address

    assert identify_by_address("2a01:111:f403:c112::5") == "Microsoft 365 mail servers"
    assert identify_by_address("209.85.220.69") == "Google mail servers"
    assert identify_by_address("2607:f8b0:4864:20::b147") == "Google mail servers"
    assert identify_by_address("203.0.113.9") is None
    assert identify_by_address("not an address") is None
    assert identify_by_address("") is None


def failing(**over):
    base = {
        "pass": False,
        "spf": False,
        "dkim": False,
        "header_from": "acme.com",
        "spf_domains": [],
        "dkim_domains": [],
        "spf_results": [],
        "dkim_results": [],
    }
    return {**base, **over}


def test_failures_are_explained_by_what_the_receiver_found_for_spf_and_for_dkim():
    from app.services.dmarc_senders import failure_causes

    assert failure_causes({"pass": True}) == []
    assert failure_causes(failing()) == ["no SPF result", "no DKIM signature"]
    out = failure_causes(
        failing(spf_domains=["bounce.sender.net"], spf_results=["softfail"], dkim_domains=["sender.net"], dkim_results=["pass"])
    )
    assert out == ["SPF softfail for bounce.sender.net", "DKIM passed for sender.net, not for acme.com (not aligned)"]
    assert failure_causes(failing(spf=True, dkim_domains=["x.com"], dkim_results=["fail"])) == ["DKIM fail for x.com"]
    assert failure_causes(failing(dkim=True, spf_domains=["x.com"], spf_results=["pass"])) == [
        "SPF passed for x.com, not for acme.com (not aligned)"
    ]


def test_sender_stats_count_what_failed_how_and_where_it_claimed_to_be_from():
    from app.services.dmarc_senders import SenderStats

    s = SenderStats()
    s.add(
        failing(
            ip="1.2.3.4",
            spf_domains=["a.net"],
            spf_results=["fail"],
            dkim=True,
            spf=False,
            envelope_from="a.net",
            disposition="quarantine",
            reason="forwarded",
        ),
        5,
        "acme.com",
    )
    s.add(failing(ip="1.2.3.4", dkim_domains=["a.net"], dkim_results=["fail"], spf=True, dkim=False), 3, "acme.com")
    s.add(failing(ip="1.2.3.4"), 2, "acme.com")
    s.add({"pass": True, "spf": True, "dkim": True, "ip": "1.2.3.4", "header_from": "acme.com", "disposition": "none"}, 90, "acme.com")
    d = s.detail()
    assert (d["spf_only_failed"], d["dkim_only_failed"], d["both_failed"]) == (5, 3, 2)
    assert {"text": "no SPF result", "count": 2} in d["causes"] and {"text": "SPF fail for a.net", "count": 5} in d["causes"]
    assert d["dispositions"] == {"quarantine": 5, "none": 95}
    assert d["reasons"] == ["forwarded"] and d["addresses"] == ["1.2.3.4"] and d["header_from"] == ["acme.com"]


def test_who_owns_an_address_comes_from_the_registry_record_and_nothing_else_is_trusted():
    import json

    from app.services.dmarc_senders import parse_ip_rdap

    vcard = {"entities": [{"vcardArray": ["vcard", [["version", {}, "text", "4.0"], ["fn", {}, "text", "Google LLC"]]]}], "name": "GOOGLE"}
    assert parse_ip_rdap(json.dumps(vcard).encode()) == "Google LLC"
    assert parse_ip_rdap(json.dumps({"name": "NET-1"}).encode()) == "NET-1"
    assert parse_ip_rdap(b"not json") is None
    assert parse_ip_rdap(b"[]") is None
    assert parse_ip_rdap(json.dumps({"name": ""}).encode()) is None

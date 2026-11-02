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

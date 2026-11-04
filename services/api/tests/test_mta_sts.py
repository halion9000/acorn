"""MTA-STS: the record, the policy file, whether its server list still covers the real MX records, and the advice that follows. No network: DNS and the file come from stand-ins."""

import asyncio

from app.services import mta_sts, safe_fetch

POLICY = "version: STSv1\nmode: enforce\nmx: mail.acme.com\nmx: *.mail.protection.outlook.com\nmax_age: 604800\n"


class Dns:
    def __init__(self, txt=None, mx=None, broken=False):
        self._txt, self._mx, self.broken = txt or {}, mx or [], broken

    async def txt(self, name):
        if self.broken:
            raise RuntimeError("down")
        return self._txt.get(name, [])

    async def mx(self, name):
        return self._mx

    async def cname(self, name):
        return []

    async def a(self, name):
        return []


def run(txt=None, mx=None, policy=POLICY, refuse=None, broken=False):
    asked = []

    async def fetch(url):
        asked.append(url)
        if refuse:
            raise safe_fetch.FetchRefused(refuse)
        return policy.encode()

    dns = Dns(
        {"_mta-sts.acme.com": ["v=STSv1; id=20260101"]} if txt is None else txt, mx or ["10 acme-com.mail.protection.outlook.com."], broken
    )
    return asyncio.run(mta_sts.check("acme.com", dns, fetch)), asked


def test_a_good_enforced_policy_that_covers_the_real_mail_servers_has_nothing_to_fix():
    r, asked = run()
    assert (r.state, r.mode, r.max_age, r.record_id) == ("ok", "enforce", 604800, "20260101")
    assert r.uncovered_mx == [] and r.issues == []
    assert asked == ["https://mta-sts.acme.com/.well-known/mta-sts.txt"]
    assert mta_sts.advice(r, True) == []


def test_an_enforced_policy_that_misses_a_real_mail_server_is_the_urgent_finding():
    r, _ = run(mx=["10 mail.acme.com.", "20 backup.acme.net."])
    assert r.uncovered_mx == ["backup.acme.net"]
    text = " ".join(mta_sts.advice(r, True))
    assert "backup.acme.net" in text and "refuse to deliver" in text and "raise the id" in text


def test_a_wildcard_stands_for_exactly_one_label():
    assert mta_sts.host_matches("*.example.com", "mx1.example.com")
    assert not mta_sts.host_matches("*.example.com", "a.b.example.com")
    assert not mta_sts.host_matches("*.example.com", "example.com")
    assert mta_sts.host_matches("mail.example.com", "MAIL.example.com.")


def test_testing_mode_and_a_short_memory_are_said_in_words():
    r, _ = run(policy="version: STSv1\nmode: testing\nmx: *.mail.protection.outlook.com\nmax_age: 600\n")
    text = " ".join(mta_sts.advice(r, True))
    assert "testing mode" in text and "10 minutes" in text


def test_no_record_is_only_mentioned_for_a_domain_that_receives_mail():
    r, asked = run(txt={})
    assert r.state == "none" and asked == [], "no file is fetched when there is no record"
    assert mta_sts.advice(r, True) and mta_sts.advice(r, False) == []


def test_an_unreachable_file_is_reported_as_unreadable_not_as_a_judgement_on_the_policy():
    r, _ = run(refuse="The address redirects, which is not followed here.")
    assert r.state == "unreadable" and r.mode is None
    assert "could not be read" in mta_sts.advice(r, True)[0]


def test_a_dns_failure_is_unreadable_not_none():
    r, _ = run(broken=True)
    assert r.state == "unreadable"


def test_a_broken_policy_file_lists_each_problem():
    r, _ = run(policy="mode: sometimes\nmax_age: soon\n")
    text = " ".join(r.issues)
    assert "version: STSv1" in text and "not enforce, testing or none" in text and "max_age" in text


def test_two_records_or_a_bad_id_are_not_a_valid_record():
    assert mta_sts.parse_record(["v=STSv1; id=abc", "v=STSv1; id=def"]) is None
    assert mta_sts.parse_record(["v=STSv1; id=has space!"]) is None
    assert mta_sts.parse_record(["v=STSv1; id=Abc123"]) == "Abc123"

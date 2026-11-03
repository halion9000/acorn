"""Blocklist answers: listed, clear, refused (the list will not answer us) and no answer (the lookup failed) are four different things."""

import asyncio

import pytest
from app.services import blocklist as bl


def lookup_from(table, failing=()):
    seen = []

    async def lookup(name):
        seen.append(name)
        if any(name.endswith(f) for f in failing):
            raise bl.LookupFailed("timed out")
        return table.get(name, [])

    lookup.seen = seen
    return lookup


@pytest.mark.parametrize(
    "zone,answers,status",
    [
        ("zen.spamhaus.org", [], "clear"),
        ("zen.spamhaus.org", ["127.0.0.2"], "listed"),
        ("zen.spamhaus.org", ["127.0.0.4", "127.0.0.10"], "listed"),
        ("zen.spamhaus.org", ["127.255.255.254"], "refused"),
        ("dbl.spamhaus.org", ["127.255.255.252"], "refused"),
        ("multi.uribl.com", ["127.0.0.1"], "refused"),
        ("multi.uribl.com", ["127.0.0.2"], "listed"),
        ("multi.surbl.org", ["127.0.0.8"], "listed"),
        ("bl.spamcop.net", ["8.8.8.8"], "refused"),
    ],
)
def test_the_answer_code_decides_listed_clear_or_refused(zone, answers, status):
    assert bl.classify(zone, answers)[0] == status


def test_a_refusal_is_never_reported_as_clear_and_says_why():
    status, detail = bl.classify("zen.spamhaus.org", ["127.255.255.254"])
    assert status != "clear" and "does not answer" in detail


def test_only_public_ipv4_addresses_are_ever_sent_to_a_list():
    assert bl.reverse_ipv4("8.8.4.0") == "0.4.8.8"
    for no in ["10.0.0.1", "192.168.1.1", "127.0.0.1", "169.254.1.1", "2001:4860:4860::8888", "nonsense", ""]:
        assert bl.reverse_ipv4(no) is None, no
    look = lookup_from({})
    assert asyncio.run(bl.check_ip("10.0.0.1", look)) == [] and look.seen == []


def test_an_address_is_asked_of_every_ip_list_and_each_answer_is_kept_apart():
    look = lookup_from({"4.3.2.1.zen.spamhaus.org": ["127.0.0.2"], "4.3.2.1.bl.spamcop.net": ["127.255.255.254"]}, failing=("uceprotect.net",))
    out = {r.zone: r.status for r in asyncio.run(bl.check_ip("1.2.3.4", look))}
    assert out == {"zen.spamhaus.org": "listed", "bl.spamcop.net": "refused", "psbl.surriel.com": "clear", "dnsbl-1.uceprotect.net": "no_answer"}
    assert sorted(look.seen) == sorted(f"4.3.2.1.{z}" for z, _ in bl.IP_LISTS)


def test_a_domain_is_asked_of_every_domain_list_and_one_failing_list_does_not_hide_the_rest():
    look = lookup_from({"evil.example.dbl.spamhaus.org": ["127.0.1.2"]}, failing=("surbl.org",))
    out = {r.zone: r.status for r in asyncio.run(bl.check_domain("Evil.Example.", look))}
    assert out == {"dbl.spamhaus.org": "listed", "multi.surbl.org": "no_answer", "multi.uribl.com": "clear"}


def test_an_unexpected_error_in_a_lookup_is_a_no_answer_not_a_crash():
    async def broken(name):
        raise RuntimeError("boom")

    assert {r.status for r in asyncio.run(bl.check_domain("a.example", broken))} == {"no_answer"}

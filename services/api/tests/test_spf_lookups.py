"""SPF lookups counted through every include: the number a receiver would count, and honesty when part of the chain cannot be read."""

import asyncio

import pytest
from app.services import spf_lookups as sl


class Dns:
    def __init__(self, records, broken=()):
        self.records, self.broken, self.asked = records, set(broken), []

    async def txt(self, name):
        self.asked.append(name)
        if name in self.broken:
            raise RuntimeError("down")
        rec = self.records.get(name)
        return [rec] if isinstance(rec, str) else list(rec or [])


def count(records, domain="acme.com", **kw):
    return asyncio.run(sl.count_lookups(domain, Dns(records, **kw)))


def test_a_plain_record_counts_its_own_lookups_and_ip_terms_cost_nothing():
    r = count({"acme.com": "v=spf1 ip4:1.2.3.4 ip6:2001:db8::/32 a mx include:_spf.example.net -all", "_spf.example.net": "v=spf1 ip4:5.6.7.8 -all"})
    assert (r.count, r.complete, r.over_limit) == (3, True, False)  # a, mx and the include; the ip terms are free and the included record costs nothing more


def test_the_includes_are_followed_and_their_lookups_are_counted_too():
    r = count(
        {
            "acme.com": "v=spf1 include:a.example include:b.example -all",
            "a.example": "v=spf1 a mx include:c.example -all",
            "b.example": "v=spf1 mx exists:%{i}.x.example -all",
            "c.example": "v=spf1 a a:mail.c.example -all",
        }
    )
    assert r.count == 2 + 3 + 2 + 2 and r.complete  # 2 includes + (a, mx, include) + (mx, exists) + (a, a:) = 9
    assert r.over_limit is False


def test_eleven_is_over_the_limit_and_ten_is_not():
    ten = "v=spf1 " + " ".join(f"include:i{i}.example" for i in range(10)) + " -all"
    eleven = "v=spf1 " + " ".join(f"include:i{i}.example" for i in range(11)) + " -all"
    leaf = {f"i{i}.example": "v=spf1 -all" for i in range(11)}
    assert count({"acme.com": ten, **leaf}).over_limit is False and count({"acme.com": ten, **leaf}).count == 10
    assert count({"acme.com": eleven, **leaf}).over_limit is True and count({"acme.com": eleven, **leaf}).count == 11


def test_a_redirect_is_followed_and_a_loop_is_counted_once_not_forever():
    r = count({"acme.com": "v=spf1 redirect=base.example", "base.example": "v=spf1 a mx"})
    assert r.count == 3 and r.complete
    loop = count({"acme.com": "v=spf1 include:b.example -all", "b.example": "v=spf1 include:acme.com -all"})
    assert loop.complete is True and loop.count == 2


def test_a_part_of_the_chain_that_cannot_be_read_makes_the_count_a_minimum_not_a_claim():
    r = count({"acme.com": "v=spf1 include:ok.example include:down.example -all", "ok.example": "v=spf1 a -all"}, broken=["down.example"])
    assert r.complete is False and r.count == 3
    missing = count({"acme.com": "v=spf1 include:nowhere.example -all"})
    assert missing.complete is False and missing.count == 1  # an include with no SPF record behind it is unknown, not free


def test_no_spf_record_or_two_of_them_counts_nothing_and_is_complete_at_the_top_level():
    assert count({}) == sl.SpfLookups(0, True, False)
    assert count({"acme.com": ["v=spf1 a -all", "v=spf1 mx -all"]}) == sl.SpfLookups(0, True, False)


def test_the_walk_is_bounded_in_depth_and_in_records_fetched():
    chain = {f"d{i}.example": f"v=spf1 include:d{i + 1}.example -all" for i in range(40)}
    chain["acme.com"] = "v=spf1 include:d0.example -all"
    dns = Dns(chain)
    r = asyncio.run(sl.count_lookups("acme.com", dns))
    assert r.complete is False and len(dns.asked) <= sl.MAX_DOMAINS

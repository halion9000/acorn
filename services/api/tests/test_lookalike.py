"""Lookalike domains: the names generated and which of them DNS says exist."""

import asyncio

import pytest
from app.services import lookalike as lk


class Dns:
    def __init__(self, a=(), mx=(), broken=()):
        self.a_set, self.mx_set, self.broken, self.calls = set(a), set(mx), set(broken), 0

    async def a(self, name):
        self.calls += 1
        if name in self.broken:
            raise RuntimeError("down")
        return ["1.2.3.4"] if name in self.a_set else []

    async def mx(self, name):
        if name in self.broken:
            raise RuntimeError("down")
        return ["mx." + name] if name in self.mx_set else []

    async def cname(self, name):
        return []

    async def txt(self, name):
        return []


@pytest.fixture(autouse=True)
def fresh():
    lk._CACHE.clear()


def test_each_kind_of_lookalike_is_generated_and_the_domain_itself_never_is():
    out = lk.generate("acme.com")
    assert out["acm.com"] == "omission" and out["aacme.com"] == "repetition" and out["amce.com"] == "swap"
    assert out["a-cme.com"] == "hyphen" and out["acme.co"] == "other-ending" and out["acme.net"] == "other-ending"
    assert lk.generate("rome.com")["rorne.com"] == "lookalike-character"  # m looks like rn
    assert "acme.com" not in out
    assert lk.generate("l0gic.com").get("logic.com") == "lookalike-character" and lk.generate("l0gic.com").get("10gic.com") == "lookalike-character"


def test_a_bad_domain_gives_nothing_and_the_list_is_capped_and_names_are_valid():
    assert lk.generate("nodot") == {} and lk.generate("") == {} and lk.generate("bad label.com") == {}
    big = lk.generate("a" * 40 + ".com")
    assert len(big) <= lk.MAX_CANDIDATES
    assert all(not n.split(".")[0].startswith("-") and not n.split(".")[0].endswith("-") for n in big)


def test_only_names_that_dns_shows_are_reported_and_the_ones_that_can_send_mail_come_first():
    dns = Dns(a={"acme.net", "acm.com"}, mx={"acme.co", "acme.net"})
    out = asyncio.run(lk.scan("acme.com", dns))
    assert [(x.domain, x.kind, x.has_mail) for x in out] == [("acme.co", "other-ending", True), ("acme.net", "other-ending", True), ("acm.com", "omission", False)]
    assert all(x.registered for x in out)


def test_a_failed_lookup_is_not_a_finding_and_a_result_is_cached_for_hours():
    dns = Dns(a={"acme.net"}, broken={"acme.co"})
    assert [x.domain for x in asyncio.run(lk.scan("acme.com", dns, now=1000))] == ["acme.net"]
    calls = dns.calls
    assert [x.domain for x in asyncio.run(lk.scan("acme.com", dns, now=1500))] == ["acme.net"] and dns.calls == calls
    asyncio.run(lk.scan("acme.com", dns, now=1000 + lk._TTL_SECONDS + 1))
    assert dns.calls > calls

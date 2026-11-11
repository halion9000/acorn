"""Finding a sending address's country from Team Cymru's DNS answers."""

import asyncio

import pytest
from app.services import ip_country as ic


class TxtResolver:
    def __init__(self, answers=None, broken=()):
        self.answers, self.broken, self.calls = answers or {}, set(broken), []

    async def txt(self, name):
        self.calls.append(name)
        if name in self.broken:
            raise RuntimeError("DNS is down")
        return self.answers.get(name, [])


@pytest.fixture(autouse=True)
def fresh_cache():
    ic._CACHE.clear()


def test_the_question_is_the_reversed_address_and_only_public_addresses_are_asked_about():
    assert ic.cymru_name("8.8.4.0") == "0.4.8.8.origin.asn.cymru.com"
    assert ic.cymru_name("2001:4860:4860::8888").endswith(".origin6.asn.cymru.com")
    assert ic.cymru_name("2001:4860:4860::8888").startswith("8.8.8.8.0.0.0.0.")
    for private in ["10.1.2.3", "192.168.0.9", "127.0.0.1", "169.254.1.1", "::1", "fe80::1", "not an ip", ""]:
        assert ic.cymru_name(private) is None, private


@pytest.mark.parametrize(
    "txt,expected",
    [
        ("15169 | 8.8.8.0/24 | US | arin | 2000-03-30", "US"),
        ('"15169 | 8.8.8.0/24 | DE | ripencc | 2000"', "DE"),
        ("15169 | 8.8.8.0/24 | ZZZ | x", None),
        ("garbage", None),
        ("1 | 2", None),
        ("1 | 2 | us | x", None),
    ],
)
def test_the_country_is_the_third_field_when_it_is_two_capital_letters(txt, expected):
    assert ic.parse_country(txt) == expected


def test_an_answer_is_cached_a_failure_is_not_and_a_private_address_costs_no_lookup():
    name = ic.cymru_name("8.8.4.0")
    r = TxtResolver({name: ["15169 | 8.8.4.0/24 | US | arin | 2000"]})
    assert asyncio.run(ic.country_of("8.8.4.0", r, now=1000)) == "US"
    assert asyncio.run(ic.country_of("8.8.4.0", r, now=1500)) == "US"
    assert len(r.calls) == 1
    assert asyncio.run(ic.country_of("8.8.4.0", r, now=1000 + ic._TTL_SECONDS + 1)) == "US"
    assert len(r.calls) == 2  # a day later it is asked again
    down = TxtResolver(broken=[ic.cymru_name("1.2.3.4")])
    assert asyncio.run(ic.country_of("1.2.3.4", down)) is None and asyncio.run(ic.country_of("1.2.3.4", down)) is None
    assert len(down.calls) == 2  # the failure was not remembered
    assert asyncio.run(ic.country_of("10.0.0.1", down)) is None
    assert len(down.calls) == 2

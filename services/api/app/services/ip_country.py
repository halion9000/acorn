"""Which country a sending address is in, from Team Cymru's free IP-to-ASN DNS service (a TXT lookup of the reversed address). Answers are cached for a day; a lookup that fails is not guessed at.

Only public addresses are looked up: a private, loopback or otherwise reserved address says nothing about a country and would only leak internal addressing to a third party.
"""

from __future__ import annotations

import ipaddress
import re
import time

from app.services.domain_posture import Resolver

_TTL_SECONDS = 24 * 3600
_MAX_CACHE = 5000
_CACHE: dict[str, tuple[float, str]] = {}
_COUNTRY = re.compile(r"^[A-Z]{2}$")


def cymru_name(ip: str) -> str | None:
    """The DNS name to ask about this address, or None when it is not a public address."""
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return None
    if not addr.is_global:
        return None
    if addr.version == 4:
        return ".".join(reversed(str(addr).split("."))) + ".origin.asn.cymru.com"
    return ".".join(reversed(addr.exploded.replace(":", ""))) + ".origin6.asn.cymru.com"


def parse_country(txt: str) -> str | None:
    """ "15169 | 8.8.8.0/24 | US | arin | 2000-03-30" gives "US". Anything else gives None."""
    fields = [f.strip() for f in txt.strip().strip('"').split("|")]
    return fields[2] if len(fields) >= 3 and _COUNTRY.match(fields[2]) else None


async def country_of(ip: str, resolver: Resolver, now: float | None = None) -> str | None:
    name = cymru_name(ip)
    if name is None:
        return None
    t = time.monotonic() if now is None else now
    hit = _CACHE.get(name)
    if hit and t - hit[0] < _TTL_SECONDS:
        return hit[1]
    try:
        answers = await resolver.txt(name)
    except Exception:  # a failed lookup reads as unknown, and is tried again next time
        return None
    for a in answers:
        code = parse_country(a)
        if code:
            if len(_CACHE) >= _MAX_CACHE:
                _CACHE.clear()
            _CACHE[name] = (t, code)
            return code
    return None

"""What an external scan looks up: public IP addresses typed in, and the addresses of domain names (typed in, or the domains of the people held for the tenant).

A domain is resolved through public DNS to its addresses (the name itself, ``www``, and the hosts that take its mail), keeping public IPv4 addresses only. Those addresses are looked up in
Shodan's InternetDB, which sends nothing to them. Only addresses typed in by hand are ever port-probed: an address that merely came out of someone else's DNS is never probed from here.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re

from app.services.domain_posture import MAX_DOMAINS, Resolver

MAX_RESOLVED_IPS = 64
_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def split_targets(entries: list[str]) -> tuple[list[str], list[str]]:
    """(public IP addresses, domain names) from what was typed; anything else raises ValueError naming it. Case, spaces and repeats are tidied."""
    ips: list[str] = []
    domains: list[str] = []
    for raw in entries:
        entry = raw.strip().lower().rstrip(".")
        if not entry:
            raise ValueError("an empty entry is not an IP address or a domain name")
        try:
            ip = ipaddress.ip_address(entry)
        except ValueError:
            if not _DOMAIN.match(entry):
                raise ValueError(f"{raw!r} is not an IP address or a domain name (ranges and internal names are not accepted)") from None
            if entry not in domains:
                domains.append(entry)
            continue
        if not ip.is_global:
            raise ValueError(f"{raw!r} is not a public IP address")
        if entry not in ips:
            ips.append(entry)
    return ips, domains


def within(name: str, domains: list[str]) -> bool:
    """Whether a host name is one of the domains or below one of them."""
    host = name.strip().lower().rstrip(".")
    return any(host == d or host.endswith(f".{d}") for d in domains)


def _public_v4(addresses: list[str]) -> list[str]:
    out: list[str] = []
    for a in addresses:
        try:
            ip = ipaddress.ip_address(a.strip())
        except ValueError:
            continue
        if ip.version == 4 and ip.is_global:
            out.append(str(ip))
    return out


async def resolve_domains(domains: list[str], resolver: Resolver) -> dict[str, list[str]]:
    """Each domain's public IPv4 addresses (its own, ``www``'s and its mail hosts'), at most ``MAX_RESOLVED_IPS`` across all of them."""
    found: dict[str, list[str]] = {}
    budget = MAX_RESOLVED_IPS

    async def one(domain: str) -> list[str]:
        mx = await resolver.mx(domain)
        # Only mail hosts that belong to the domain are the client's own servers; a hosted mail service (Microsoft, Google, a filtering provider) is not part of its attack surface.
        own_mail = [h for h in mx if h == domain or h.endswith(f".{domain}")]
        names = [domain, f"www.{domain}", *own_mail[:3]]
        answers = await asyncio.gather(*(resolver.a(n) for n in names))
        seen: list[str] = []
        for group in answers:
            for ip in _public_v4(group):
                if ip not in seen:
                    seen.append(ip)
        return seen

    results = await asyncio.gather(*(one(d) for d in domains[:MAX_DOMAINS]))
    for domain, ips in zip(domains[:MAX_DOMAINS], results, strict=True):
        keep = ips[:budget]
        budget -= len(keep)
        found[domain] = keep
    return found

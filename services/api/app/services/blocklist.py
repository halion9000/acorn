"""Blocklist checks for sending addresses and domains, over DNS.

A blocklist is asked by looking up the reversed address (or the domain) under the list's zone: an answer in 127.0.0.0/8 means listed, "no such name" means not listed. Two things make a naive check
dangerous, and both are handled here rather than shown as "clean":
- Several lists refuse to answer through big shared resolvers and say so with a special answer (127.255.255.x, or 127.0.0.1 from URIBL). That is "refused", not "not listed".
- A lookup that times out or fails is "no answer", not "not listed".
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

Status = Literal["listed", "clear", "refused", "no_answer"]
CONCURRENCY = 8

# (zone, name shown). Lists that need an account or are retired are left out rather than reported as always clear.
IP_LISTS: tuple[tuple[str, str], ...] = (
    ("zen.spamhaus.org", "Spamhaus ZEN"),
    ("bl.spamcop.net", "SpamCop"),
    ("psbl.surriel.com", "Passive Spam Block List"),
    ("dnsbl-1.uceprotect.net", "UCEPROTECT level 1"),
)
DOMAIN_LISTS: tuple[tuple[str, str], ...] = (
    ("dbl.spamhaus.org", "Spamhaus DBL"),
    ("multi.surbl.org", "SURBL"),
    ("multi.uribl.com", "URIBL"),
)

# A lookup: the 127.x answers for a name, an empty list for "no such name"; raises LookupFailed when it could not be asked.
Lookup = Callable[[str], Awaitable[list[str]]]


class LookupFailed(Exception):
    pass


@dataclass(frozen=True)
class ListResult:
    list_name: str
    zone: str
    status: Status
    detail: str = ""


def reverse_ipv4(ip: str) -> str | None:
    """The reversed dotted form of a public IPv4 address, or None (private, reserved, IPv6 or not an address): those are never sent to a list."""
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return None
    if addr.version != 4 or not addr.is_global:
        return None
    return ".".join(reversed(str(addr).split(".")))


def classify(zone: str, answers: list[str]) -> tuple[Status, str]:
    """What the answers from one list mean. No answers is clear; a refusal code is refused; anything else in 127/8 is a listing."""
    if not answers:
        return "clear", ""
    codes = [a for a in answers if a.startswith("127.")]
    if not codes:
        return "refused", "The list gave an answer that is not a listing code."
    if any(c.startswith("127.255.255.") for c in codes):
        return "refused", "The list does not answer queries from this resolver (shared or public resolvers are refused)."
    if zone == "multi.uribl.com" and codes == ["127.0.0.1"]:
        return "refused", "URIBL refuses queries from this resolver."
    return "listed", ", ".join(sorted(codes))


async def system_lookup(name: str) -> list[str]:
    """Ask the server's own resolver for the A records of a name. "No such name" is an empty list; any other failure raises LookupFailed."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(name, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        if e.errno in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", socket.EAI_NONAME)):
            return []
        raise LookupFailed(str(e)) from None
    except OSError as e:
        raise LookupFailed(str(e)) from None
    return sorted({i[4][0] for i in infos})


async def _ask(zone: str, label: str, query: str, lookup: Lookup, gate: asyncio.Semaphore) -> ListResult:
    async with gate:
        try:
            answers = await lookup(query)
        except LookupFailed as e:
            return ListResult(label, zone, "no_answer", f"The lookup did not complete ({e}).")
        except Exception:  # never let one list's failure hide the others
            return ListResult(label, zone, "no_answer", "The lookup did not complete.")
    status, detail = classify(zone, answers)
    return ListResult(label, zone, status, detail)


async def check_ip(ip: str, lookup: Lookup = system_lookup) -> list[ListResult]:
    rev = reverse_ipv4(ip)
    if rev is None:
        return []
    gate = asyncio.Semaphore(CONCURRENCY)
    return list(await asyncio.gather(*(_ask(z, n, f"{rev}.{z}", lookup, gate) for z, n in IP_LISTS)))


async def check_domain(domain: str, lookup: Lookup = system_lookup) -> list[ListResult]:
    gate = asyncio.Semaphore(CONCURRENCY)
    return list(await asyncio.gather(*(_ask(z, n, f"{domain.strip().lower().rstrip('.')}.{z}", lookup, gate) for z, n in DOMAIN_LISTS)))

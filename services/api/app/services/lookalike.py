"""Lookalike domains: names someone could register to pass as a client's domain, and which of them exist.

The names are generated the way the well-known tools do (a letter dropped, doubled or swapped, look-alike characters, a hyphen, a different ending). Whether one is registered is read from public DNS only
(an address or mail record); nothing here connects to those sites. A registered name with no records at all is not seen, so "none found" means none with records, not none registered.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass

from app.services.domain_posture import Resolver

MAX_CANDIDATES = 300
CONCURRENCY = 10
_TTL_SECONDS = 6 * 3600
_CACHE: dict[str, tuple[float, list[Lookalike]]] = {}
_LABEL = re.compile(r"^[a-z0-9-]{1,63}$")

# Characters that read alike at a glance.
_HOMOGLYPHS: dict[str, list[str]] = {
    "o": ["0"],
    "0": ["o"],
    "l": ["1", "i"],
    "1": ["l"],
    "i": ["l", "1"],
    "m": ["rn"],
    "w": ["vv"],
    "a": ["e"],
    "e": ["a"],
    "s": ["5"],
    "g": ["q"],
    "q": ["g"],
    "u": ["v"],
    "v": ["u"],
}
_OTHER_ENDINGS = ("com", "net", "org", "co", "us", "biz", "info", "cm", "om", "co.uk", "io")


@dataclass(frozen=True)
class Lookalike:
    domain: str
    kind: str  # omission, repetition, swap, lookalike-character, hyphen, other-ending
    registered: bool = False
    has_mail: bool = False


def _split(domain: str) -> tuple[str, str] | None:
    label, _, ending = domain.strip().lower().rstrip(".").partition(".")
    return (label, ending) if label and ending and _LABEL.match(label) else None


def generate(domain: str) -> dict[str, str]:
    """Candidate domain -> the kind of change that made it. The domain itself is never a candidate. Capped, with the likeliest kinds first."""
    parts = _split(domain)
    if parts is None:
        return {}
    label, ending = parts
    out: dict[str, str] = {}

    def add(new_label: str, kind: str, new_ending: str | None = None) -> None:
        name = f"{new_label}.{new_ending or ending}"
        if (
            name != f"{label}.{ending}"
            and _LABEL.match(new_label)
            and not new_label.startswith("-")
            and not new_label.endswith("-")
            and name not in out
        ):
            out[name] = kind

    for i, ch in enumerate(label):
        for repl in _HOMOGLYPHS.get(ch, []):
            add(label[:i] + repl + label[i + 1 :], "lookalike-character")
    for i in range(len(label) - 1):
        add(label[:i] + label[i + 1] + label[i] + label[i + 2 :], "swap")
    for i in range(len(label)):
        add(label[:i] + label[i + 1 :], "omission")
        add(label[: i + 1] + label[i] + label[i + 1 :], "repetition")
    for i in range(1, len(label)):
        add(label[:i] + "-" + label[i:], "hyphen")
    for other in _OTHER_ENDINGS:
        if other != ending:
            add(label, "other-ending", other)
    return dict(list(out.items())[:MAX_CANDIDATES])


async def _exists(name: str, resolver: Resolver) -> tuple[bool, bool]:
    """(registered as far as DNS shows, can receive mail). A failed lookup counts as nothing found, and is not cached."""
    try:
        mail = bool([m for m in await resolver.mx(name) if m.strip(". ")])
        return (mail or bool(await resolver.a(name)), mail)
    except Exception:
        return (False, False)


async def scan(domain: str, resolver: Resolver, now: float | None = None) -> list[Lookalike]:
    """The lookalikes of this domain that exist, those that can send mail first. Cached for hours: the answer changes slowly and the scan is hundreds of lookups."""
    t = time.monotonic() if now is None else now
    key = domain.strip().lower().rstrip(".")
    hit = _CACHE.get(key)
    if hit and t - hit[0] < _TTL_SECONDS:
        return hit[1]
    candidates = generate(key)
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(name: str, kind: str) -> Lookalike | None:
        async with gate:
            registered, mail = await _exists(name, resolver)
        return Lookalike(name, kind, True, mail) if registered else None

    found = [x for x in await asyncio.gather(*(one(n, k) for n, k in candidates.items())) if x]
    found.sort(key=lambda x: (not x.has_mail, x.domain))
    _CACHE[key] = (t, found)
    return found

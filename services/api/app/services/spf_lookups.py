"""How many DNS lookups a domain's SPF record really costs.

A receiver stops after ten lookups (include, a, mx, ptr, exists, redirect) and treats SPF as failed (RFC 7208, "permerror"). The ten is counted through every include, so a short record that includes a
big sender can already be over. This follows the includes and redirects (each domain once, a few levels deep) and says how many lookups the whole record costs. When part of the chain could not be
read it says so and gives a minimum, never a number it cannot back up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.domain_posture import _LOOKUP, Resolver

LIMIT = 10
WARN_AT = 8
MAX_DEPTH = 6
MAX_DOMAINS = 25  # a hard stop on how many records are fetched for one answer


@dataclass(frozen=True)
class SpfLookups:
    count: int  # lookups counted so far (all of them when complete)
    complete: bool  # False when some record in the chain could not be read, so count is a minimum
    over_limit: bool  # True only when count is above the limit: a minimum above it is already enough


def _spf_record(txt: list[str]) -> str | None:
    records = [t.strip() for t in txt if t.strip().lower().startswith("v=spf1")]
    return records[0] if len(records) == 1 else None  # none, or several (an error of its own that the SPF check reports)


async def count_lookups(domain: str, resolver: Resolver) -> SpfLookups:
    seen: set[str] = set()
    state = {"count": 0, "complete": True}

    async def walk(name: str, depth: int) -> None:
        key = name.lower().rstrip(".")
        if key in seen:
            return
        if depth > MAX_DEPTH or len(seen) >= MAX_DOMAINS:
            state["complete"] = False
            return
        seen.add(key)
        try:
            record = _spf_record(await resolver.txt(key))
        except Exception:  # a failed lookup is "could not read", not "no lookups"
            state["complete"] = False
            return
        if record is None:
            if depth > 0:
                state["complete"] = False  # an include that names no usable record: its cost is unknown (and receivers call it an error)
            return
        for term in record.split()[1:]:
            if not _LOOKUP.match(term):
                continue
            state["count"] += 1
            bare = re.sub(r"^[+\-~?]", "", term)
            if bare.lower().startswith("include:"):
                await walk(bare.split(":", 1)[1], depth + 1)
            elif bare.lower().startswith("redirect="):
                await walk(bare.split("=", 1)[1], depth + 1)

    await walk(domain, 0)
    return SpfLookups(count=state["count"], complete=bool(state["complete"]), over_limit=state["count"] > LIMIT)

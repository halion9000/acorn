"""Possible duplicate people on the Identities page: two people of ONE client who may be the same human but that no automatic rule joined.

The automatic rules in ``identity_merge`` only join what is certain. Everything that is merely likely lands here as a suggestion for the owner to confirm (Merge) or dismiss (Not the same person, which is
remembered and stops the pair coming back). Pure functions: no database, no clock.

A pair is suggested only inside one client (a person at another client is never suggested), never for a shared mailbox, a guest or a generic name such as admin, and never when the owner already said the
two are separate. Each pair carries a score and the reasons in plain words:

* the same display name (two or more words, after taking off a tag such as "@ PPP" or "(old)"): the strongest sign;
* the same name before the ``@`` on different domains (``marla@a.com`` and ``marla@b.com``): a good sign, and weaker when the name is short or common;
* a display name that matches the other's address (``Marla Falcon`` and ``mfalcon@...``): a supporting sign.

Two licensed accounts are still suggested (it is exactly the case a rule will not decide), but the pair says so: it is two paid seats, so merging is a deliberate choice.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from app.services.identity_merge import GENERIC_LOCALS, MIN_LOCAL

# A name shared by more people than this in one client is a common name, not a sign: every one of the pairs would be a guess.
MAX_BUCKET = 6
# The score each sign adds, and the lowest total that is worth showing.
NAME_SCORE = 60
LOCAL_SCORE = 30
PATTERN_SCORE = 25
MIN_SHOWN = 55
HIGH = 85

_TAG = re.compile(r"\s+(@|-|–|—|\(|\[|\|)\s*.*$")
_NON_WORD = re.compile(r"[^a-z0-9 ]+")


def name_key(display_name: str | None) -> str | None:
    """A display name reduced to what identifies a person: lower case, accents and punctuation gone, a trailing tag ("@ PPP", "- old", "(contractor)") taken off. None when fewer than two words remain
    (a first name alone says nothing) or when the name is itself an address."""
    if not display_name or "@" in display_name.split(" ")[0]:
        return None
    text = unicodedata.normalize("NFKD", display_name).encode("ascii", "ignore").decode("ascii").lower()
    text = _TAG.sub("", text.strip())
    text = " ".join(_NON_WORD.sub(" ", text).split())
    return text if len(text.split()) >= 2 else None


def local_key(address: str) -> str | None:
    """The part before the ``@``, lower case, or None when it is too short or a role name (admin, support, ...) rather than a person."""
    local = address.split("@", 1)[0].strip().lower()
    return local if len(local) >= MIN_LOCAL and local not in GENERIC_LOCALS else None


def _pattern_keys(name: str) -> set[str]:
    """The ways a person's address is usually made from their name: first.last, firstlast, flast, first_last, first."""
    words = name.split()
    first, last = words[0], words[-1]
    return {
        f"{first}.{last}",
        f"{first}{last}",
        f"{first[0]}{last}",
        f"{first}_{last}",
        f"{first}-{last}",
        f"{first}{last[0]}",
        f"{last}.{first}",
    }


@dataclass
class DuplicatePair:
    client_id: uuid.UUID
    a: Any
    b: Any
    score: int
    reasons: list[str] = field(default_factory=list)
    both_licensed: bool = False

    @property
    def label(self) -> str:
        return "high" if self.score >= HIGH else "medium"


def _eligible(p: Any) -> bool:
    return p.kind == "user" and "#ext#" not in p.email.lower()


def _pair_key(a: Any, b: Any) -> tuple[str, str]:
    first, second = sorted((a.email, b.email))
    return first, second


def _separated(a: Any, b: Any, separate: set[tuple[uuid.UUID, str, str]]) -> bool:
    """True when the owner marked any address of one as not the same person as any address of the other."""
    for x in a.addresses:
        for y in b.addresses:
            lo, hi = sorted((x.lower(), y.lower()))
            if (a.tenant_id, lo, hi) in separate:
                return True
    return False


def find_duplicates(people: list[Any], separate: list[tuple[uuid.UUID, str, str]], limit: int = 500) -> list[DuplicatePair]:
    """The suggested pairs, strongest first. ``separate`` are the owner's "not the same person" marks as (client, address, address)."""
    marks = {(t, *sorted((x.lower(), y.lower()))) for t, x, y in separate}
    by_name: dict[tuple[uuid.UUID, str], list[Any]] = {}
    by_local: dict[tuple[uuid.UUID, str], list[Any]] = {}
    for p in people:
        if not _eligible(p):
            continue
        nk = name_key(p.display_name)
        if nk:
            by_name.setdefault((p.tenant_id, nk), []).append(p)
        for address in p.addresses:
            lk = local_key(address)
            if lk:
                by_local.setdefault((p.tenant_id, lk), []).append(p)

    pairs: dict[tuple[uuid.UUID, tuple[str, str]], DuplicatePair] = {}

    def add(a: Any, b: Any, score: int, reason: str) -> None:
        if a is b or a.tenant_id != b.tenant_id or _separated(a, b, marks):
            return
        key = (a.tenant_id, _pair_key(a, b))
        found = pairs.get(key)
        if found is None:
            found = pairs[key] = DuplicatePair(
                client_id=a.tenant_id, a=a, b=b, score=0, both_licensed=a.licensed is True and b.licensed is True
            )
        if reason not in found.reasons:
            found.score += score
            found.reasons.append(reason)

    for (_tenant, name), group in by_name.items():
        members = list({id(p): p for p in group}.values())
        if 2 <= len(members) <= MAX_BUCKET:
            for a, b in combinations(members, 2):
                add(a, b, NAME_SCORE, f"The same name: {name.title()}")
    for (_tenant, local), group in by_local.items():
        members = list({id(p): p for p in group}.values())
        if 2 <= len(members) <= MAX_BUCKET:
            for a, b in combinations(members, 2):
                if a.email.split("@")[-1].lower() != b.email.split("@")[-1].lower():
                    add(a, b, LOCAL_SCORE, f"The same name before the @: {local}")
    # A display name that matches the other person's address: supports a pair another sign already found; never makes one alone.
    for pair in list(pairs.values()):
        for x, y in ((pair.a, pair.b), (pair.b, pair.a)):
            nk = name_key(x.display_name)
            if nk and any(local_key(addr) in _pattern_keys(nk) for addr in y.addresses if local_key(addr)):
                reason = f"The name {x.display_name} matches the address {y.email}"
                if reason not in pair.reasons:
                    pair.score += PATTERN_SCORE
                    pair.reasons.append(reason)
    out = [p for p in pairs.values() if p.score >= MIN_SHOWN]
    out.sort(key=lambda p: (-p.score, p.a.email, p.b.email))
    return out[:limit]

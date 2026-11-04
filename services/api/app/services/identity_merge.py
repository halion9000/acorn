"""Putting the several addresses of one human together on the Identities page.

The tools key a person by whatever address they hold, so one human often appears as several rows: the Microsoft sign-in name, the client's own domain, the ``.onmicrosoft.com`` address, a guest sign-in name,
an address a tool reports only as a display name. This module finds those pairs and folds each group into ONE person (the "primary" address plus its aliases). Pure functions: no database, no clock.

Automatic rules, all inside ONE client (a person at another client is never joined) and none for a shared mailbox:

* ``display_name``: a person's display name is itself another address, on the SAME domain, that exists for the client, and that address is the display name of no one else (a tool that names the account by its
  primary address). A name shared by several accounts, or an address on another domain, joins nothing.
* ``guest``: ``name_domain.com#EXT#@client.onmicrosoft.com`` is how Microsoft writes the guest sign-in name of ``name@domain.com``; when that address exists, they are one person.
* ``hash``: a 32-character hexadecimal prefix on an ``.onmicrosoft.com`` address is a system prefix on the same address without it.
* ``onmicrosoft``: an ``.onmicrosoft.com`` address and exactly ONE real-domain address with the same name before the ``@``, both ordinary (member) accounts and the real address on one of the client's OWN
  domains (not a generic name such as admin or support, which are often different accounts, and not a guest from another company who happens to share a first name).

Two accounts that each hold a licence are never joined automatically: each is a paid seat, so they are two accounts a person is paying for, whatever their names say. (A hand merge is still allowed.)

A person can also be merged by hand, and "not the same person" is remembered: an automatic rule never joins two groups that hold a pair marked separate. A hand merge is the owner's word and wins.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

# Names before the @ that are usually a role, not a person: the same name on two domains is often two different accounts (a break-glass admin, a shared inbox).
GENERIC_LOCALS: frozenset[str] = frozenset(
    {
        "admin", "administrator", "info", "support", "sales", "office", "billing", "accounting", "accounts", "service", "noreply", "no-reply", "helpdesk", "help", "it", "hr", "test", "user",
        "contact", "mail", "postmaster", "root", "webmaster", "marketing", "team", "staff", "reception", "frontdesk", "front", "orders", "scanner", "scan", "print", "printer", "alerts", "security",
    }
)  # fmt: skip
MIN_LOCAL = 3
# No automatic rule builds a person out of more than this many addresses: a real person has a handful, and a longer chain means a rule is joining people it should not. A hand merge is not limited.
MAX_GROUP = 6

_EXT = re.compile(r"^(.+)_([^_#@]+)#ext#@[^@]+$")
_HASH = re.compile(r"^[0-9a-f]{32}(.+)$")

REASON_TEXT = {
    "display_name": "its name is this address",
    "guest": "the guest sign-in name of this address",
    "hash": "the same address with a system prefix",
    "onmicrosoft": "the same name on the client's Microsoft address",
    "manual": "merged by hand",
}


def is_onmicrosoft(address: str) -> bool:
    return address.endswith(".onmicrosoft.com")


@dataclass(frozen=True)
class Link:
    a: str  # person key
    b: str
    reason: str


def find_links(people: dict[str, Any]) -> list[Link]:
    """The automatic pairs among ``people`` (person key -> Person). Each person is one address at this stage."""
    by_addr: dict[tuple[uuid.UUID, str], Any] = {(p.tenant_id, p.email): p for p in people.values()}
    links: list[Link] = []
    named_by: dict[tuple[uuid.UUID, str], int] = {}
    for p in people.values():
        n = (p.display_name or "").strip().lower()
        if "@" in n:
            named_by[(p.tenant_id, n)] = named_by.get((p.tenant_id, n), 0) + 1

    def link(p: Any, q: Any, reason: str) -> None:
        if q is None or q is p or p.kind == "shared" or q.kind == "shared":
            return
        links.append(Link(p.key, q.key, reason))

    for p in people.values():
        t, e = p.tenant_id, p.email
        name = (p.display_name or "").strip().lower()
        if "@" in name and name != e and name.partition("@")[2] == e.partition("@")[2] and named_by.get((t, name)) == 1:
            link(p, by_addr.get((t, name)), "display_name")
        m = _EXT.match(e)
        if m:
            link(p, by_addr.get((t, f"{m.group(1)}@{m.group(2)}")), "guest")
        local, _, domain = e.partition("@")
        h = _HASH.match(local)
        if h and is_onmicrosoft(e):
            link(p, by_addr.get((t, f"{h.group(1)}@{domain}")), "hash")

    # Same name on the client's Microsoft address and on exactly one real domain of the client's own.
    members_by_domain: dict[tuple[uuid.UUID, str], int] = {}
    for p in people.values():
        if p.kind == "user":
            key = (p.tenant_id, p.email.partition("@")[2])
            members_by_domain[key] = members_by_domain.get(key, 0) + 1
    by_local: dict[tuple[uuid.UUID, str], list[Any]] = {}
    for p in people.values():
        by_local.setdefault((p.tenant_id, p.email.partition("@")[0]), []).append(p)
    for (t, local), group in by_local.items():
        if len(group) < 2 or len(local) < MIN_LOCAL or local in GENERIC_LOCALS:
            continue
        real = [p for p in group if not is_onmicrosoft(p.email)]
        if len(real) != 1 or real[0].kind != "user" or not _own_domain(t, real[0].email, members_by_domain, group):
            continue
        for p in group:
            if is_onmicrosoft(p.email) and p.kind == "user":
                link(p, real[0], "onmicrosoft")
    return links


def _own_domain(tenant: uuid.UUID, address: str, members_by_domain: dict[tuple[uuid.UUID, str], int], group: list[Any]) -> bool:
    """Whether the real address is on a domain the client itself uses: two or more ordinary accounts of the client have it, or it is named like the client's Microsoft address (tecovas.com for tecovas.onmicrosoft.com)."""
    domain = address.partition("@")[2]
    if members_by_domain.get((tenant, domain), 0) >= 2:
        return True
    label = domain.split(".")[0]
    return any(is_onmicrosoft(p.email) and p.email.partition("@")[2].split(".")[0] == label for p in group)


_MFA_RANK = {"covered": 3, "registered_not_required": 2, "none": 1, "unknown": 0}


def _score(p: Any) -> tuple:
    """Which address is the one to show: Microsoft's own record first, then a real domain over a system address, then the person with more tools, then alphabetical (so the choice is stable)."""
    e = p.email
    has_ms = any(s.vendor == "cipp" for s in p.sources)
    # 0 a real domain, 1 the client's .onmicrosoft.com address, 2 a guest sign-in name or a system-prefixed address (the least like what a person would give out).
    system = 2 if ("#ext#" in e or (is_onmicrosoft(e) and _HASH.match(e.partition("@")[0]))) else (1 if is_onmicrosoft(e) else 0)
    return (not has_ms, system, -len({s.vendor for s in p.sources}), e)


def _fold(members: list[Any], reasons: dict[str, str]) -> Any:
    """One person from several: the primary's address and facts, plus what the others add."""
    ordered = sorted(members, key=_score)
    p = ordered[0]
    primary_has_microsoft = any(s.vendor == "cipp" for s in p.sources)
    seen = {(s.vendor, s.external_id) for s in p.sources}
    for q in ordered[1:]:
        for s in q.sources:
            if (s.vendor, s.external_id) not in seen:
                seen.add((s.vendor, s.external_id))
                p.sources.append(s)
        p.aliases.append(q.email)
        p.alias_reasons[q.email] = reasons.get(q.key, "merged")
    if not p.display_name or "@" in p.display_name:
        better = next((q.display_name for q in ordered if q.display_name and "@" not in q.display_name), None)
        p.display_name = better or p.display_name
    states = [q.enabled for q in ordered if q.enabled is not None]
    p.enabled = True if True in states else (False if states else None)
    p.admin = any(q.admin for q in ordered)
    lic = [q.licensed for q in ordered if q.licensed is not None]
    p.licensed = True if True in lic else (False if lic else None)
    if not primary_has_microsoft or p.mfa == "unknown":
        # The primary has no Microsoft record (or it says nothing): take the most protected state the others report, never inventing one.
        best = max(ordered, key=lambda q: _MFA_RANK.get(q.mfa, 0))
        if _MFA_RANK.get(best.mfa, 0) > _MFA_RANK.get(p.mfa, 0):
            p.mfa, p.mfa_methods = best.mfa, best.mfa_methods or p.mfa_methods
    if not p.mfa_methods:
        p.mfa_methods = next((q.mfa_methods for q in ordered if q.mfa_methods), None)
    p.sources.sort(key=lambda r: (r.vendor != "cipp", r.vendor, r.external_id))
    return p


def merge_people(
    people: dict[str, Any],
    manual: list[tuple[uuid.UUID, str, str]] | None = None,
    separate: list[tuple[uuid.UUID, str, str]] | None = None,
) -> list[Any]:
    """Fold ``people`` (person key -> Person, one address each) into one person per human. ``manual`` and ``separate`` are (client, address, address) pairs the owner chose."""
    parent = {k: k for k in people}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    reasons: dict[str, str] = {}

    def addr_key(t: uuid.UUID, a: str) -> str | None:
        k = f"{t}:{a}"
        return k if k in people else None

    blocked = [(addr_key(t, a), addr_key(t, b)) for t, a, b in (separate or [])]
    blocked = [(x, y) for x, y in blocked if x and y]

    # How many licensed accounts each group holds: two licensed accounts are two paid seats, so no rule joins them (a chain of rules cannot either).
    licensed = {k: (1 if people[k].licensed is True else 0) for k in people}
    size = {k: 1 for k in people}

    def union(a: str, b: str, reason: str, respect_blocked: bool) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if respect_blocked and (any({find(x), find(y)} == {ra, rb} for x, y in blocked) or licensed[ra] + licensed[rb] > 1 or size[ra] + size[rb] > MAX_GROUP):
            return
        parent[ra] = rb
        licensed[rb] += licensed[ra]
        size[rb] += size[ra]
        for k in (a, b):
            reasons.setdefault(k, reason)

    for t, a, b in manual or []:
        ka, kb = addr_key(t, a), addr_key(t, b)
        if ka and kb:
            union(ka, kb, "manual", False)
    for lk in find_links(people):
        union(lk.a, lk.b, lk.reason, True)

    groups: dict[str, list[Any]] = {}
    for k, p in people.items():
        groups.setdefault(find(k), []).append(p)
    out: list[Any] = []
    for members in groups.values():
        out.append(members[0] if len(members) == 1 else _fold(members, {k: REASON_TEXT.get(r, r) for k, r in reasons.items()}))
    return out

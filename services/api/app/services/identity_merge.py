"""Putting the several addresses of one human together on the Identities page.

The tools key a person by whatever address they hold, so one human often appears as several rows: the Microsoft sign-in name, the client's own domain, the ``.onmicrosoft.com`` address, a guest sign-in name,
an address a tool reports only as a display name. This module finds those pairs and folds each group into ONE person (the "primary" address plus its aliases). Pure functions: no database, no clock.

Automatic rules, all inside ONE client (a person at another client is never joined) and none for a shared mailbox:

* ``display_name``: a person's display name is itself another address, on the SAME domain, that exists for the client, and that address is the display name of no one else (a tool that names the account by its
  primary address). A name shared by several accounts, or an address on another domain, joins nothing, with one exception: the client's ``.onmicrosoft.com`` address named by the real address with
  the SAME name before the ``@`` (``julio@acme.onmicrosoft.com`` named "julio@acme.com"). The directory itself says whose account it is, so this pair is joined even when each address counts a licence
  (one human seen by two directories) and whoever else shares the name before the ``@``.
* ``guest``: ``name_domain.com#EXT#@client.onmicrosoft.com`` is how Microsoft writes the guest sign-in name of ``name@domain.com``; when that address exists, they are one person.
* ``hash``: a 32-character hexadecimal prefix on an ``.onmicrosoft.com`` address is a system prefix on the same address without it.
* ``same_person``: two accounts of the client with the SAME display name (two or more words, a tag such as "@ PPP" ignored) AND the same name before the ``@`` on different domains, and nobody else
  of the client has that name and local part. Two independent signs, one pair: the client's second domain, or its Microsoft address next to its real one. Ordinary member accounts only.
* ``onmicrosoft``: an ``.onmicrosoft.com`` address and exactly ONE real-domain address with the same name before the ``@``, both ordinary (member) accounts and the real address on one of the client's OWN
  domains (not a generic name such as admin or support, which are often different accounts, and not a guest from another company who happens to share a first name).

Two accounts that each hold a licence are never joined automatically: each is a paid seat, so they are two accounts a person is paying for, whatever their names say. (A hand merge is still allowed.)

A person can also be merged by hand, and "not the same person" is remembered: an automatic rule never joins two groups that hold a pair marked separate. A hand merge is the owner's word and wins.
"""

from __future__ import annotations

import re
import unicodedata
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


_EXT = re.compile(r"^(.+)_([^_#@]+)#ext#@[^@]+$")
_HASH = re.compile(r"^[0-9a-f]{32}(.+)$")

REASON_TEXT = {
    "display_name": "its name is this address",
    "guest": "the guest sign-in name of this address",
    "hash": "the same address with a system prefix",
    "onmicrosoft": "the same name on the client's Microsoft address",
    "same_person": "the same display name and the same name before the @",
    "manual": "merged by hand",
}


def is_onmicrosoft(address: str) -> bool:
    return address.endswith(".onmicrosoft.com")


@dataclass(frozen=True)
class Link:
    a: str  # person key
    b: str
    reason: str
    # The tool itself names one address by the other across the client's Microsoft and real domains: joined even when both count a licence.
    named: bool = False


def find_links(people: dict[str, Any]) -> list[Link]:
    """The automatic pairs among ``people`` (person key -> Person). Each person is one address at this stage."""
    by_addr: dict[tuple[uuid.UUID, str], Any] = {(p.tenant_id, p.email): p for p in people.values()}
    links: list[Link] = []
    named_by: dict[tuple[uuid.UUID, str], int] = {}
    for p in people.values():
        n = (p.display_name or "").strip().lower()
        if "@" in n:
            named_by[(p.tenant_id, n)] = named_by.get((p.tenant_id, n), 0) + 1

    def link(p: Any, q: Any, reason: str, named: bool = False) -> None:
        if q is None or q is p or p.kind == "shared" or q.kind == "shared":
            return
        links.append(Link(p.key, q.key, reason, named))

    for p in people.values():
        t, e = p.tenant_id, p.email
        name = (p.display_name or "").strip().lower()
        if "@" in name and name != e and named_by.get((t, name)) == 1:
            # The Microsoft address and the real one, the same name before the @: one account under its two names.
            microsoft_pair = name.partition("@")[0] == e.partition("@")[0] and is_onmicrosoft(name) != is_onmicrosoft(e)
            if microsoft_pair or name.partition("@")[2] == e.partition("@")[2]:
                link(p, by_addr.get((t, name)), "display_name", named=microsoft_pair)
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

    # The same display name AND the same name before the @ on two different domains, with nobody else of the client holding that pair: the same human on two of the client's domains.
    by_person: dict[tuple[uuid.UUID, str, str], list[Any]] = {}
    for p in people.values():
        key_name = name_key(p.display_name)
        local = p.email.partition("@")[0]
        if key_name is None or p.kind != "user" or len(local) < MIN_LOCAL or local in GENERIC_LOCALS or _EXT.match(p.email):
            continue
        by_person.setdefault((p.tenant_id, key_name, local), []).append(p)
    for group in by_person.values():
        if len(group) == 2 and group[0].email.partition("@")[2] != group[1].email.partition("@")[2]:
            link(group[0], group[1], "same_person")
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
    # One account seen under two addresses is not two seats. CIPP lists every account of a tenant it manages, so in such a client an address CIPP does not list is not an account of its own, whatever other tools
    # (ThreatMate's directory, the PSA's contact list, an EDR) also hold it: it is the same account under another address (its .onmicrosoft.com name), and its licence is not counted a second time.
    cipp_tenants = {p.tenant_id for p in people.values() if any(s.vendor == "cipp" for s in p.sources)}

    def echo_only(p: Any) -> bool:
        return p.tenant_id in cipp_tenants and not any(s.vendor == "cipp" for s in p.sources)

    licensed = {k: (1 if people[k].licensed is True and not echo_only(people[k]) else 0) for k in people}
    size = {k: 1 for k in people}

    def union(a: str, b: str, reason: str, respect_blocked: bool, named: bool = False) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if respect_blocked and (
            any({find(x), find(y)} == {ra, rb} for x, y in blocked)
            or (licensed[ra] + licensed[rb] > 1 and not named)
            or size[ra] + size[rb] > MAX_GROUP
        ):
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
        union(lk.a, lk.b, lk.reason, True, lk.named)

    groups: dict[str, list[Any]] = {}
    for k, p in people.items():
        groups.setdefault(find(k), []).append(p)
    out: list[Any] = []
    for members in groups.values():
        out.append(members[0] if len(members) == 1 else _fold(members, {k: REASON_TEXT.get(r, r) for k, r in reasons.items()}))
    return out

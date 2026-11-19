"""Client families: which clients are linked under one parent company (roadmap huntress-family). Pure helpers; the database reads live in the endpoint."""

from __future__ import annotations

import uuid
from typing import Any


def family_map(members: list[tuple[uuid.UUID, uuid.UUID]]) -> dict[uuid.UUID, uuid.UUID]:
    """``client -> family`` from (family id, client id) rows. A client in two families (it cannot be, the table forbids it) keeps the first."""
    out: dict[uuid.UUID, uuid.UUID] = {}
    for family_id, client_id in members:
        out.setdefault(client_id, family_id)
    return out


def same_family(families: dict[uuid.UUID, uuid.UUID], a: uuid.UUID, b: uuid.UUID) -> bool:
    """Whether two different clients are linked in one family."""
    return a != b and a in families and families.get(a) == families.get(b)


def siblings(families: dict[uuid.UUID, uuid.UUID], client: uuid.UUID) -> set[uuid.UUID]:
    """The other clients of this client's family (empty when it is in none)."""
    fam = families.get(client)
    return set() if fam is None else {c for c, f in families.items() if f == fam and c != client}


def clean_members(client_ids: list[uuid.UUID], valid: set[uuid.UUID], taken: dict[uuid.UUID, uuid.UUID], family_id: uuid.UUID | None) -> tuple[list[uuid.UUID], str | None]:
    """The members to save, without repeats, and a reason when the list cannot be saved (pure): every id must be one of the caller's clients, and a client already in ANOTHER family is refused."""
    seen: list[uuid.UUID] = []
    for c in client_ids:
        if c not in seen:
            seen.append(c)
    for c in seen:
        if c not in valid:
            return [], "One of the clients is not one of yours."
        if c in taken and taken[c] != family_id:
            return [], "One of the clients is already in another family. Take it out there first."
    return seen, None


def summary(family: Any, member_names: list[str]) -> dict[str, Any]:
    return {"id": family.id, "name": family.name, "clients": sorted(member_names, key=str.lower)}

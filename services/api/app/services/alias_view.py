"""The owner's client mapping, read once and shared for a few seconds.

Every report CORE sends for a client (license counts, Microsoft 365 checks, sign-ins, MFA, secure scores, identities...) first needs to know which client tenant the tool's client id is mapped to. That
meant reading ALL of the owner's client aliases (thousands) and every child tenant on every report, about a tenth of a second each, and with hundreds of reports arriving together that alone kept
the API's one CPU busy so that pages timed out. The mapping changes rarely, so it is kept for ``TTL_SECONDS``.

It is cleared at once whenever a client alias or a tenant is written through the ORM in this process (so a mapping a person just saved applies to the next report), and it expires on its own after
``TTL_SECONDS`` for any change made some other way. Only plain values are kept (never an ORM object, which belongs to a session that is gone).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, NamedTuple

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models.client_alias import ClientAlias
from app.models.tenant import Tenant

TTL_SECONDS = 5.0


class AliasView(NamedTuple):
    """What the report routes read of a ClientAlias (the same attribute names)."""

    ignored: bool
    child_tenant_id: uuid.UUID | None
    vendor_client_name: str | None


_cache: dict[uuid.UUID, tuple[float, dict[tuple[str, str], AliasView], frozenset[uuid.UUID]]] = {}


def forget_aliases() -> None:
    _cache.clear()


async def alias_view(db: Any, owner: uuid.UUID) -> tuple[dict[tuple[str, str], AliasView], frozenset[uuid.UUID]]:
    """``({(vendor, vendor client id): alias}, ids of the owner's child tenants)``, from memory when read in the last ``TTL_SECONDS``."""
    now = time.monotonic()
    hit = _cache.get(owner)
    if hit is not None and now - hit[0] < TTL_SECONDS:
        return hit[1], hit[2]
    rows = (await db.execute(select(ClientAlias).where(ClientAlias.tenant_id == owner))).scalars().all()
    known = {(a.vendor, a.vendor_client_id): AliasView(a.ignored, a.child_tenant_id, a.vendor_client_name) for a in rows}
    children = frozenset((await db.execute(select(Tenant.id).where(Tenant.parent_tenant_id == owner))).scalars().all())
    _cache[owner] = (now, known, children)
    return known, children


@event.listens_for(Session, "before_flush")
def _forget_on_flush(session: Session, _ctx: Any, _instances: Any) -> None:
    for obj in (*session.new, *session.dirty, *session.deleted):
        if isinstance(obj, ClientAlias | Tenant):
            _cache.clear()
            return


@event.listens_for(Session, "do_orm_execute")
def _forget_on_dml(state: Any) -> None:
    if state.is_insert or state.is_update or state.is_delete:
        if any(m.class_ in (ClientAlias, Tenant) for m in state.all_mappers):
            _cache.clear()

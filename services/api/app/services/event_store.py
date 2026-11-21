"""The event store (SIEM style storage, step 2): append events from any source, never change them, keep them for as long as the client's retention says.

``append_events`` writes a batch and skips an event it already holds (same organization, source, kind and external id), so a source that is read again does not make copies. ``retention_years`` reads a client's
retention (1, 3, 5, 7 or 10 years; infinite by default) and ``purge_expired`` deletes only what a client's retention has passed, the one way a stored event is ever removed.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

MAX_BATCH = 500
MAX_PAYLOAD_BYTES = 65536
RETENTION_CHOICES = (1, 3, 5, 7, 10)


@dataclass(frozen=True)
class NewEvent:
    source: str
    kind: str
    event_time: datetime
    external_id: str
    payload: dict[str, Any]
    client_id: uuid.UUID | None = None


def parse_event(raw: Any) -> NewEvent | None:
    """One event as a source sends it, or None when it cannot be kept (pure): it needs a source, a kind, an external id, a time and an object payload that is not too large."""
    if not isinstance(raw, dict):
        return None
    source = str(raw.get("source") or "").strip()[:64]
    kind = str(raw.get("kind") or "").strip()[:64]
    external_id = str(raw.get("external_id") or "").strip()[:200]
    payload = raw.get("payload")
    if not source or not kind or not external_id or not isinstance(payload, dict):
        return None
    if len(json.dumps(payload, default=str)) > MAX_PAYLOAD_BYTES:
        return None
    when = raw.get("event_time")
    try:
        at = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    client = None
    if raw.get("client_id"):
        try:
            client = uuid.UUID(str(raw["client_id"]))
        except ValueError:
            return None
    return NewEvent(source=source, kind=kind, event_time=at, external_id=external_id, payload=payload, client_id=client)


async def append_events(db: Any, tenant_id: uuid.UUID, raws: list[Any], now: datetime | None = None) -> dict[str, int]:
    """Store a batch (at most MAX_BATCH): {"stored": new events, "duplicates": already held, "refused": not usable}. Never updates a stored row."""
    when = now or datetime.now(UTC)
    events = [e for e in (parse_event(r) for r in raws[:MAX_BATCH]) if e is not None]
    refused = len(raws[:MAX_BATCH]) - len(events)
    stored = 0
    for e in events:
        res = await db.execute(
            text(
                """
                INSERT INTO stored_events (tenant_id, client_id, source, kind, event_time, pulled_at, external_id, payload)
                VALUES (:t, :c, :s, :k, :et, :pa, :x, CAST(:p AS JSONB))
                ON CONFLICT ON CONSTRAINT stored_events_once DO NOTHING
                """
            ).bindparams(t=tenant_id, c=e.client_id, s=e.source, k=e.kind, et=e.event_time, pa=when, x=e.external_id, p=json.dumps(e.payload, default=str))
        )
        stored += res.rowcount or 0
    return {"stored": stored, "duplicates": len(events) - stored, "refused": refused}


def retention_years(settings: dict[str, Any] | None, client_id: str | None) -> int | None:
    """How many years a client's events are kept (pure): the client's own choice, else the organization's default, else None (infinite). A value that is not one of the choices means infinite, never a guess."""
    r = (settings or {}).get("retention") or {}
    per = r.get("clients") or {}
    value = per.get(client_id) if client_id and client_id in per else r.get("default")
    return value if isinstance(value, int) and not isinstance(value, bool) and value in RETENTION_CHOICES else None


def cutoff(years: int | None, now: datetime) -> datetime | None:
    """The time before which events are past retention (pure); None for infinite."""
    return None if years is None else now - timedelta(days=365 * years + years // 4)


async def purge_expired(db: Any, tenant_id: uuid.UUID, settings: dict[str, Any] | None, now: datetime | None = None) -> int:
    """Delete the events a client's retention has passed (the organization's default covers a client with no choice of its own). Returns how many were deleted; with every client infinite it deletes nothing."""
    when = now or datetime.now(UTC)
    deleted = 0
    await db.execute(text("SET LOCAL aisoc.event_purge = 'on'"))
    clients = (await db.execute(text("SELECT DISTINCT client_id FROM stored_events WHERE tenant_id = :t"), {"t": tenant_id})).scalars().all()
    for client in clients:
        years = retention_years(settings, str(client) if client else None)
        limit = cutoff(years, when)
        if limit is None:
            continue
        res = await db.execute(
            text("DELETE FROM stored_events WHERE tenant_id = :t AND client_id IS NOT DISTINCT FROM :c AND event_time < :limit"), {"t": tenant_id, "c": client, "limit": limit}
        )
        deleted += res.rowcount or 0
    return deleted


async def expired_counts(db: Any, tenant_id: uuid.UUID, settings: dict[str, Any] | None, now: datetime | None = None) -> dict[str, int]:
    """How many events each client's retention has passed right now, {client id or "none": count}, without deleting anything (what a purge would remove)."""
    when = now or datetime.now(UTC)
    out: dict[str, int] = {}
    clients = (await db.execute(text("SELECT DISTINCT client_id FROM stored_events WHERE tenant_id = :t"), {"t": tenant_id})).scalars().all()
    for client in clients:
        limit = cutoff(retention_years(settings, str(client) if client else None), when)
        if limit is None:
            continue
        n = (
            await db.execute(text("SELECT count(*) FROM stored_events WHERE tenant_id = :t AND client_id IS NOT DISTINCT FROM :c AND event_time < :limit"), {"t": tenant_id, "c": client, "limit": limit})
        ).scalar_one()
        if n:
            out[str(client) if client else "none"] = int(n)
    return out

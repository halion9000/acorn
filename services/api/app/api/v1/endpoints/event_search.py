"""Search the event store (SIEM style storage, step 4): one client's stored events by time range, source, kind and text, with paging, and the whole raw event.

Read with ``reports:read``. The store belongs to the organization (row-level security); ``client_id`` narrows the search to one client's events, and an event about no particular client is found with ``client_id=none``.
The text matches the event's external id and anywhere in its JSON. Newest first; the page after one is asked for with ``before`` (the id of its last event).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.api.v1.deps import AuthUser, DBSession, require_permission

router = APIRouter(prefix="/events", tags=["events"])

PAGE = 100
PREVIEW = 240


class EventRow(BaseModel):
    id: int
    client_id: uuid.UUID | None
    source: str
    kind: str
    event_time: datetime
    pulled_at: datetime
    external_id: str
    preview: str


class EventPage(BaseModel):
    rows: list[EventRow]
    # The id to pass as ``before`` for the next page; None when this is the last one.
    next_before: int | None = None
    sources: list[str]


class EventFull(EventRow):
    payload: dict[str, Any]


def like_pattern(q: str) -> str:
    """The text as a LIKE pattern that matches it literally anywhere (pure): % and _ and the escape character (!) are escaped."""
    return "%" + q.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def build_query(client: str | None, source: str | None, kind: str | None, since: datetime | None, until: datetime | None, q: str, before: int | None) -> tuple[str, dict[str, Any]]:
    """The WHERE part and its values for a search (pure)."""
    where = ["true"]
    values: dict[str, Any] = {}
    if client == "none":
        where.append("client_id IS NULL")
    elif client:
        where.append("client_id = :client")
        values["client"] = uuid.UUID(client)
    if source:
        where.append("source = :source")
        values["source"] = source
    if kind:
        where.append("kind = :kind")
        values["kind"] = kind
    if since is not None:
        where.append("event_time >= :since")
        values["since"] = since
    if until is not None:
        where.append("event_time < :until")
        values["until"] = until
    if q.strip():
        where.append("(external_id ILIKE :q ESCAPE '!' OR payload::text ILIKE :q ESCAPE '!')")
        values["q"] = like_pattern(q.strip())
    if before is not None:
        where.append("id < :before")
        values["before"] = before
    return " AND ".join(where), values


def preview_of(payload: dict[str, Any]) -> str:
    """A short single line of what an event says (pure): its summary, title or message when it has one, else the start of its JSON."""
    import json

    for key in ("summary", "title", "message", "name", "description"):
        v = payload.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()[:PREVIEW]
    return json.dumps(payload, default=str)[:PREVIEW]


@router.get("/search", response_model=EventPage, dependencies=[Depends(require_permission("reports:read"))], summary="Search the stored events of an organization or one of its clients")
async def search_events(
    user: AuthUser,
    db: DBSession,
    client_id: Annotated[str | None, Query(pattern=r"^(none|[0-9a-fA-F-]{36})$")] = None,
    source: Annotated[str | None, Query(max_length=64)] = None,
    kind: Annotated[str | None, Query(max_length=64)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    q: Annotated[str, Query(max_length=200)] = "",
    before: Annotated[int | None, Query(ge=1)] = None,
) -> EventPage:
    where, values = build_query(client_id, source, kind, since, until, q, before)
    rows = (
        await db.execute(
            text(f"SELECT id, client_id, source, kind, event_time, pulled_at, external_id, payload FROM stored_events WHERE tenant_id = :tenant AND {where} ORDER BY id DESC LIMIT :limit"),
            {**values, "tenant": user.tenant_id, "limit": PAGE + 1},
        )
    ).all()
    page = rows[:PAGE]
    sources = (await db.execute(text("SELECT DISTINCT source FROM stored_events WHERE tenant_id = :t ORDER BY 1"), {"t": user.tenant_id})).scalars().all()
    return EventPage(
        rows=[EventRow(id=r.id, client_id=r.client_id, source=r.source, kind=r.kind, event_time=r.event_time, pulled_at=r.pulled_at, external_id=r.external_id, preview=preview_of(r.payload)) for r in page],
        next_before=page[-1].id if len(rows) > PAGE else None,
        sources=list(sources),
    )


@router.get("/{event_id}", response_model=EventFull, dependencies=[Depends(require_permission("reports:read"))], summary="One stored event, whole")
async def get_event(event_id: int, user: AuthUser, db: DBSession) -> EventFull:
    r = (
        await db.execute(
            text("SELECT id, client_id, source, kind, event_time, pulled_at, external_id, payload FROM stored_events WHERE tenant_id = :t AND id = :i"), {"t": user.tenant_id, "i": event_id}
        )
    ).first()
    if r is None:
        raise HTTPException(status_code=404, detail="No such event")
    return EventFull(id=r.id, client_id=r.client_id, source=r.source, kind=r.kind, event_time=r.event_time, pulled_at=r.pulled_at, external_id=r.external_id, preview=preview_of(r.payload), payload=r.payload)

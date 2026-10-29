"""The history of each client-review question: what A.C.O.R.N worked out over time, and what people typed.

The review is computed on every read, so an automatic answer used to leave no trace: when "193 of 204 people have a second factor" became "204 of 204", nothing said when. Each read now compares every
question's worked-out status and evidence with the last automatic row stored and writes a row only when they differ; a person's typed answer or note is a manual row. ``changed`` and ``snapshot`` are pure.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text

from app.models.client_review_history import ClientReviewHistory

DETAIL_CHARS = 1000
# Rows kept per question; the oldest go first.
KEEP_PER_QUESTION = 200
LIST_LIMIT = 100


@dataclass(frozen=True)
class Reading:
    section: str
    key: str
    status: str | None
    detail: str | None


def _cut(text: str | None) -> str | None:
    text = (text or "").strip()
    return text[:DETAIL_CHARS] if text else None


def snapshot(readiness: list[Any], tech: list[Any], m365: list[Any], assess: list[Any]) -> list[Reading]:
    """Every question's worked-out status and evidence, taken BEFORE a person's typed answers are laid over them (the merge changes the objects)."""
    out = [Reading("readiness", i.key, i.status, _cut(i.evidence)) for i in readiness]
    out += [Reading("tech", a.key, a.status, _cut(" - ".join(x for x in (a.suggested, a.evidence) if x))) for a in tech]
    out += [Reading("m365", a.question[:400], a.status, _cut(a.evidence)) for a in m365]
    out += [Reading("assess", a.question[:400], a.status, _cut(a.evidence)) for a in assess]
    return out


def changed(readings: list[Reading], last: dict[tuple[str, str], tuple[str | None, str | None]]) -> list[Reading]:
    """The readings that differ from the last automatic row (or have none yet)."""
    return [r for r in readings if last.get((r.section, r.key)) != (r.status, r.detail)]


async def last_automatic(db: Any, tenant_id: uuid.UUID) -> dict[tuple[str, str], tuple[str | None, str | None]]:
    """The newest automatic row of each question of this client: ``{(section, key): (status, detail)}``."""
    newest = (
        select(ClientReviewHistory.section, ClientReviewHistory.key, func.max(ClientReviewHistory.at).label("at"))
        .where(ClientReviewHistory.tenant_id == tenant_id, ClientReviewHistory.source == "automatic")
        .group_by(ClientReviewHistory.section, ClientReviewHistory.key)
        .subquery()
    )
    rows = (
        await db.execute(
            select(ClientReviewHistory.section, ClientReviewHistory.key, ClientReviewHistory.status, ClientReviewHistory.detail)
            .join(
                newest,
                (ClientReviewHistory.section == newest.c.section)
                & (ClientReviewHistory.key == newest.c.key)
                & (ClientReviewHistory.at == newest.c.at),
            )
            .where(ClientReviewHistory.tenant_id == tenant_id, ClientReviewHistory.source == "automatic")
        )
    ).all()
    return {(r.section, r.key): (r.status, r.detail) for r in rows}


async def record_automatic(db: Any, tenant_id: uuid.UUID, readings: list[Reading], now: datetime | None = None) -> int:
    """Store the readings that changed since the last read. The caller has put ``db`` in the client's row-level-security scope and commits. Returns how many rows were written."""
    now = now or datetime.now(UTC)
    todo = changed(readings, await last_automatic(db, tenant_id))
    for r in todo:
        db.add(
            ClientReviewHistory(
                tenant_id=tenant_id, section=r.section, key=r.key, at=now, source="automatic", status=r.status, detail=r.detail
            )
        )
    if todo:
        await db.flush()
        await prune_tenant(db, tenant_id)
    return len(todo)


async def record_manual(
    db: Any,
    tenant_id: uuid.UUID,
    section: str,
    key: str,
    *,
    status: str | None,
    answer: str | None,
    note: str | None,
    actor: str | None,
    cleared: bool = False,
    now: datetime | None = None,
) -> None:
    """A person typed, changed or cleared an answer or a note. The caller commits."""
    db.add(
        ClientReviewHistory(
            tenant_id=tenant_id,
            section=section,
            key=key,
            at=now or datetime.now(UTC),
            source="manual",
            status=status,
            detail="Typed answer removed: back to what A.C.O.R.N works out" if cleared else _cut(answer),
            note=None if cleared else ((note or "").strip() or None),
            actor=(actor or None) and actor[:320],
        )
    )


async def history(db: Any, tenant_id: uuid.UUID, section: str, key: str, limit: int = LIST_LIMIT) -> list[dict[str, Any]]:
    """One question's rows, newest first."""
    rows = (
        (
            await db.execute(
                select(ClientReviewHistory)
                .where(ClientReviewHistory.tenant_id == tenant_id, ClientReviewHistory.section == section, ClientReviewHistory.key == key)
                .order_by(ClientReviewHistory.at.desc(), ClientReviewHistory.id)
                .limit(max(1, min(limit, LIST_LIMIT)))
            )
        )
        .scalars()
        .all()
    )
    return [{"at": r.at, "source": r.source, "status": r.status, "detail": r.detail, "note": r.note, "actor": r.actor} for r in rows]


async def prune_tenant(db: Any, tenant_id: uuid.UUID) -> None:
    """Keep only the newest ``KEEP_PER_QUESTION`` rows of each question of this client (one statement)."""
    await db.execute(
        text(
            "DELETE FROM client_review_history WHERE id IN (SELECT id FROM (SELECT id, row_number() OVER (PARTITION BY section, key ORDER BY at DESC, id) AS rn "
            "FROM client_review_history WHERE tenant_id = :t) x WHERE x.rn > :n)"
        ),
        {"t": tenant_id, "n": KEEP_PER_QUESTION},
    )

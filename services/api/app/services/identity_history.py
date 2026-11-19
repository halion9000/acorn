"""Joiners and leavers from the directory (roadmap r7-af-25, Hal 2026-11-18: "first seen as the join date, leavers recorded from now on").

Every directory snapshot passes through ``record_snapshot``: an account seen for the first time gets ``first_seen`` (marked baseline when it was already there the first time its source ever reported, since
its real join day is unknown); an account that is disabled, or missing from a finished snapshot, gets ``left_at``; one that comes back loses it. ``report`` turns the rows into the two lists (pure).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.identity_history import IdentityHistory


async def record_snapshot(db: Any, tenant_id: uuid.UUID, source: str, items: list[Any], snapshot_id: uuid.UUID, last: bool, now: datetime | None = None) -> None:
    """Apply one chunk of a source's snapshot for one client. ``items`` have ``id``, ``upn``, ``display_name`` and ``enabled``. On the last chunk, accounts not in this snapshot are marked as left."""
    now = now or datetime.now(UTC)
    if items:
        seen_before = (
            await db.execute(select(exists().where(IdentityHistory.tenant_id == tenant_id, IdentityHistory.source == source, IdentityHistory.snapshot_id != snapshot_id)))
        ).scalar_one()
        values = [
            {
                "tenant_id": tenant_id,
                "source": source,
                "user_id": str(u.id)[:100],
                "upn": str(u.upn)[:320],
                "display_name": (u.display_name or None),
                "first_seen": now,
                "baseline": not seen_before,
                "last_seen": now,
                "left_at": None if u.enabled else now,
                "snapshot_id": snapshot_id,
            }
            for u in items
        ]
        stmt = pg_insert(IdentityHistory).values(values)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["tenant_id", "source", "user_id"],
                set_={
                    "upn": stmt.excluded.upn,
                    "display_name": stmt.excluded.display_name,
                    "last_seen": now,
                    "snapshot_id": snapshot_id,
                    # disabled: keep the first time it was seen so; enabled again: back
                    "left_at": case((stmt.excluded.left_at.is_(None), None), else_=func.coalesce(IdentityHistory.left_at, stmt.excluded.left_at)),
                },
            )
        )
    if last:
        await db.execute(
            update(IdentityHistory)
            .where(IdentityHistory.tenant_id == tenant_id, IdentityHistory.source == source, IdentityHistory.snapshot_id != snapshot_id, IdentityHistory.left_at.is_(None))
            .values(left_at=now)
        )


def report(rows: list[dict[str, Any]], now: datetime, days: int = 30) -> dict[str, Any]:
    """The accounts first seen (not baseline) and the accounts that left in the last ``days`` days, newest first (pure). Each row has ``client``, ``upn``, ``name``, ``first_seen``, ``left_at`` and ``baseline``."""
    since = now - timedelta(days=days)

    def out(r: dict[str, Any], when: datetime) -> dict[str, Any]:
        return {"client": r.get("client") or "", "upn": r["upn"], "name": r.get("name") or "", "when": when.isoformat()}

    joiners = [out(r, r["first_seen"]) for r in rows if not r.get("baseline") and r["first_seen"] >= since]
    leavers = [out(r, r["left_at"]) for r in rows if r.get("left_at") is not None and r["left_at"] >= since]
    joiners.sort(key=lambda r: r["when"], reverse=True)
    leavers.sort(key=lambda r: r["when"], reverse=True)
    return {"days": days, "joiners": joiners, "leavers": leavers}

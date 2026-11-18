"""Keeps the roadmap in step with the repository file docs/ROADMAP_ITEMS.json (the assistant that does the work maintains that file as work goes on).

An item with a ``key`` is owned by the file: its title, detail, area, status, needs, note and finish reference follow it. Its ``priority`` is the person's and is never touched. An item with no key (added on the page)
is never touched. An item whose key leaves the file stays as it is. A status a person set is kept (unless the file says completed), and an item a person removed is never brought back. Nothing is deleted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.roadmap import RoadmapItem

STATUSES = ("new", "not_started", "in_progress", "completed")
NEEDS = ("claude", "signoff", "hal")
PRIORITIES = ("high", "normal", "low")
OWNED = ("title", "detail", "area", "status", "needs", "note", "completed_ref")


def _day(value: Any) -> datetime | None:
    """A day written YYYY-MM-DD in the file as midday UTC (so it reads as that day in any time zone), or None; anything else is ignored (pure)."""
    text = str(value or "").strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(hour=12, tzinfo=UTC) if text else None
    except ValueError:
        return None


def clean(entry: dict[str, Any]) -> dict[str, Any]:
    """One file entry made safe: unknown status or needs refused, text trimmed to the column sizes (pure)."""
    key = str(entry.get("key") or "").strip()
    title = str(entry.get("title") or "").strip()
    if not key or not title:
        raise ValueError("every item needs a key and a title")
    status = entry.get("status", "not_started")
    needs = entry.get("needs", "claude")
    if status not in STATUSES:
        raise ValueError(f"{key}: status {status!r} is not one of {STATUSES}")
    if needs not in NEEDS:
        raise ValueError(f"{key}: needs {needs!r} is not one of {NEEDS}")
    return {
        "added": _day(entry.get("added")),
        "done": _day(entry.get("completed")),
        "key": key[:80],
        "title": title[:200],
        "detail": str(entry.get("detail") or ""),
        "area": (str(entry.get("area") or "General").strip() or "General")[:60],
        "status": status,
        "needs": needs,
        "note": str(entry.get("note") or ""),
        "completed_ref": (str(entry["completed_ref"])[:80] if entry.get("completed_ref") else None),
    }


async def sync(db: AsyncSession, tenant: uuid.UUID, entries: list[dict[str, Any]]) -> dict[str, int]:
    """Add the new keys, bring the changed ones up to date. Returns how many were added, changed and left alone."""
    wanted = [clean(e) for e in entries]
    if len({w["key"] for w in wanted}) != len(wanted):
        raise ValueError("a key appears twice in the file")
    rows = {
        r.key: r
        for r in (await db.execute(select(RoadmapItem).where(RoadmapItem.tenant_id == tenant, RoadmapItem.key.is_not(None)))).scalars()
    }
    added = changed = same = 0
    now = datetime.now(UTC)
    for w in wanted:
        added_at, done_at = w.pop("added"), w.pop("done")
        row = rows.get(w["key"])
        if row is None:
            db.add(
                RoadmapItem(
                    id=uuid.uuid4(),
                    tenant_id=tenant,
                    created_by="assistant",
                    created_at=added_at or now,
                    updated_at=now,
                    completed_at=(done_at or now) if w["status"] == "completed" else None,
                    **w,
                )
            )
            added += 1
            continue
        if row.removed_at is not None:
            same += 1
            continue
        # A status a person set on the page is theirs, unless the file now says the work is finished.
        keep_status = row.person_status and w["status"] != "completed"
        # An item the person approved stays approved: the file still saying "signoff" does not take it back.
        keep_needs = row.approved_at is not None and w["needs"] == "signoff"
        diff = {k: w[k] for k in OWNED if not (k == "status" and keep_status) and not (k == "needs" and keep_needs) and getattr(row, k) != w[k]}
        # The days the file gives are the truth about when the item was added and finished.
        dates = {}
        if added_at and row.created_at != added_at:
            dates["created_at"] = added_at
        if done_at and (w["status"] == "completed" or row.status == "completed") and row.completed_at != done_at:
            dates["completed_at"] = done_at
        if not diff and not dates:
            same += 1
            continue
        for k, v in dates.items():
            setattr(row, k, v)
        for k, v in diff.items():
            setattr(row, k, v)
        if "status" in diff:
            row.completed_at = ((done_at or now) if w["status"] == "completed" else None)
            row.person_status = False
        row.updated_at = now
        changed += 1
    await db.commit()
    return {"added": added, "changed": changed, "unchanged": same}

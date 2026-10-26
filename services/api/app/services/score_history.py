"""A client's check score kept once a day, and what it did over a stretch of days. ``trend`` is pure; ``record_today`` reads the client's stored checks and writes today's row."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.signin import CheckWeight, ClientCheckAcceptance, ClientM365Check, ClientScoreHistory
from app.services.fleet_posture import FleetCheck, summarize
from app.services.infra_review import TOOL_CHECK_SOURCES


def trend(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """From a client's daily scores (any order): the first and last score with a value, the change between them, and whether it is better, worse or the same. Days with no score are skipped.

    ``direction`` is "none" when fewer than two days have a score.
    """
    scored = sorted((r for r in rows if r.get("score") is not None), key=lambda r: r["day"])
    if len(scored) < 2:
        return {"first": scored[0]["score"] if scored else None, "last": scored[0]["score"] if scored else None, "change": None, "direction": "none", "days": len(scored)}
    first, last = scored[0]["score"], scored[-1]["score"]
    change = last - first
    return {"first": first, "last": last, "change": change, "direction": "better" if change > 0 else "worse" if change < 0 else "same", "days": len(scored)}


def summary_of_rows(rows: list[Any], accepted_keys: set[str], weights: dict[str, int] | None = None) -> dict[str, Any]:
    """The score and counts for stored check rows (ClientM365Check) of one client, the same way the fleet page works them out."""
    checks = [
        FleetCheck(client_id="", client_name="", source=r.source, key=str(c["key"]), status=str(c["status"]), evidence="", accepted=str(c["key"]) in accepted_keys)
        for r in rows
        for c in r.checks or []
        if isinstance(c, dict) and c.get("key") and c.get("status")
    ]
    return summarize(checks, weights)


async def record_today(db: Any, tenant_id: uuid.UUID, now: datetime | None = None, weights: dict[str, int] | None = None) -> None:
    """Store (or replace) today's score row for a client from its stored tool checks. The caller has the session scoped to that client and owns the transaction."""
    now = now or datetime.now(UTC)
    rows = (await db.execute(select(ClientM365Check).where(ClientM365Check.tenant_id == tenant_id, ClientM365Check.source.in_(list(TOOL_CHECK_SOURCES))))).scalars().all()
    if not rows:
        return
    accepted = {a.key for a in (await db.execute(select(ClientCheckAcceptance).where(ClientCheckAcceptance.tenant_id == tenant_id))).scalars().all() if a.expires_at is None or a.expires_at > now}
    s = summary_of_rows(rows, accepted, weights)
    values = {"tenant_id": tenant_id, "day": now.date() if isinstance(now, datetime) else date.today(), "score": s["score"], "met": s["met"], "partly": s["partly"], "not_met": s["not_met"], "accepted": s["accepted"]}
    stmt = pg_insert(ClientScoreHistory).values(values)
    await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "day"], set_={c: stmt.excluded[c] for c in values if c not in ("tenant_id", "day")}))


async def load_weights(db: Any, owner: uuid.UUID) -> dict[str, int]:
    """The owner's check weights ({key: 1 to 5}); checks not listed count 1. An older database without the table gives none. Read in the owner's own scope."""
    try:
        async with db.begin_nested():
            return {r.key: int(r.weight) for r in (await db.execute(select(CheckWeight).where(CheckWeight.tenant_id == owner))).scalars().all()}
    except Exception:  # noqa: BLE001
        return {}

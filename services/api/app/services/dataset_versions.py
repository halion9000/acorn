"""Versions of the datasets CORE sends (SIEM style storage, step 3): the replaced snapshots are kept, append-only.

A version is stored when its content differs from every version already held (SHA-256 of the canonical JSON) and the newest held version of that dataset is at least ``MIN_GAP`` old, so a dataset that CORE
recomputes every hour is kept a few times a day at most, and only when it really changed.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

MIN_GAP = timedelta(hours=6)


def digest(payload: dict[str, Any]) -> str:
    """SHA-256 of the payload's canonical JSON (pure): the same facts give the same digest whatever the order of the keys."""
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


async def keep_version(db: Any, tenant_id: uuid.UUID, key: str, payload: dict[str, Any], now: datetime | None = None) -> bool:
    """Store this state of a dataset as a version when it is new and the last version is old enough; True when one was stored."""
    when = now or datetime.now(UTC)
    newest = (await db.execute(text("SELECT max(received_at) FROM dataset_versions WHERE tenant_id = :t AND key = :k"), {"t": tenant_id, "k": key})).scalar_one_or_none()
    if newest is not None and when - newest < MIN_GAP:
        return False
    res = await db.execute(
        text(
            """
            INSERT INTO dataset_versions (tenant_id, key, received_at, sha256, payload)
            VALUES (:t, :k, :at, :h, CAST(:p AS JSONB))
            ON CONFLICT ON CONSTRAINT dataset_versions_once DO NOTHING
            """
        ).bindparams(t=tenant_id, k=key, at=when, h=digest(payload), p=json.dumps(payload, default=str))
    )
    return bool(res.rowcount)

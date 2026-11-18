"""What CORE says about itself with each status report: the commit it runs, how long it has been up and how many feed passes it has made since it started.

Kept in Redis for 20 minutes per client tenant, like the approvals: if CORE stops reporting, the line disappears instead of showing a CORE that may long since have stopped. Nothing but those three values is kept.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from redis.exceptions import RedisError

from app.core import token_revocation

logger = logging.getLogger("aisoc.core_heartbeat")

KEEP_SECONDS = 20 * 60
_KEY = "aisoc:core-heartbeat:"


async def remember(tenant_id: Any, commit: str, uptime_seconds: int, sweeps: int, now: datetime | None = None) -> None:
    """Store CORE's latest values. Best effort: a Redis problem is logged and never fails the status report."""
    body = {"reported_at": (now or datetime.now(UTC)).isoformat(), "commit": commit[:40], "uptime_seconds": max(0, int(uptime_seconds)), "sweeps": max(0, int(sweeps))}
    try:
        await token_revocation._get_client().set(_KEY + str(tenant_id), json.dumps(body), ex=KEEP_SECONDS)  # noqa: SLF001 - the one shared Redis client
    except (RedisError, OSError) as exc:
        logger.warning("core_heartbeat.remember_failed", extra={"err": str(exc)})


async def recall(tenant_id: Any) -> dict[str, Any] | None:
    """``{reported_at, commit, uptime_seconds, sweeps}``, or None when CORE has not reported lately (or never sent them) or Redis cannot be read."""
    try:
        raw = await token_revocation._get_client().get(_KEY + str(tenant_id))  # noqa: SLF001
    except (RedisError, OSError):
        return None
    if not raw:
        return None
    try:
        body = json.loads(raw)
    except ValueError:
        return None
    return body if isinstance(body, dict) else None

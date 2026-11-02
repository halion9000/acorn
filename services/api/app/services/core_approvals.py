"""The approvals CORE says are waiting for the owner, as of CORE's last report, so the notification bell can show them.

CORE sends the list with its status report every few minutes. It is kept in Redis for 20 minutes per client tenant: if CORE stops reporting, the list disappears instead of showing approvals that may long since have been answered.
Only the agent's name, a one-line summary and how long it has waited are kept, nothing from the approval's detail.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from redis.exceptions import RedisError

from app.core import token_revocation

logger = logging.getLogger("aisoc.core_approvals")

KEEP_SECONDS = 20 * 60
_KEY = "aisoc:core-approvals:"


async def remember(tenant_id: Any, items: list[dict[str, Any]], now: datetime | None = None) -> None:
    """Store CORE's current list (an empty list is stored too: it means nothing is waiting). Best effort: a Redis problem is logged and never fails the status report."""
    body = {"reported_at": (now or datetime.now(UTC)).isoformat(), "items": items}
    try:
        await token_revocation._get_client().set(_KEY + str(tenant_id), json.dumps(body), ex=KEEP_SECONDS)  # noqa: SLF001 - the one shared Redis client
    except (RedisError, OSError) as exc:
        logger.warning("core_approvals.remember_failed", extra={"err": str(exc)})


async def recall(tenant_id: Any) -> dict[str, Any] | None:
    """``{reported_at, items}`` (oldest-waiting first), or None when CORE has not reported lately or Redis cannot be read."""
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
    items = sorted(body.get("items", []), key=lambda i: i.get("days_left", 0))
    return {"reported_at": body.get("reported_at"), "items": items}

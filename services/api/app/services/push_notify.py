"""Sending web push to the browsers an organization subscribed (roadmap r7-af-39): the key, the sending, and which alerts are new. The crypto is in ``web_push``."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import delete, select

from app.models.push import PushKey, PushSubscription
from app.security.credential_vault import get_vault
from app.services import web_push as wp

logger = structlog.get_logger()

SUBJECT = "mailto:alerts@liveoakit.com"
MAX_ALERTS_PER_PASS = 10

Sender = Callable[[str, str, str, bytes, str, str], Awaitable[int]]


async def ensure_key(db: Any, tenant: uuid.UUID) -> PushKey:
    """The organization's VAPID key, made the first time it is asked for. The caller commits."""
    row = (await db.execute(select(PushKey).where(PushKey.tenant_id == tenant))).scalar_one_or_none()
    if row is None:
        private, public = wp.generate_vapid()
        row = PushKey(tenant_id=tenant, public_key=public, private_key_enc=get_vault().encrypt(private))
        db.add(row)
        await db.flush()
    return row


async def send_to_tenant(db: Any, tenant: uuid.UUID, payload: bytes, sender: Sender) -> dict[str, int]:
    """One message to every browser subscribed under ``tenant``. A subscription the push service says is gone is deleted. Returns how many were sent, dropped and failed. The caller commits."""
    key = (await db.execute(select(PushKey).where(PushKey.tenant_id == tenant))).scalar_one_or_none()
    subs = (await db.execute(select(PushSubscription).where(PushSubscription.tenant_id == tenant))).scalars().all()
    out = {"sent": 0, "dropped": 0, "failed": 0}
    if key is None or not subs:
        return out
    private = get_vault().decrypt(key.private_key_enc)
    for sub in subs:
        try:
            status = await sender(sub.endpoint, sub.p256dh, sub.auth, payload, private, key.public_key)
        except Exception as exc:  # noqa: BLE001 - one bad browser must not stop the others
            logger.warning("push.send_error", error=type(exc).__name__)
            out["failed"] += 1
            continue
        if wp.should_drop(status):
            await db.execute(delete(PushSubscription).where(PushSubscription.id == sub.id))
            out["dropped"] += 1
        elif 200 <= status < 300:
            out["sent"] += 1
        else:
            out["failed"] += 1
    return out


def new_critical(rows: list[dict[str, Any]], since: datetime) -> tuple[list[dict[str, Any]], datetime | None]:
    """The critical alerts created after ``since``, oldest first, and the time to remember as looked-at (pure). Each row has ``severity``, ``created_at``, ``title`` and ``client``."""
    fresh = sorted((r for r in rows if str(r.get("severity") or "").lower() == "critical" and r["created_at"] > since), key=lambda r: r["created_at"])
    return fresh, (fresh[-1]["created_at"] if fresh else None)


def messages_for(fresh: list[dict[str, Any]]) -> list[bytes]:
    """The pushes for these alerts: one each up to ``MAX_ALERTS_PER_PASS``, then one saying how many more (pure)."""
    shown = fresh[:MAX_ALERTS_PER_PASS]
    out = [wp.alert_message(str(r.get("client") or ""), str(r.get("title") or ""), "critical") for r in shown]
    if len(fresh) > len(shown):
        out.append(wp.alert_message("several clients", f"{len(fresh) - len(shown)} more critical alerts", "critical"))
    return out

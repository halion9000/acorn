"""Pushes each new critical alert to the browsers that turned notifications on (roadmap r7-af-39). Every minute, for each organization that has a push key: the critical alerts of its clients (and its own)
created since the last look are sent, once, and the time looked up to is remembered. A failure for one organization never stops the others, and a browser the push service has forgotten is dropped.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import structlog
from sqlalchemy import select

from app.core.config import settings as default_settings
from app.db.rls_scope import cross_tenant_reads
from app.db.rls_sessions import platform_session, tenant_session
from app.models.alert import Alert
from app.models.push import PushKey, PushSubscription
from app.models.tenant import Tenant
from app.services import push_notify as pn
from app.services import web_push as wp
from app.services import worker_heartbeat

logger = structlog.get_logger()


async def push_once(*, factory: Callable[[], Any] | None = None, client: Any = None) -> dict[str, int]:
    """One pass. Returns how many alerts were pushed and how many organizations raised an error."""
    async with platform_session(factory=factory) as s:
        owners = [r for r in (await s.execute(select(PushKey.tenant_id).where(PushKey.tenant_id.in_(select(PushSubscription.tenant_id))))).scalars().all()]
    own_client = client is None
    http = client or httpx.AsyncClient()
    pushed = failed = 0

    async def sender(endpoint: str, p256dh: str, auth: str, payload: bytes, private: str, public: str) -> int:
        return await wp.send(http, endpoint, p256dh, auth, payload, private, public, pn.SUBJECT)

    try:
        for owner in owners:
            try:
                async with tenant_session(owner, factory=factory) as s:
                    key = (await s.execute(select(PushKey).where(PushKey.tenant_id == owner))).scalar_one()
                    names = {r.id: r.name for r in (await s.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == owner))).all()}
                    since = key.last_alert_at
                    async with cross_tenant_reads(s):
                        rows = (
                            await s.execute(
                                select(Alert.tenant_id, Alert.severity, Alert.title, Alert.created_at).where(
                                    Alert.tenant_id.in_([owner, *names]), Alert.severity == "critical", Alert.created_at > since
                                )
                            )
                        ).all()
                    fresh, upto = pn.new_critical([{"client": names.get(r[0]) or "", "severity": r[1], "title": r[2], "created_at": r[3]} for r in rows], since)
                    for payload in pn.messages_for(fresh):
                        await pn.send_to_tenant(s, owner, payload, sender)
                        pushed += 1
                    if upto is not None:
                        key.last_alert_at = upto
                    await s.commit()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning("push_alerts.error", error=type(exc).__name__)
    finally:
        if own_client:
            await http.aclose()
    return {"pushed": pushed, "failed": failed}


async def run_push_alerts(
    *, sleep: Callable[[float], Any] = asyncio.sleep, settings: Any = default_settings, factory: Callable[[], Any] | None = None
) -> None:
    """The long-running loop (started under the scheduler lock from the API lifespan)."""
    interval = max(30, settings.PUSH_ALERTS_INTERVAL_SECONDS)
    worker_heartbeat.expect("push_alerts", interval, first_turn_after_seconds=60)
    await sleep(60)
    while True:
        try:
            result = await push_once(factory=factory)
            if any(result.values()):
                logger.info("push_alerts.pass", **result)
            worker_heartbeat.beat("push_alerts")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("push_alerts.loop_error", error=type(exc).__name__)
            worker_heartbeat.beat("push_alerts", error=type(exc).__name__)
        await sleep(interval)


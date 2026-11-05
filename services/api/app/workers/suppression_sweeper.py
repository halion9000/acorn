"""Keeps "hide this alert type" rules true as alerts keep arriving: every minute it hides new alerts an active rule covers and lifts the rules that have run out (their alerts come back)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import structlog

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.rls_sessions import mark_platform
from app.services import worker_heartbeat
from app.services.alert_stale import exempt_severities, exempt_tenant_ids, sweep_stale
from app.services.alert_suppression import sweep
from app.services.alert_ticket_rules import sweep_ticket_rules

logger = structlog.get_logger()

INTERVAL_SECONDS = 60
# Setting alerts aside as stale needs no more than an hourly look.
STALE_EVERY_SECONDS = 3600


async def run_suppression_sweeper(
    *, sleep: Callable[[float], Any] = asyncio.sleep, session_factory: Callable[[], Any] = AsyncSessionLocal
) -> None:
    """The long-running loop (started under the scheduler lock from the API lifespan). A failed pass never ends it; cancellation does."""
    worker_heartbeat.expect("alert_suppression", INTERVAL_SECONDS, first_turn_after_seconds=20)
    await sleep(20)
    since_stale = STALE_EVERY_SECONDS  # the first pass checks at once
    while True:
        try:
            async with session_factory() as session:
                mark_platform(session)  # the rules cover the owner's clients, so the pass reads across tenants
                done = await sweep(session)
                if done["hidden"] or done["expired"]:
                    logger.info("alert_suppression.sweep", **done)
                queued = await sweep_ticket_rules(session)
                await session.commit()
                if queued:
                    logger.info("alert_ticket_rules.queued", queued=queued)
            if since_stale >= STALE_EVERY_SECONDS:
                since_stale = 0
                async with session_factory() as session:
                    mark_platform(session)
                    n = await sweep_stale(session, settings.ALERT_STALE_DAYS, exempt_severities(settings.ALERT_STALE_EXEMPT_SEVERITIES), skip_tenants=await exempt_tenant_ids(session))
                    await session.commit()
                    if n:
                        logger.info("alert_stale.swept", set_aside=n)
            worker_heartbeat.beat("alert_suppression")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("alert_suppression.sweeper_error", error=str(exc))
            worker_heartbeat.beat("alert_suppression", error=type(exc).__name__)
        await sleep(INTERVAL_SECONDS)
        since_stale += INTERVAL_SECONDS

"""Sends the weekly compliance notice (Compliance, Notices) to the organizations and clients that switched it on.

Hourly it looks at every notice that is switched on and is due (never sent, or last sent a week or more ago) and sends it: an e-mail to the saved people and the same list to the saved web address. Nothing is sent when no action
item is waiting, and a notice only counts as sent when an e-mail or the web address took it, so a failure is tried again the next hour. At most MAX_PER_PASS notices go in one pass; the rest follow. A failure for one never stops the others.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select

from app.core.config import settings as default_settings
from app.db.rls_sessions import platform_session, tenant_session
from app.models.governance import ComplianceNotice
from app.services import compliance_notice as cn
from app.services import worker_heartbeat
from app.services.alert_email.graph import GraphMailer
from app.services.compliance_notice_sender import send_notice

logger = structlog.get_logger()
MAX_PER_PASS = 50


async def _due(now: datetime, factory: Callable[[], Any] | None) -> list[uuid.UUID]:
    async with platform_session(factory=factory) as s:
        rows = (await s.execute(select(ComplianceNotice).where(ComplianceNotice.weekly.is_(True)).limit(5000))).scalars().all()
        return [r.tenant_id for r in rows if cn.due(r.weekly, r.last_sent_at, now)]


async def notify_once(*, now: datetime | None = None, factory: Callable[[], Any] | None = None, mailer: GraphMailer | None = None, post: Any = None) -> dict[str, int]:
    """One pass. Returns how many notices went, how many had nothing waiting or failed."""
    now = now or datetime.now(UTC)
    sent = failed = idle = 0
    for tenant in (await _due(now, factory))[:MAX_PER_PASS]:
        try:
            async with tenant_session(tenant, factory=factory) as s:
                row = (await s.execute(select(ComplianceNotice).where(ComplianceNotice.tenant_id == tenant))).scalar_one_or_none()
                if row is None:
                    continue
                out = await send_notice(s, row, now=now, mailer=mailer, post=post)
                await s.commit()
            if out["sent"]:
                sent += 1
            elif out["items"] == 0:
                idle += 1
            else:
                failed += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning("compliance_notice.error", error=type(exc).__name__)
    return {"sent": sent, "failed": failed, "idle": idle}


async def run_compliance_notices(
    *, sleep: Callable[[float], Any] = asyncio.sleep, settings: Any = default_settings, factory: Callable[[], Any] | None = None
) -> None:
    """The long-running loop (started under the scheduler lock from the API lifespan)."""
    interval = max(300, settings.COMPLIANCE_NOTICE_INTERVAL_SECONDS)
    worker_heartbeat.expect("compliance_notices", interval, first_turn_after_seconds=max(0, settings.COMPLIANCE_NOTICE_INITIAL_DELAY_SECONDS))
    await sleep(max(0, settings.COMPLIANCE_NOTICE_INITIAL_DELAY_SECONDS))
    while True:
        try:
            result = await notify_once(factory=factory)
            if any(result.values()):
                logger.info("compliance_notice.pass", **result)
            worker_heartbeat.beat("compliance_notices")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("compliance_notice.loop_error", error=type(exc).__name__)
            worker_heartbeat.beat("compliance_notices", error=type(exc).__name__)
        await sleep(interval)

"""Sends the scheduled reports (Reports > Executive digest > Scheduled reports). Hourly it looks at every schedule that is switched on and is due, works the report out for its organization or client and e-mails it.

A report with nothing to say is not sent, and the schedule records that. A send that fails is tried again the next hour (the schedule is only marked as run when the mail went, or when there was nothing to
send). At most MAX_PER_PASS go in one pass; a failure for one never stops the others.
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
from app.models.report_schedule import ReportSchedule
from app.services import report_scheduler as rs
from app.services import worker_heartbeat
from app.services.alert_email.graph import GraphMailer, MailError

logger = structlog.get_logger()
MAX_PER_PASS = 50


async def send_schedule(db: Any, row: ReportSchedule, *, now: datetime, mailer: GraphMailer | None = None) -> str:
    """Work out and send one schedule's report, record how it went on the row (the caller commits) and return the result text."""
    try:
        made = await rs.render(row.report_kind, db, row.tenant_id, now)
    except KeyError:
        row.last_result = "That kind of report no longer exists."
        return row.last_result
    if made is None:
        row.last_run_at = now
        row.last_result = "Nothing to report, so nothing was sent."
        return row.last_result
    emails = rs.clean_emails(list(row.emails or []))
    if not emails:
        row.last_result = "No recipient is set."
        return row.last_result
    mailer = mailer or GraphMailer.from_settings()
    if not mailer.configured:
        row.last_result = "The mail credentials are not set."
        return row.last_result
    subject, text = made
    try:
        await mailer.send(emails, f"{row.name}: {subject}", text)
    except MailError as exc:
        row.last_result = f"The mail failed ({'permanent' if exc.permanent else 'will retry'})."
        return row.last_result
    row.last_run_at = now
    row.last_result = f"Sent to {len(emails)}."
    return row.last_result


async def _due(now: datetime, factory: Callable[[], Any] | None) -> list[tuple[uuid.UUID, uuid.UUID]]:
    async with platform_session(factory=factory) as s:
        rows = (await s.execute(select(ReportSchedule).where(ReportSchedule.enabled.is_(True)).limit(5000))).scalars().all()
        return [(r.tenant_id, r.id) for r in rows if rs.due(r.frequency, r.day, r.hour_utc, r.last_run_at, now)]


async def send_once(*, now: datetime | None = None, factory: Callable[[], Any] | None = None, mailer: GraphMailer | None = None) -> dict[str, int]:
    """One pass. Returns how many schedules were looked at and how many raised an error."""
    now = now or datetime.now(UTC)
    done = failed = 0
    for tenant, schedule_id in (await _due(now, factory))[:MAX_PER_PASS]:
        try:
            async with tenant_session(tenant, factory=factory) as s:
                row = (await s.execute(select(ReportSchedule).where(ReportSchedule.id == schedule_id))).scalar_one_or_none()
                if row is None:
                    continue
                await send_schedule(s, row, now=now, mailer=mailer)
                await s.commit()
            done += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning("report_schedules.error", error=type(exc).__name__)
    return {"handled": done, "failed": failed}


async def run_report_schedules(
    *, sleep: Callable[[float], Any] = asyncio.sleep, settings: Any = default_settings, factory: Callable[[], Any] | None = None
) -> None:
    """The long-running loop (started under the scheduler lock from the API lifespan)."""
    interval = max(300, settings.REPORT_SCHEDULES_INTERVAL_SECONDS)
    worker_heartbeat.expect("report_schedules", interval, first_turn_after_seconds=max(0, settings.REPORT_SCHEDULES_INITIAL_DELAY_SECONDS))
    await sleep(max(0, settings.REPORT_SCHEDULES_INITIAL_DELAY_SECONDS))
    while True:
        try:
            result = await send_once(factory=factory)
            if any(result.values()):
                logger.info("report_schedules.pass", **result)
            worker_heartbeat.beat("report_schedules")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("report_schedules.loop_error", error=type(exc).__name__)
            worker_heartbeat.beat("report_schedules", error=type(exc).__name__)
        await sleep(interval)

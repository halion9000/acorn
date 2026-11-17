"""Starts the access reviews that are due (Access Reviews, Repeat).

Once an hour it looks for enabled schedules whose next start day has come and, for each, takes a fresh snapshot of the system's people and opens a review (named "Q4 2026 access review: Microsoft 365", due 30 days
later, with the schedule's reviewer). The next start is counted from the day it actually started. A system with nobody to review starts nothing: the schedule keeps its day, says why in last_error and tries again
the next hour. One schedule failing never stops the others, and a failure never ends the loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import structlog
from sqlalchemy import select

from app.core.config import settings as default_settings
from app.db.rls_sessions import platform_session, tenant_session
from app.models.access_review import AccessReviewSchedule
from app.services import access_review_schedule as rules
from app.services import worker_heartbeat
from app.services.access_review_start import create_review, snapshot_lines

logger = structlog.get_logger()


async def start_due(today: date, *, factory: Callable[[], Any] | None = None) -> dict[str, int]:
    """Start every review that is due on ``today``. Returns how many were started, how many had nobody to review, and how many failed."""
    out = {"started": 0, "empty": 0, "failed": 0}
    async with platform_session(factory=factory) as s:
        due = [
            (r.id, r.tenant_id)
            for r in (
                await s.execute(
                    select(AccessReviewSchedule).where(AccessReviewSchedule.enabled.is_(True), AccessReviewSchedule.next_start <= today)
                )
            ).scalars()
        ]
    for schedule_id, tenant in due:
        try:
            async with tenant_session(tenant, factory=factory) as s:
                row = (
                    await s.execute(
                        select(AccessReviewSchedule).where(AccessReviewSchedule.id == schedule_id, AccessReviewSchedule.tenant_id == tenant)
                    )
                ).scalar_one_or_none()
                if row is None or not rules.is_due(row.next_start, row.enabled, today):
                    continue
                lines = await snapshot_lines(s, tenant, row.system)
                if not lines:
                    row.last_error = f"There are no people to review for {row.system}."
                    out["empty"] += 1
                else:
                    review = await create_review(
                        s,
                        tenant,
                        name=rules.review_name(row.system, today),
                        system=row.system,
                        reviewer=row.reviewer,
                        due_date=rules.due_date_for(today),
                        created_by="scheduled",
                        lines=lines,
                    )
                    row.last_review_id = review.id
                    row.last_error = None
                    row.next_start = rules.next_start_after(today, row.every_days)
                    out["started"] += 1
                await s.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            out["failed"] += 1
            logger.warning("access_review_scheduler.schedule_failed", error=type(exc).__name__)
    return out


async def run_access_review_scheduler(
    *, sleep: Callable[[float], Any] = asyncio.sleep, settings: Any = default_settings, factory: Callable[[], Any] | None = None
) -> None:
    """The long-running loop (started under the scheduler lock from the API lifespan)."""
    interval = max(60, settings.ACCESS_REVIEW_SCHEDULER_INTERVAL_SECONDS)
    worker_heartbeat.expect(
        "access_review_scheduler", interval, first_turn_after_seconds=max(0, settings.ACCESS_REVIEW_SCHEDULER_INITIAL_DELAY_SECONDS)
    )
    await sleep(max(0, settings.ACCESS_REVIEW_SCHEDULER_INITIAL_DELAY_SECONDS))
    while True:
        try:
            result = await start_due(datetime.now(UTC).date(), factory=factory)
            if result["started"] or result["empty"] or result["failed"]:
                logger.info("access_review_scheduler.pass", **result)
            worker_heartbeat.beat("access_review_scheduler")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("access_review_scheduler.error", error=type(exc).__name__)
            worker_heartbeat.beat("access_review_scheduler", error=type(exc).__name__)
        await sleep(interval)

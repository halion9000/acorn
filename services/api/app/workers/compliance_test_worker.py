"""Records the automated control tests every night for the organizations and clients that switched it on (Compliance, Automated tests).

Hourly it looks at every schedule that is switched on and is due (never run, or last run 20 hours ago or more) and does what Record now does: works out the tests from the client's checks and writes the results as evidence for the
controls of the frameworks that are on. A run that fails is tried again the next hour; at most MAX_PER_PASS go in one pass; a failure for one never stops the others.
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
from app.models.governance import ComplianceTestSchedule
from app.services import compliance_tests as engine
from app.services import worker_heartbeat

logger = structlog.get_logger()
MAX_PER_PASS = 50


async def _due(now: datetime, factory: Callable[[], Any] | None) -> list[uuid.UUID]:
    async with platform_session(factory=factory) as s:
        rows = (await s.execute(select(ComplianceTestSchedule).where(ComplianceTestSchedule.nightly.is_(True)).limit(5000))).scalars().all()
        return [r.tenant_id for r in rows if engine.nightly_due(r.nightly, r.last_run_at, now)]


async def record_once(*, now: datetime | None = None, factory: Callable[[], Any] | None = None) -> dict[str, int]:
    """One pass. Returns how many schedules recorded and how many failed."""
    from app.api.v1.endpoints.compliance_tests import _checks, _disabled, _enabled  # late: the endpoint module is large

    now = now or datetime.now(UTC)
    done = failed = 0
    for tenant in (await _due(now, factory))[:MAX_PER_PASS]:
        try:
            async with tenant_session(tenant, factory=factory) as s:
                row = (await s.execute(select(ComplianceTestSchedule).where(ComplianceTestSchedule.tenant_id == tenant))).scalar_one_or_none()
                if row is None:
                    continue
                checks = await _checks(s, tenant)
                enabled = await _enabled(s, tenant)
                results = engine.evaluate_all(checks, await _disabled(s, tenant))
                out = await engine.record(s, tenant, engine.evidence_rows(results, set(enabled)), now)
                row.last_run_at = now
                row.last_result = f"Recorded {out['written']} result{'' if out['written'] == 1 else 's'} for the frameworks that are on, replacing {out['replaced']}."
                await s.commit()
            done += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning("compliance_tests.nightly_error", error=type(exc).__name__)
    return {"recorded": done, "failed": failed}


async def run_compliance_tests(
    *, sleep: Callable[[float], Any] = asyncio.sleep, settings: Any = default_settings, factory: Callable[[], Any] | None = None
) -> None:
    """The long-running loop (started under the scheduler lock from the API lifespan)."""
    interval = max(300, settings.COMPLIANCE_TESTS_INTERVAL_SECONDS)
    worker_heartbeat.expect("compliance_tests", interval, first_turn_after_seconds=max(0, settings.COMPLIANCE_TESTS_INITIAL_DELAY_SECONDS))
    await sleep(max(0, settings.COMPLIANCE_TESTS_INITIAL_DELAY_SECONDS))
    while True:
        try:
            result = await record_once(factory=factory)
            if any(result.values()):
                logger.info("compliance_tests.pass", **result)
            worker_heartbeat.beat("compliance_tests")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("compliance_tests.loop_error", error=type(exc).__name__)
            worker_heartbeat.beat("compliance_tests", error=type(exc).__name__)
        await sleep(interval)

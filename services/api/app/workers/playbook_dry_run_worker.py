"""The loop that records playbook dry runs (see ``app.services.playbook_dry_runs``): every minute, for the clients the MSSP ticked. Takes no action on any alert."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import structlog

from app.db.database import AsyncSessionLocal
from app.services import playbook_dry_runs

logger = structlog.get_logger()

INTERVAL_SECONDS = 60


async def run_playbook_dry_runs(
    *, sleep: Callable[[float], Any] = asyncio.sleep, session_factory: Callable[[], Any] = AsyncSessionLocal
) -> None:
    """The long-running loop (started under the scheduler lock from the API lifespan). A failed pass never ends it; cancellation does."""
    await sleep(30)
    while True:
        try:
            done = await playbook_dry_runs.run_once(session_factory)
            if done["recorded"] or done["skipped"] or done["pruned"]:
                logger.info("playbook_dry_runs.pass", **done)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("playbook_dry_runs.error", error=str(exc))
        await sleep(INTERVAL_SECONDS)

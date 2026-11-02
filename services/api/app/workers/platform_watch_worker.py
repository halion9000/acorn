"""Runs the platform's self-check on a timer and emails the platform administrators about CHANGES (see app/services/platform_watch.py for what is checked).

It reuses the alert-email setup: the recipients are the ones a platform administrator already entered for alert emails, and the mail goes out through the same Microsoft Graph sender. With no recipients or no Graph credentials it still logs every change at WARNING (``platform_watch.change``), so the problem is
in the server log even when nobody is mailed. A failed send keeps the change pending and tries again next cycle, so a mail outage does not swallow the news.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.rls_sessions import mark_platform
from app.models.connector import Connector
from app.models.tenant import Tenant
from app.services.alert_email.graph import GraphMailer, MailError
from app.services.alert_email.settings_store import get_settings
from app.services.llm_health import llm_status
from app.services.platform_watch import ConnectorSeen, Finding, changes, compose, evaluate

logger = structlog.get_logger()

INTERVAL_SECONDS = 300


def disk_free_percent(path: str = "/") -> float | None:
    try:
        usage = shutil.disk_usage(path)
        return usage.free * 100.0 / usage.total if usage.total else None
    except OSError:
        return None


def memory_available_percent(meminfo: str = "/proc/meminfo") -> float | None:
    """MemAvailable over MemTotal. Inside a container this shows the host's memory, which is the number that matters. None where there is no /proc (a developer laptop)."""
    try:
        values: dict[str, int] = {}
        with open(meminfo, encoding="utf-8") as fh:
            for line in fh:
                name, _, rest = line.partition(":")
                if name in ("MemTotal", "MemAvailable"):
                    values[name] = int(rest.split()[0])
        return values["MemAvailable"] * 100.0 / values["MemTotal"]
    except (OSError, KeyError, ValueError, IndexError, ZeroDivisionError):
        return None


async def measure(session_factory: Callable[[], Any], now: datetime) -> dict[str, Any]:
    async with session_factory() as db:
        mark_platform(db)  # one look across every client
        feed = (
            await db.execute(select(func.max(Connector.last_health_check), func.count()).where(Connector.connector_type == "core_feed"))
        ).first()
        rows = (
            await db.execute(
                select(Connector.name, Connector.last_event_at, Tenant.name)
                .join(Tenant, Tenant.id == Connector.tenant_id)
                .where(Connector.is_enabled.is_(True), Connector.connector_type != "core_feed", Connector.last_event_at.is_not(None))
            )
        ).all()
    return {
        "now": now,
        "core_feed_last_report": feed[0] if feed else None,
        "core_feed_sources": int(feed[1]) if feed and feed[1] else 0,
        "connectors": [ConnectorSeen(name=r[0], tenant_name=r[2], last_event_at=r[1]) for r in rows],
        "connector_silent_after": timedelta(hours=settings.PLATFORM_WATCH_CONNECTOR_SILENT_HOURS),
        "disk_free_percent": disk_free_percent(),
        "memory_available_percent": memory_available_percent(),
        "llm_failing": llm_status(now),
    }


class Watch:
    """Remembers the findings of the last look and what has still to be told."""

    def __init__(self) -> None:
        self.known: dict[str, Finding] = {}
        self.untold_new: list[Finding] = []
        self.untold_cleared: list[Finding] = []

    async def step(
        self,
        *,
        session_factory: Callable[[], Any] = AsyncSessionLocal,
        mailer: GraphMailer | None = None,
        now: datetime | None = None,
        measure_fn: Callable[..., Awaitable[dict[str, Any]]] = measure,
    ) -> dict[str, int]:
        now = now or datetime.now(UTC)
        current = evaluate(**await measure_fn(session_factory, now))
        new, cleared = changes(self.known, current)
        self.known = {f.key: f for f in current}
        self.untold_new = [f for f in self.untold_new if f.key in self.known] + [
            f for f in new if f.key not in {u.key for u in self.untold_new}
        ]
        self.untold_cleared = [f for f in self.untold_cleared if f.key not in self.known] + cleared
        for f in new:
            logger.warning("platform_watch.change", state="problem", key=f.key, severity=f.severity, message=f.message)
        for f in cleared:
            logger.warning("platform_watch.change", state="cleared", key=f.key, message=f.message)
        if self.untold_new or self.untold_cleared:
            if await self._tell(session_factory, mailer or GraphMailer.from_settings()):
                self.untold_new, self.untold_cleared = [], []
        return {"problems": len(current), "untold": len(self.untold_new) + len(self.untold_cleared)}

    async def _tell(self, session_factory: Callable[[], Any], mailer: GraphMailer) -> bool:
        async with session_factory() as db:
            recipients = [str(r) for r in (await get_settings(db)).recipients or []]
        if not recipients or not mailer.configured:
            # Nobody to mail: the log line above is the record. Count it as told so it is not retried forever.
            return True
        subject, body = compose(
            self.untold_new, self.untold_cleared, server_name=os.environ.get("AISOC_SERVER_NAME") or socket.gethostname()
        )
        try:
            await mailer.send(recipients, subject, body)
        except MailError as exc:
            logger.warning("platform_watch.mail_failed", permanent=exc.permanent)
            return False
        return True


async def run_platform_watch(*, sleep: Callable[[float], Any] = asyncio.sleep) -> None:
    """The long-running loop (started under the scheduler lock from the API lifespan). A failed cycle never ends it; cancellation does."""
    await sleep(60)
    watch = Watch()
    while True:
        try:
            await watch.step()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001  # the watcher must outlive a bad cycle
            logger.exception("platform_watch.cycle_failed")
        await sleep(INTERVAL_SECONDS)

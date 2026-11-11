"""Reads the shared DMARC mailbox on a timer and stores the reports it finds (see app/services/dmarc_mailbox.py).

Off until the mailbox is set up: it needs DMARC_MAILBOX (the shared mailbox that receives every client's reports), DMARC_OWNER_TENANT_ID (the managing tenant the reports belong to) and a Microsoft
app with the Mail.Read application permission limited to that one mailbox (DMARC_GRAPH_*, or the alert-e-mail app ALERT_EMAIL_GRAPH_* as a fallback). A failed pass never ends the loop; the reason is kept for the page.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

import structlog

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.services import worker_heartbeat
from app.services.dmarc_alerts import run_pass_rate_detection
from app.services.dmarc_mailbox import GraphMailboxReader, ingest_once
from app.services.dmarc_store import store_report, store_tls_policy
from app.services.domain_expiry import run_expiry_check

logger = structlog.get_logger()


def make_reader() -> GraphMailboxReader:
    """The reader's own app (DMARC_GRAPH_*) when all three are set, otherwise the alert-e-mail app (ALERT_EMAIL_GRAPH_*)."""
    own = (settings.DMARC_GRAPH_TENANT_ID, settings.DMARC_GRAPH_CLIENT_ID, settings.DMARC_GRAPH_CLIENT_SECRET)
    tenant_id, client_id, client_secret = (
        own
        if all(own)
        else (settings.ALERT_EMAIL_GRAPH_TENANT_ID, settings.ALERT_EMAIL_GRAPH_CLIENT_ID, settings.ALERT_EMAIL_GRAPH_CLIENT_SECRET)
    )
    return GraphMailboxReader(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        sender=settings.DMARC_MAILBOX,
        base_url=settings.ALERT_EMAIL_GRAPH_BASE_URL,
        authority=settings.ALERT_EMAIL_AUTHORITY,
    )


async def raise_alerts() -> int:
    """After reports were stored: alert on any client whose pass rate fell. Its own session and its own failure handling, so it can never fail the read of the mailbox."""
    from app.db.rls_sessions import mark_platform

    try:
        async with AsyncSessionLocal() as db:
            mark_platform(db)
            made = await run_pass_rate_detection(db)
            await db.commit()
            return made
    except Exception:  # noqa: BLE001
        logger.warning("dmarc_ingest.alerts_failed", exc_info=True)
        return 0


async def check_expiry() -> tuple[int, int]:
    """Look up the registration end of client domains that are due and alert on those ending soon. Its own session and failure handling, like ``raise_alerts``."""
    from app.db.rls_sessions import mark_platform
    from app.services import safe_fetch

    async def fetch(url: str) -> bytes:
        return await safe_fetch.fetch(url, max_bytes=500_000, max_redirects=3, accept="application/rdap+json, application/json")

    try:
        async with AsyncSessionLocal() as db:
            mark_platform(db)
            done = await run_expiry_check(db, fetch)
            await db.commit()
            return done
    except Exception:  # noqa: BLE001
        logger.warning("dmarc_ingest.expiry_failed", exc_info=True)
        return 0, 0


def owner_id() -> uuid.UUID | None:
    try:
        return uuid.UUID(settings.DMARC_OWNER_TENANT_ID.strip())
    except ValueError:
        return None


async def run_dmarc_ingest(*, sleep: Callable[[float], Any] = asyncio.sleep) -> None:
    worker_heartbeat.expect("dmarc_ingest", max(300, settings.DMARC_INTERVAL_SECONDS), first_turn_after_seconds=120)
    await sleep(120)
    while True:
        try:
            owner, reader = owner_id(), make_reader()
            if owner is None or not reader.configured:
                logger.info("dmarc_ingest.not_set_up")
                worker_heartbeat.beat("dmarc_ingest")  # not being set up is not a fault: the worker is alive and has nothing to read
            else:
                result = await ingest_once(AsyncSessionLocal, reader, owner, store=store_report, store_tls=store_tls_policy)
                logger.info(
                    "dmarc_ingest.pass",
                    stored=result.stored,
                    tls_stored=result.tls_stored,
                    duplicates=result.duplicates,
                    rejected=result.rejected,
                    messages=result.messages,
                    error=result.error,
                )
                if result.stored:
                    await raise_alerts()
                await check_expiry()
                worker_heartbeat.beat("dmarc_ingest", error="mailbox_read_failed" if result.error else None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001  # the reader must outlive a bad pass
            logger.exception("dmarc_ingest.pass_failed")
            worker_heartbeat.beat("dmarc_ingest", error=type(exc).__name__)
        await sleep(max(300, settings.DMARC_INTERVAL_SECONDS))

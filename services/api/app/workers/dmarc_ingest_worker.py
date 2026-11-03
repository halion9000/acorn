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
from app.services.dmarc_mailbox import GraphMailboxReader, ingest_once
from app.services.dmarc_store import store_report, store_tls_policy

logger = structlog.get_logger()


def make_reader() -> GraphMailboxReader:
    """The reader's own app (DMARC_GRAPH_*) when all three are set, otherwise the alert-e-mail app (ALERT_EMAIL_GRAPH_*)."""
    own = (settings.DMARC_GRAPH_TENANT_ID, settings.DMARC_GRAPH_CLIENT_ID, settings.DMARC_GRAPH_CLIENT_SECRET)
    tenant_id, client_id, client_secret = own if all(own) else (settings.ALERT_EMAIL_GRAPH_TENANT_ID, settings.ALERT_EMAIL_GRAPH_CLIENT_ID, settings.ALERT_EMAIL_GRAPH_CLIENT_SECRET)
    return GraphMailboxReader(
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        sender=settings.DMARC_MAILBOX,
        base_url=settings.ALERT_EMAIL_GRAPH_BASE_URL,
        authority=settings.ALERT_EMAIL_AUTHORITY,
    )


def owner_id() -> uuid.UUID | None:
    try:
        return uuid.UUID(settings.DMARC_OWNER_TENANT_ID.strip())
    except ValueError:
        return None


async def run_dmarc_ingest(*, sleep: Callable[[float], Any] = asyncio.sleep) -> None:
    await sleep(120)
    while True:
        try:
            owner, reader = owner_id(), make_reader()
            if owner is None or not reader.configured:
                logger.info("dmarc_ingest.not_set_up")
            else:
                result = await ingest_once(AsyncSessionLocal, reader, owner, store=store_report, store_tls=store_tls_policy)
                logger.info("dmarc_ingest.pass", stored=result.stored, tls_stored=result.tls_stored, duplicates=result.duplicates, rejected=result.rejected, messages=result.messages, error=result.error)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001  # the reader must outlive a bad pass
            logger.exception("dmarc_ingest.pass_failed")
        await sleep(max(300, settings.DMARC_INTERVAL_SECONDS))

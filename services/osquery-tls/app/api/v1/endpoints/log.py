"""POST /api/v1/osquery/log — osquery TLS log endpoint.

osqueryd POSTs result and status logs here.  We normalise each row and
forward the batch to services/ingest.

Reference:
  https://osquery.readthedocs.io/en/stable/deployment/remote/#log-string
"""

from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_valid_node_key
from app.db.session import get_db
from app.models.node import OsqueryNode
from app.services.fim_rows import fim_event_from
from app.services.log_forwarder import forward_events
from app.services.node_registry import mark_seen
from app.services.normalizer import normalize_row

logger = logging.getLogger(__name__)
router = APIRouter()


class LogRequest(BaseModel):
    node_key: str
    log_type: str  # "result" | "snapshot" | "status"
    data: str  # JSON-encoded string (osquery sends it as a string)


@router.post("/log")
async def log(
    body: LogRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    node: Annotated[OsqueryNode, Depends(require_valid_node_key)],
) -> dict:
    await mark_seen(db, node)
    # Read once, now: after a failed save the node object is expired and touching it would raise.
    tenant_id, host_identifier = node.tenant_id, node.host_identifier

    events: list[dict] = []
    fim_rows: list = []
    try:
        payload = json.loads(body.data)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Received non-JSON log data from node %s", node.host_identifier)
        return {"node_invalid": False}

    # Only result and snapshot log types carry query rows worth forwarding.
    # Status logs are osqueryd daemon diagnostics; skip them.
    if body.log_type not in ("result", "snapshot"):
        await forward_events([], node.tenant_id)
        return {"node_invalid": False}

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = [payload]
    else:
        rows = []

    for entry in rows:
        query_name = entry.get("name", "unknown")
        raw_rows = entry.get("columns") or entry.get("snapshot") or [entry]
        if isinstance(raw_rows, dict):
            raw_rows = [raw_rows]
        for row in raw_rows:
            fim = fim_event_from(row, entry=entry, node_key=body.node_key, hostname=host_identifier, tenant_id=tenant_id)
            if fim is not None:
                fim_rows.append(fim)
            events.append(
                normalize_row(
                    row,
                    host_identifier=node.host_identifier,
                    tenant_id=node.tenant_id,
                    query_name=query_name,
                    log_type=body.log_type,
                )
            )

    if fim_rows:
        # What the /fim pages read. Never allowed to stop the events being forwarded: a failure here is logged and the batch carries on.
        try:
            db.add_all(fim_rows)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
            logger.warning("could not store %d file-integrity event(s) for node %s", len(fim_rows), host_identifier, exc_info=True)

    await forward_events(events, tenant_id)
    return {"node_invalid": False}

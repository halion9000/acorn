"""The HubSpot automations (Automation, HubSpot): asking CORE to run the Halo to HubSpot copy now instead of at its next ten-minute check.

The press leaves a request on the organization's settings (``sync_requests``); CORE collects it with its usual claim, about every 15 seconds, runs the copy once, and reports as it always does (the HubSpot page then
shows the result). Nothing here reaches HubSpot or HaloPSA.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import text

from app.api.v1.deps import AuthUser, DBSession, require_permission

router = APIRouter(prefix="/automation/hubspot", tags=["automation"])

# The name CORE knows this automation by in a sync request (CORE's sweep source for it).
HALO_HUBSPOT_VENDOR = "halo-hubspot"


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED, summary="Ask CORE to run the Halo to HubSpot copy now")
async def request_halo_hubspot_sync(
    current_user: Annotated[AuthUser, Depends(require_permission("connectors:write"))],
    db: DBSession,
) -> dict[str, Any]:
    """Leave a request for CORE to run the copy now. One atomic update of the settings, so it cannot overwrite another change made at the same moment."""
    now = datetime.now(UTC)
    await db.execute(
        text(
            """
            UPDATE tenants
            SET settings = jsonb_set(
                COALESCE(settings, '{}'::jsonb),
                '{sync_requests}',
                COALESCE(settings -> 'sync_requests', '{}'::jsonb) || jsonb_build_object(CAST(:vendor AS text), CAST(:at AS text)),
                true
            )
            WHERE id = :tenant
            """
        ).bindparams(vendor=HALO_HUBSPOT_VENDOR, at=now.isoformat(), tenant=current_user.tenant_id)
    )
    await db.commit()
    return {"requested_at": now.isoformat(), "vendor": HALO_HUBSPOT_VENDOR}

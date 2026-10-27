"""EASM (External Attack Surface Management) endpoints (Tier 3.6)."""

from __future__ import annotations

import ipaddress
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import ARRAY, Text, cast, func, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import CurrentUser, get_current_user, require_permission
from app.core.config import get_settings
from app.db.database import get_db
from app.db.rls_sessions import mark_tenant
from app.models.easm import ExternalAsset, ExternalAssetDrift, ExternalAssetType
from app.models.tenant import Tenant
from app.services.easm_discovery import run_discovery
from app.services.easm_drift import detect_drift

logger = logging.getLogger("aisoc.easm")

router = APIRouter(prefix="/easm", tags=["easm"])


MAX_IP_TARGETS = 64


class ScanRequest(BaseModel):
    # Defaults to the signed-in user's own tenant (the console does not need to know its tenant id); naming a different tenant is refused.
    tenant_id: UUID | None = None
    org_query: str | None = None
    # PUBLIC IP addresses only (an external attack surface scan): an internal address, a hostname or a CIDR would turn this into a port scanner of the API host's own network,
    # with the open ports then readable from /easm/assets.
    ip_targets: list[str] = Field(default_factory=list, max_length=MAX_IP_TARGETS)
    asset_type: ExternalAssetType | None = None

    @field_validator("ip_targets")
    @classmethod
    def _public_ips_only(cls, targets: list[str]) -> list[str]:
        for target in targets:
            try:
                ip = ipaddress.ip_address(target.strip())
            except ValueError as exc:
                raise ValueError(f"{target!r} is not an IP address (hostnames and CIDR ranges are not accepted)") from exc
            if not ip.is_global:
                raise ValueError(f"{target!r} is not a public IP address")
        return [t.strip() for t in targets]


async def _run_scan_job(
    tenant_id: UUID,
    org_query: str,
    ip_targets: list[str],
) -> None:
    """Background task that runs discovery + drift detection, and records how it went (``Tenant.settings['easm_last_scan']``) so the page can say, instead of leaving "Scan started" hanging."""
    from app.db.database import AsyncSessionLocal as async_session_factory

    started = datetime.now(UTC)
    summary: dict[str, Any] = {"started_at": started.isoformat(), "sources": scan_plan(get_settings(), ip_targets)["sources"], "found": 0, "changes": 0, "error": None}
    try:
        discovered = await run_discovery(org_query, ip_targets=ip_targets or None)
        async with async_session_factory() as db:
            mark_tenant(db, tenant_id)  # a background job for one tenant (step 4b)
            drift_records = await detect_drift(db, tenant_id, discovered)
            await db.commit()
            summary.update(found=len(discovered), changes=len(drift_records))
            logger.info(
                "EASM scan complete: tenant=%s discovered=%d drifts=%d",
                tenant_id,
                len(discovered),
                len(drift_records),
            )
    except Exception as exc:
        logger.exception("EASM scan failed for tenant=%s", tenant_id)
        summary["error"] = f"The scan failed ({type(exc).__name__}); the API log has the detail."
    summary["finished_at"] = datetime.now(UTC).isoformat()
    try:
        async with async_session_factory() as db:
            mark_tenant(db, tenant_id)
            await db.execute(
                update(Tenant)
                .where(Tenant.id == tenant_id)
                .values(settings=func.jsonb_set(func.coalesce(Tenant.settings, cast({}, JSONB)), cast(["easm_last_scan"], ARRAY(Text)), cast(json.dumps(summary), JSONB), True))
            )
            await db.commit()
    except Exception:
        logger.exception("EASM scan result could not be recorded for tenant=%s", tenant_id)


def scan_plan(s: Any, ip_targets: list[str]) -> dict[str, Any]:
    """What a scan could do with the current settings and the addresses entered: which sources would run, and, when none would, the one thing to change (pure; unit-tested)."""
    shodan = bool(s.AISOC_EASM_SHODAN_API_KEY)
    censys = bool(s.AISOC_EASM_CENSYS_API_ID and s.AISOC_EASM_CENSYS_API_SECRET)
    active_on = bool(s.AISOC_EASM_ACTIVE_SCAN_ENABLED)
    sources = [name for name, on in (("shodan", shodan), ("censys", censys), ("port check", active_on and bool(ip_targets))) if on]
    problem: str | None = None
    if not sources:
        if ip_targets and not active_on:
            problem = (
                "The port check is switched off on this server, so the addresses you entered would not be probed, and no Shodan or Censys key is set. "
                "Set AISOC_EASM_ACTIVE_SCAN_ENABLED=true (it probes only the public addresses you enter), or add a Shodan or Censys key, in the API's environment and restart it."
            )
        elif active_on:
            problem = "The port check is on, but no IP addresses were entered, and no Shodan or Censys key is set. Enter the public IP addresses to check."
        else:
            problem = (
                "Nothing is set up to discover with. Add a Shodan key (AISOC_EASM_SHODAN_API_KEY) or a Censys key (AISOC_EASM_CENSYS_API_ID and AISOC_EASM_CENSYS_API_SECRET), "
                "or turn on the port check (AISOC_EASM_ACTIVE_SCAN_ENABLED=true) and enter public IP addresses, in the API's environment, then restart it."
            )
    return {
        "shodan": shodan,
        "censys": censys,
        "port_check": active_on,
        "sources": sources,
        "can_run": bool(sources),
        "problem": problem,
    }


@router.get("/status", dependencies=[Depends(require_permission("alerts:read"))])
async def easm_status(db: AsyncSession = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    """Which discovery sources are set up on this server, and how this tenant's last scan went (found, changes, or the failure)."""
    tenant = await db.get(Tenant, current_user.tenant_id)
    last = (tenant.settings or {}).get("easm_last_scan") if tenant is not None else None
    return {"plan": scan_plan(get_settings(), []), "last_scan": last if isinstance(last, dict) else None}


@router.post("/scan", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_permission("settings:write"))])
async def trigger_easm_scan(
    body: ScanRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Trigger an EASM discovery scan for a tenant (Tier 3.6).

    Runs passive connectors (Shodan / Censys) and, when enabled, an active
    TCP connect probe.  Results are upserted into ``external_assets`` and
    drift events written to ``external_asset_drift``.
    """
    s = get_settings()
    if not s.AISOC_FEATURE_EASM:
        raise HTTPException(status_code=403, detail="EASM feature is disabled")

    if body.tenant_id is not None and body.tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot trigger EASM scan for a different tenant",
        )
    scan_tenant = current_user.tenant_id

    tenant = await db.get(Tenant, scan_tenant)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    org_query = body.org_query or tenant.name

    plan = scan_plan(s, body.ip_targets)
    if not plan["can_run"]:
        # Said plainly instead of "Scan started" followed by nothing: a scan with no source would finish at once with no assets.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=plan["problem"])

    background_tasks.add_task(
        _run_scan_job,
        scan_tenant,
        org_query,
        body.ip_targets,
    )

    return {
        "status": "accepted",
        "tenant_id": str(scan_tenant),
        "org_query": org_query,
        "sources": plan["sources"],
        "message": "EASM scan enqueued.",
    }


@router.get("/assets", dependencies=[Depends(require_permission("alerts:read"))])
async def list_external_assets(
    tenant_id: UUID | None = Query(None),
    asset_type: ExternalAssetType | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List externally discovered assets for a tenant.

    ``tenant_id`` defaults to the authenticated user's tenant, so the analyst
    console can hit ``/easm/assets`` without explicit tenant scoping. A user
    can never request another tenant's assets — supplying a foreign
    ``tenant_id`` returns 403.
    """
    if tenant_id is not None and tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot list EASM assets for a different tenant",
        )
    effective_tenant = current_user.tenant_id
    stmt = select(ExternalAsset).where(ExternalAsset.tenant_id == effective_tenant).order_by(ExternalAsset.last_seen.desc()).limit(limit)
    if asset_type:
        stmt = stmt.where(ExternalAsset.asset_type == asset_type)

    result = await db.execute(stmt)
    assets = result.scalars().all()
    return [
        {
            "id": str(a.id),
            "asset_type": a.asset_type.value,
            "value": a.value,
            "first_seen": a.first_seen.isoformat(),
            "last_seen": a.last_seen.isoformat(),
            "metadata": a.metadata_json,
        }
        for a in assets
    ]


@router.get("/drift", dependencies=[Depends(require_permission("alerts:read"))])
async def list_external_asset_drift(
    tenant_id: UUID | None = Query(None),
    external_asset_id: UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List drift events (new ports, certs, sub-domains, etc.).

    A user can never request another tenant's drift events — supplying a
    foreign ``tenant_id`` returns 403.
    """
    if tenant_id is not None and tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot list EASM drift for a different tenant",
        )
    effective_tenant = current_user.tenant_id
    stmt = (
        select(ExternalAssetDrift)
        .where(ExternalAssetDrift.tenant_id == effective_tenant)
        .order_by(ExternalAssetDrift.detected_at.desc())
        .limit(limit)
    )
    if external_asset_id:
        stmt = stmt.where(ExternalAssetDrift.external_asset_id == external_asset_id)

    result = await db.execute(stmt)
    drifts = result.scalars().all()
    return [
        {
            "id": str(d.id),
            "external_asset_id": str(d.external_asset_id),
            "drift_type": d.drift_type,
            "details": d.details,
            "detected_at": d.detected_at.isoformat(),
        }
        for d in drifts
    ]

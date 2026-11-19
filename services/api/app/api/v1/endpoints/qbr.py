"""The quarterly business review pack of one client (roadmap r7-af-31): the security and "what we did" sections, read with ``alerts:read``.

The tickets, hours and satisfaction sections are the metrics pages' own and are drawn beside these by the page. There is no finance information here (Hal, 2026-11-18). Nothing is changed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import _scope
from app.db.rls_scope import cross_tenant_reads
from app.models.alert import Alert
from app.models.case import Case
from app.models.client_vulnerability import ClientVulnerability
from app.models.device import Device
from app.services import qbr_pack as q

router = APIRouter(prefix="/reports/qbr", tags=["reports"])


@router.get("", summary="One client's quarterly business review: security and what we did over the last few months (no finance)")
async def qbr(
    user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    client_id: uuid.UUID,
    months: Annotated[int, Query(ge=1, le=12)] = 3,
) -> dict[str, Any]:
    scope, names = await _scope(db, user.tenant_id, client_id)
    if client_id not in scope or client_id not in names:
        raise HTTPException(status_code=404, detail="Client not found")
    now = datetime.now(UTC)
    since = q.period_start(now, months)
    finished = q.FINISHED
    async with cross_tenant_reads(db):
        alerts = (
            await db.execute(
                select(Alert.severity, Alert.status, Alert.created_at, Alert.resolved_at).where(
                    Alert.tenant_id == client_id, or_(Alert.created_at >= since, Alert.status.notin_(finished), Alert.resolved_at >= since)
                )
            )
        ).all()
        vulns = (await db.execute(select(ClientVulnerability.severity, ClientVulnerability.exploited).where(ClientVulnerability.tenant_id == client_id))).all()
        cases = (await db.execute(select(Case.created_at, Case.closed_at).where(Case.tenant_id == client_id, or_(Case.created_at >= since, Case.closed_at >= since)))).all()
        devices = (await db.execute(select(func.count()).select_from(Device).where(Device.tenant_id == client_id))).scalar_one()
    alert_rows = [{"severity": a[0], "status": a[1], "created_at": a[2], "resolved_at": a[3]} for a in alerts]
    security = q.security_section(alert_rows, [{"severity": v[0], "exploited": v[1]} for v in vulns], int(devices), since)
    work = q.work_section([{"created_at": c[0], "closed_at": c[1]} for c in cases], alert_rows, since)
    return {
        "client": names[client_id],
        "months": months,
        "from": since.date().isoformat(),
        "to": now.date().isoformat(),
        "highlights": q.highlights(security, work),
        "security": security,
        "work": work,
    }

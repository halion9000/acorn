"""NIST CSF 2.0 coverage for one client, from the checks the tools already report (read-only).

``GET /api/v1/nist-coverage/{client_id}``: every NIST control A.C.O.R.N holds with how the client stands today and the checks behind it, built by ``app.services.nist_coverage`` from the same posture numbers the
client page shows. A control no check bears on says "no automated evidence": it is never called met by default.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.client_posture import client_posture
from app.models.compliance import ComplianceControl
from app.models.tenant import Tenant
from app.services import nist_coverage as nc

router = APIRouter(prefix="/nist-coverage", tags=["compliance"])


@router.get("/{client_id}", summary="NIST CSF 2.0 controls with how one client stands, from live checks")
async def nist_for_client(client_id: uuid.UUID, user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> dict[str, Any]:
    owner = user.tenant_id
    if client_id != owner:
        found = (await db.execute(select(Tenant.id).where(Tenant.id == client_id, Tenant.parent_tenant_id == owner))).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=404, detail="Client not found")
    posture = await client_posture(client_id, user, db)
    controls = (await db.execute(select(ComplianceControl.control_id, ComplianceControl.category, ComplianceControl.title).where(ComplianceControl.framework == nc.FRAMEWORK).order_by(ComplianceControl.control_id))).all()
    data = posture.model_dump()
    out = nc.coverage([{"control_id": c, "category": cat, "title": t} for c, cat, t in controls], data.get("tool_checks") or {}, data.get("identity"))
    out["client_id"] = str(client_id)
    out["client_name"] = posture.client_name
    out["generated_at"] = posture.generated_at.isoformat()
    return out

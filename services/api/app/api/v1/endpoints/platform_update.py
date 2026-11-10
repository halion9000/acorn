"""Update A.C.O.R.N from its own screen (PLATFORM ADMINISTRATORS ONLY).

Every route requires `platform:cross_tenant_query`, written out on each route, which only the platform_admin role holds. The API does not run the update: it writes a request file and the VM's watcher runs the update script (see app/services/update_control.py and infra/azure/update-acorn.sh). Where that folder is not set up (a laptop install) the status says so and the button is not offered.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.services import update_control as uc
from app.services.audit import emit_audit

router = APIRouter(prefix="/platform/update", tags=["platform"])


class UpdateStatus(BaseModel):
    available: bool
    state: str
    requested_by: str | None = None
    requested_at: str | None = None
    last_run_at: str | None = None
    last_run_ok: bool | None = None
    summary: str | None = None
    log: list[str] = []
    history: list[dict] = []


def _out(state: uc.UpdateState) -> UpdateStatus:
    return UpdateStatus(**state.__dict__)


@router.get("", response_model=UpdateStatus)
async def get_update_status(current_user: Annotated[AuthUser, Depends(require_permission("platform:cross_tenant_query"))]) -> UpdateStatus:
    return _out(uc.read_state(uc.control_dir()))


@router.post("", response_model=UpdateStatus, status_code=status.HTTP_202_ACCEPTED)
async def request_update(
    current_user: Annotated[AuthUser, Depends(require_permission("platform:cross_tenant_query"))], db: DBSession
) -> UpdateStatus:
    directory = uc.control_dir()
    try:
        uc.request_update(directory, current_user.email or str(current_user.user_id))
    except uc.UpdateRefused as refused:
        raise HTTPException(status.HTTP_409_CONFLICT if refused.code == "busy" else status.HTTP_404_NOT_FOUND, detail=str(refused)) from refused
    await emit_audit(
        db=db,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
        action="platform:update_requested",
        resource="platform_update",
        resource_id="acorn",
        changes={},
    )
    return _out(uc.read_state(directory))

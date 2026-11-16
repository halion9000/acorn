"""The script log: every script A.C.O.R.N asked CORE to run on a machine, and what came of it.

A request is queued as a vendor action (vendor ``core``, action ``run_script``) by a person pressing Run script on an alert or the Devices page, or by an auto-run rule. CORE collects it, runs the script in
NinjaOne and reports the result. This lists those requests for the organization and its clients, newest first, so a script that never ran, or ran and failed, can be found without opening each alert.

States shown: ``done`` (CORE ran it), ``failed`` (CORE could not, or never reported back), ``expired`` (nobody collected it within 30 minutes: CORE was off or could not reach A.C.O.R.N), ``pending`` and
``claimed`` (waiting for CORE, or running).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.alert_scripts import SCRIPT_ACTION, SCRIPT_VENDOR
from app.db.rls_scope import acting_as_tenant
from app.models.tenant import Tenant
from app.models.vendor_action import VendorAction
from app.services.client_mapping import tenant_hidden
from app.services.vendor_actions import effective_status

router = APIRouter(prefix="/script-runs", tags=["alerts"])

MAX_ROWS = 200
PER_CLIENT_READ = 300
MESSAGE_CHARS = 500

Outcome = Literal["done", "failed", "waiting"]


class ScriptRunOut(BaseModel):
    id: uuid.UUID
    requested_at: datetime
    finished_at: datetime | None = None
    status: str  # done, failed, expired, pending or claimed
    outcome: Outcome  # done, failed (failed or expired) or waiting (pending or claimed)
    script: str
    device: str | None = None
    client_name: str | None = None
    alert_id: uuid.UUID | None = None
    alert_title: str | None = None
    message: str | None = None
    by: Literal["person", "rule"] = "person"


class ScriptRunList(BaseModel):
    items: list[ScriptRunOut]
    done: int
    failed: int
    waiting: int
    total: int  # rows matching the filters, before the cut at MAX_ROWS
    days: int


def outcome_of(effective: str) -> Outcome:
    """The three-way outcome a state falls under (pure): a script that ran, one that did not (failed, or expired unclaimed), or one still waiting for CORE."""
    if effective == "done":
        return "done"
    if effective in ("failed", "expired"):
        return "failed"
    return "waiting"


def to_item(row: Any, client_name: str | None, now: datetime) -> ScriptRunOut:
    """One log line from a script request row (pure)."""
    params = row.params if isinstance(row.params, dict) else {}
    state = effective_status(row.status, row.created_at, row.claimed_at, now)
    message = (row.result_message or "").strip()
    if state == "expired" and not message:
        message = "CORE did not collect this request within 30 minutes, so it was never run (CORE was off, or could not reach A.C.O.R.N)."
    if state == "failed" and row.status == "claimed" and not message:
        message = "CORE collected this request but never reported a result."
    return ScriptRunOut(
        id=row.id,
        requested_at=row.created_at,
        finished_at=row.finished_at,
        status=state,
        outcome=outcome_of(state),
        script=str(params.get("script_name") or params.get("script_id") or "script")[:200],
        device=(str(params["device"])[:255] if params.get("device") else None),
        client_name=client_name,
        alert_id=row.alert_id,
        alert_title=(str(params["alert_title"])[:300] if params.get("alert_title") else None),
        message=message[:MESSAGE_CHARS] or None,
        by="person" if row.requested_by is not None else "rule",
    )


@router.get("", response_model=ScriptRunList, summary="The scripts CORE was asked to run, and what came of each")
async def list_script_runs(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    client_id: uuid.UUID | None = Query(default=None, description="One client; omit for the organization and every client."),
    outcome: Outcome | None = Query(default=None, description="Only scripts that ran (done), did not run (failed) or are still waiting."),
    days: int = Query(default=30, ge=1, le=90),
) -> ScriptRunList:
    owner = current_user.tenant_id
    now = datetime.now(UTC)
    tenants = (await db.execute(select(Tenant).where(Tenant.parent_tenant_id == owner))).scalars().all()
    names = {t.id: t.name for t in tenants}
    if client_id is not None and client_id != owner and client_id not in names:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    scope = [client_id] if client_id is not None else [owner, *[t.id for t in tenants if not tenant_hidden(t)]]
    items: list[ScriptRunOut] = []
    for tid in scope:
        async with acting_as_tenant(db, tid):
            rows = (
                (
                    await db.execute(
                        select(VendorAction)
                        .where(
                            VendorAction.tenant_id == tid,
                            VendorAction.vendor == SCRIPT_VENDOR,
                            VendorAction.action == SCRIPT_ACTION,
                            VendorAction.created_at >= now - timedelta(days=days),
                        )
                        .order_by(VendorAction.created_at.desc())
                        .limit(PER_CLIENT_READ)
                    )
                )
                .scalars()
                .all()
            )
        items.extend(to_item(r, names.get(tid), now) for r in rows)
    items.sort(key=lambda i: i.requested_at, reverse=True)
    tally = {"done": 0, "failed": 0, "waiting": 0}
    for i in items:
        tally[i.outcome] += 1
    shown = [i for i in items if outcome is None or i.outcome == outcome]
    return ScriptRunList(items=shown[:MAX_ROWS], total=len(shown), days=days, **tally)

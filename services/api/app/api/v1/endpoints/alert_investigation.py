"""Give an AI investigation somewhere to report: a case and a HaloPSA ticket, made the moment it starts, and the finished report put on both.

The agents service runs the investigation and keeps the answer only in its own memory, so a report nobody copied was lost and the case ledger it writes to had no case to hold it. Starting one from an alert
now first makes sure the alert has a case (opening one when it has none) and a HaloPSA ticket (asking CORE for one when it has none, the way a ticket rule does), and when the run finishes the report is
added to the case as a comment and written on the ticket as a private note (once; if CORE has not opened the ticket yet, it is written the moment the ticket is linked).

Permission: ``cases:write``. A.C.O.R.N opens no ticket itself: the request is queued for CORE, which holds the HaloPSA key.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.api.v1.deps import AuthUser, require_permission
from app.api.v1.endpoints.alert_vendor_actions import _alert
from app.db.rls import TenantDBSession
from app.models.vendor_action import VendorAction
from app.services.alert_scope import alert_scope
from app.services.alert_ticket_rules import ACTION as TICKET_ACTION
from app.services.alert_ticket_rules import VENDOR as TICKET_VENDOR
from app.services.alert_ticket_rules import _halo_clients, has_ticket, report_note
from app.services.audit import emit_audit
from app.services.quarantine_release import _queue_ticket_note, halo_ticket_ids
from app.services.vendor_actions import PENDING_TTL

router = APIRouter(prefix="/alerts", tags=["alerts"])


class OpenOut(BaseModel):
    case_id: uuid.UUID
    case_created: bool
    # existing: the alert already has a ticket; queued: CORE was asked to open one; waiting: a request is already with CORE; none: no ticket will be opened (reason in `ticket_note`).
    ticket: Literal["existing", "queued", "waiting", "none"]
    ticket_note: str | None = None


class ReportIn(BaseModel):
    report: str = Field(min_length=1, max_length=30000)
    run_id: str | None = Field(default=None, max_length=80)


class ReportOut(BaseModel):
    case_commented: bool
    # queued: written to the ticket(s) now; waiting: no ticket yet, it is written when one is linked; none: nothing to write it to.
    ticket: Literal["queued", "waiting", "none"]


async def _ensure_case(db: Any, tid: uuid.UUID, alert: Any, who: str, now: datetime) -> tuple[uuid.UUID, bool]:
    """The case holding the alert, opening one (and linking the alert to it) when it has none."""
    if alert.case_id is not None:
        return alert.case_id, False
    case_id = uuid.uuid4()
    title = " ".join(str(alert.title or "Alert").split())[:300]
    body = f"Opened when an AI investigation was started on this alert by {who}.\n\n{str(alert.description or '').strip()}"[:4000]
    await db.execute(
        text(
            "INSERT INTO aisoc_cases (id, tenant_id, title, description, severity, status, mitre_techniques, alert_ids, compliance_frameworks, tags, "
            "opened_at, created_at, updated_at, created_by) VALUES (:id, :t, :title, :description, :severity, 'new', CAST('[]' AS JSONB), "
            "CAST(:alert_ids AS UUID[]), CAST('{}' AS TEXT[]), CAST(:tags AS JSONB), :now, :now, :now, :by)"
        ).bindparams(
            id=case_id,
            t=tid,
            title=title,
            description=body,
            severity=alert.severity if alert.severity in ("critical", "high", "medium", "low", "info") else "medium",
            alert_ids=[str(alert.id)],
            tags=json.dumps({"source": "ai_investigation", "alert_id": str(alert.id)}),
            now=now,
            by=who[:200],
        )
    )
    await db.execute(
        text("UPDATE alerts SET case_id = :c WHERE id = :a AND tenant_id = :t AND case_id IS NULL").bindparams(c=case_id, a=alert.id, t=tid)
    )
    alert.case_id = case_id
    return case_id, True


@router.post(
    "/{alert_id}/investigation/open",
    response_model=OpenOut,
    summary="Make sure the alert has a case and a ticket before an AI investigation starts",
)
async def open_investigation(
    alert_id: uuid.UUID,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("cases:write"))],
    db: TenantDBSession,
) -> OpenOut:
    now = datetime.now(UTC)
    who = getattr(current_user, "email", None) or "a person"
    async with alert_scope(db, current_user.tenant_id, alert_id) as tid:
        alert = await _alert(db, alert_id, tid)
        case_id, created = await _ensure_case(db, tid, alert, who, now)
        note: str | None = None
        if has_ticket(alert.enrichment_data):
            ticket = "existing"
        else:
            states = (
                await db.execute(
                    select(VendorAction.status, VendorAction.created_at).where(
                        VendorAction.tenant_id == tid,
                        VendorAction.alert_id == alert.id,
                        VendorAction.vendor == TICKET_VENDOR,
                        VendorAction.action == TICKET_ACTION,
                    )
                )
            ).all()
            if any(s in ("pending", "claimed") and c > now - PENDING_TTL for s, c in states):
                ticket = "waiting"
            else:
                halo = await _halo_clients(db, current_user.tenant_id, [tid])
                title = " ".join(str(alert.title or "Alert").split())[:200]
                details = (
                    (str(alert.description or alert.title or "").strip()[:2600])
                    + f"\n\nAn A.C.O.R.N AI investigation was started on alert {alert.id} by {who}; its report is added to this ticket when it finishes."
                )
                db.add(
                    VendorAction(
                        id=uuid.uuid4(),
                        tenant_id=tid,
                        alert_id=alert.id,
                        vendor=TICKET_VENDOR,
                        incident_uid=f"ai-investigation:{alert.id}"[:200],
                        action=TICKET_ACTION,
                        params={"summary": title, "details": details[:3000], **({"halo_client_id": halo[tid]} if tid in halo else {})},
                        status="pending",
                        requested_by=current_user.user_id,
                        created_at=now,
                    )
                )
                ticket = "queued"
                if tid not in halo:
                    note = "This client is not linked to a HaloPSA client yet, so CORE may put the ticket under a default client."
        await db.execute(
            text("INSERT INTO aisoc_case_comments (case_id, author, body, is_system, tenant_id) VALUES (:c, :a, :b, true, :t)").bindparams(
                c=case_id,
                a=str(current_user.user_id),
                b=f"AI investigation started by {who}. "
                + {
                    "existing": "The alert already has a HaloPSA ticket; the report will be added to it.",
                    "queued": "A HaloPSA ticket was requested from CORE; the report will be added to it.",
                    "waiting": "A HaloPSA ticket is already being opened; the report will be added to it.",
                }[ticket],
                t=tid,
            )
        )
        await emit_audit(
            db=db,
            tenant_id=tid,
            actor_id=current_user.user_id,
            action="alerts:investigation_opened",
            resource="alert",
            resource_id=str(alert.id),
            changes={"case": str(case_id), "case_created": created, "ticket": ticket},
            request=request,
        )
        await db.commit()
    return OpenOut(case_id=case_id, case_created=created, ticket=ticket, ticket_note=note)  # type: ignore[arg-type]


@router.post(
    "/{alert_id}/investigation/report",
    response_model=ReportOut,
    summary="Put a finished AI investigation's report on the alert's case and ticket",
)
async def report_investigation(
    alert_id: uuid.UUID,
    body: ReportIn,
    request: Request,
    current_user: Annotated[AuthUser, Depends(require_permission("cases:write"))],
    db: TenantDBSession,
) -> ReportOut:
    now = datetime.now(UTC)
    async with alert_scope(db, current_user.tenant_id, alert_id) as tid:
        alert = await _alert(db, alert_id, tid)
        if alert.case_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="This alert has no case yet. Start the investigation from the alert first."
            )
        await db.execute(
            text("INSERT INTO aisoc_case_comments (case_id, author, body, is_system, tenant_id) VALUES (:c, :a, :b, false, :t)").bindparams(
                c=alert.case_id,
                a=getattr(current_user, "email", None) or str(current_user.user_id),
                b=f"AI investigation report:\n\n{body.report.strip()}"[:30000],
                t=tid,
            )
        )
        enrichment = dict(alert.enrichment_data) if isinstance(alert.enrichment_data, dict) else {}
        tickets = halo_ticket_ids(enrichment)
        record: dict[str, Any] = {"text": body.report.strip()[:30000], "at": now.isoformat(), "ticketed": False, "run_id": body.run_id}
        if tickets:
            _queue_ticket_note(db, tid, alert.id, tickets, report_note(body.report), now)
            record["ticketed"] = True
            ticket = "queued"
        else:
            ticket = "waiting"
        enrichment["ai_investigation"] = record
        alert.enrichment_data = enrichment  # a new dict, so the JSONB column is seen as changed
        await emit_audit(
            db=db,
            tenant_id=tid,
            actor_id=current_user.user_id,
            action="alerts:investigation_reported",
            resource="alert",
            resource_id=str(alert.id),
            changes={"case": str(alert.case_id), "ticket": ticket, "run": body.run_id},
            request=request,
        )
        await db.commit()
    return ReportOut(case_commented=True, ticket=ticket)  # type: ignore[arg-type]

"""Business email compromise (BEC) searches from the Identities page.

A search is a case. ``POST /identities/bec`` records it and queues ``bec_search`` for CORE (the same queue the account actions use); CORE starts CIPP's BEC investigation for the person, follows it, and reports
progress and then the finished report through the core-feed routes in ``inbox_core_feed.py``. ``GET /identities/bec`` lists a person's recent searches and ``GET /identities/bec/{id}`` reads one with its report.
Both reads and the start need ``identities:bec`` (the report names attacker addresses, rules and mail activity). The search only READS: it asks CIPP to investigate and changes nothing in the tenant.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import _as, _scope
from app.api.v1.endpoints.identities import _people
from app.api.v1.endpoints.identity_actions import cipp_customer, clean_email
from app.models.bec_case import BecCase
from app.models.vendor_action import VendorAction
from app.services.audit import emit_audit

router = APIRouter(prefix="/identities/bec", tags=["identities"])

# A search CORE has not reported on for this long is shown as failed (CORE was restarted, or the search was lost); it normally finishes in minutes and CIPP says up to ten.
STALE_AFTER = timedelta(minutes=25)
RECENT_DAYS = 30


class StartBody(BaseModel):
    client_id: uuid.UUID
    email: str = Field(max_length=320)
    confirm: bool = Field(default=False, description="True only when the person pressed Yes in the confirmation window.")


class CaseItem(BaseModel):
    id: uuid.UUID
    case_ref: str
    email: str
    status: Literal["pending", "running", "done", "failed"]
    step: int
    steps_total: int
    step_label: str | None = None
    message: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class CaseDetail(CaseItem):
    report: dict[str, Any] | None = None


class CaseList(BaseModel):
    items: list[CaseItem]


def effective_status(row: Any, now: datetime) -> tuple[str, str | None]:
    """(status, message) as the page shows them: an open case nobody has reported on for STALE_AFTER is failed, with the reason, not left "running" for ever."""
    if row.status in ("pending", "running") and (now - row.updated_at) > STALE_AFTER:
        return "failed", "CORE stopped reporting on this search (it may have been restarted). Start it again."
    return row.status, row.message


def item_of(row: Any, now: datetime | None = None, with_report: bool = False) -> CaseItem | CaseDetail:
    now = now or datetime.now(UTC)
    state, message = effective_status(row, now)
    fields = dict(
        id=row.id,
        case_ref=row.case_ref,
        email=row.email,
        status=state,
        step=row.step,
        steps_total=row.steps_total,
        step_label=row.step_label,
        message=message,
        summary=row.summary or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
        finished_at=row.finished_at,
    )
    return CaseDetail(**fields, report=row.report) if with_report else CaseItem(**fields)


def case_ref(now: datetime, case_id: uuid.UUID) -> str:
    return f"BEC-{now:%Y%m%d%H%M%S}-{case_id.hex[:6]}"


def microsoft_id_of(person: Any) -> str | None:
    """The person's Microsoft 365 directory id (what CIPP asks for), from the CIPP record of any of their addresses."""
    return next((str(s.external_id) for s in person.sources if s.vendor == "cipp" and s.external_id), None)


@router.post("", response_model=CaseItem, status_code=status.HTTP_202_ACCEPTED)
async def start_bec_search(
    body: StartBody, request: Request, user: Annotated[AuthUser, Depends(require_permission("identities:bec"))], db: DBSession
) -> CaseItem:
    """Start a search. Returns 202: nothing has been looked at yet; the case fills in as CORE reports."""
    if not body.confirm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Confirm the search first.")
    email = clean_email(body.email)
    owner = user.tenant_id
    await _scope(db, owner, body.client_id)
    if body.client_id == owner:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Pick a client: a search is for a client's person.")
    people, _ = await _people(db, owner, body.client_id)
    person = next((p for p in people if p.tenant_id == body.client_id and email.lower() in p.addresses), None)
    uid = microsoft_id_of(person) if person else None
    if person is None or uid is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Microsoft 365 does not know this person, so there is nothing for CIPP to investigate.")
    cipp = await cipp_customer(db, owner, body.client_id)
    if not cipp:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This client is not linked to CIPP (Settings, Client mapping).")
    now = datetime.now(UTC)
    async with _as(db, owner, body.client_id):
        running = (
            (
                await db.execute(
                    select(BecCase).where(
                        BecCase.tenant_id == body.client_id,
                        BecCase.email == person.email,
                        BecCase.status.in_(("pending", "running")),
                        BecCase.updated_at > now - STALE_AFTER,
                    )
                )
            )
            .scalars()
            .all()
        )
        if running:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A search for this person is already running.")
        cid = uuid.uuid4()
        case = BecCase(id=cid, tenant_id=body.client_id, case_ref=case_ref(now, cid), email=person.email, status="pending", requested_by=user.user_id, created_at=now, updated_at=now)
        db.add(case)
        db.add(
            VendorAction(
                id=uuid.uuid4(),
                tenant_id=body.client_id,
                alert_id=None,
                vendor="core",
                incident_uid=f"bec:{cid}",
                action="bec_search",
                params={"client_id": cipp, "user": person.email, "user_id": microsoft_id_of(person), "case_id": str(cid), "case_ref": case.case_ref, "requested_by_name": (getattr(user, "email", None) or "")[:200] or None},
                status="pending",
                requested_by=user.user_id,
                created_at=now,
            )
        )
        await db.flush()
        await emit_audit(
            db=db,
            tenant_id=body.client_id,
            actor_id=user.user_id,
            action="identities:bec_requested",
            resource="identity",
            resource_id=person.email,
            changes={"email": person.email, "case": case.case_ref},
            request=request,
        )
        await db.commit()
        return item_of(case, now)  # type: ignore[return-value]


@router.get("", response_model=CaseList)
async def recent_bec_searches(
    user: Annotated[AuthUser, Depends(require_permission("identities:bec"))],
    db: DBSession,
    client_id: uuid.UUID,
    email: Annotated[str, Query(max_length=320)],
) -> CaseList:
    """A person's searches in the last month, newest first, without their reports."""
    owner = user.tenant_id
    await _scope(db, owner, client_id)
    address = email.strip().lower()
    if not address or client_id == owner:
        return CaseList(items=[])
    people, _ = await _people(db, owner, client_id)
    person = next((p for p in people if p.tenant_id == client_id and address in p.addresses), None)
    addresses = person.addresses if person else [address]
    since = datetime.now(UTC) - timedelta(days=RECENT_DAYS)
    async with _as(db, owner, client_id):
        rows = (
            (
                await db.execute(
                    select(BecCase)
                    .where(BecCase.tenant_id == client_id, BecCase.email.in_(addresses), BecCase.created_at > since)
                    .order_by(BecCase.created_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
    now = datetime.now(UTC)
    return CaseList(items=[item_of(r, now) for r in rows])  # type: ignore[misc]


@router.get("/{case_id}", response_model=CaseDetail)
async def read_bec_case(case_id: uuid.UUID, user: Annotated[AuthUser, Depends(require_permission("identities:bec"))], db: DBSession, client_id: uuid.UUID) -> CaseDetail:
    """One search with its whole report."""
    owner = user.tenant_id
    await _scope(db, owner, client_id)
    async with _as(db, owner, client_id):
        row = (await db.execute(select(BecCase).where(BecCase.id == case_id, BecCase.tenant_id == client_id))).scalars().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such search")
    return item_of(row, with_report=True)  # type: ignore[return-value]

"""The billing view: what each tool counts for each client (licences bought, devices managed, people covered), and every change to those counts. Read only for people; CORE writes the counts.

``POST /api/v1/inbox/core-feed/{token}/license-counts`` is CORE's daily report for one client and tool. ``GET /api/v1/billing/clients/{id}``, ``/billing/summary`` and ``/billing/changes`` are what the page reads.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import _as, _scope
from app.api.v1.endpoints.inbox_core_feed import _verify_core_feed_token
from app.api.v1.endpoints.signins import targets_by_tenant
from app.db.rls_scope import acting_as_tenant
from app.db.rls_sessions import adopt_tenant
from app.models.signin import ClientLicenseCount, ClientLicenseHistory
from app.models.tenant import Tenant
from app.services.license_counts import changes, count_at, delta, totals, window_start

router = APIRouter(prefix="/billing", tags=["billing"])
ingest_router = APIRouter(prefix="/inbox", tags=["inbox-core-feed"])

Unit = Literal["licence", "device", "user", "seat", "mailbox", "other"]


class LicenseCountIn(BaseModel):
    item: str = Field(min_length=1, max_length=80)
    unit: Unit = "other"
    count: int = Field(ge=0, le=10_000_000)
    # For a licence: how many are not assigned to anyone.
    available: int | None = Field(default=None, ge=0, le=10_000_000)


class LicenseCountsReport(BaseModel):
    vendor: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    vendor_client_id: str = Field(min_length=1, max_length=200)
    counts: list[LicenseCountIn] = Field(min_length=1, max_length=60)


class LicenseCountsResponse(BaseModel):
    accepted: int
    unmapped: int = 0
    ignored: int = 0


class _View:
    """Lets the shared client mapping place a report that belongs to one client, as a list of one item."""

    def __init__(self, report: LicenseCountsReport) -> None:
        self.vendor = report.vendor
        self.items = [report]


async def apply_license_counts(db: Any, owner: uuid.UUID, report: LicenseCountsReport, now: datetime | None = None) -> LicenseCountsResponse:
    """Store a client's counts for one tool, and write history for every item that is new, changed or gone. The caller owns the transaction."""
    now = now or datetime.now(UTC)
    by_tenant, unmapped, ignored, _waiting = await targets_by_tenant(db, owner, _View(report))
    accepted = 0
    reported = [c.model_dump() for c in report.counts]
    for tid in by_tenant:
        async with acting_as_tenant(db, tid):
            held = (await db.execute(select(ClientLicenseCount).where(ClientLicenseCount.tenant_id == tid, ClientLicenseCount.source == report.vendor))).scalars().all()
            plan = changes({r.item: r.count for r in held}, reported)
            for h in plan["history"]:
                db.add(ClientLicenseHistory(tenant_id=tid, source=report.vendor, observed_at=now, **h))
            for u in plan["upserts"]:
                values = {"tenant_id": tid, "source": report.vendor, "updated_at": now, "first_seen_at": now, **u}
                stmt = pg_insert(ClientLicenseCount).values(values)
                await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "source", "item"], set_={c: stmt.excluded[c] for c in ("unit", "count", "available", "updated_at")}))
            if plan["removed"]:
                await db.execute(delete(ClientLicenseCount).where(ClientLicenseCount.tenant_id == tid, ClientLicenseCount.source == report.vendor, ClientLicenseCount.item.in_(plan["removed"])))
            accepted += 1
    return LicenseCountsResponse(accepted=accepted, unmapped=unmapped, ignored=ignored)


@ingest_router.post("/core-feed/{tenant_token}/license-counts", response_model=LicenseCountsResponse)
async def report_core_feed_license_counts(tenant_token: str, body: LicenseCountsReport, db: DBSession) -> LicenseCountsResponse:
    """Record one client's counts for one tool (replacing the last report), and the changes since it."""
    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    result = await apply_license_counts(db, owner, body)
    await db.commit()
    return result


class CountRow(BaseModel):
    source: str
    item: str
    unit: str
    count: int
    available: int | None = None
    # How much the count moved over the window; None when it is not known what it was (A.C.O.R.N was not yet tracking this tool for the client).
    change: int | None = None
    first_seen_at: datetime
    updated_at: datetime


class ClientCounts(BaseModel):
    client_id: uuid.UUID
    days: int
    rows: list[CountRow]


async def _client_rows(db: Any, owner: uuid.UUID, cid: uuid.UUID, days: int, now: datetime) -> list[dict[str, Any]]:
    """One client's counts with each item's count ``days`` ago. Read under that client's own scope."""
    when = window_start(now, days)
    async with _as(db, owner, cid):
        held = (await db.execute(select(ClientLicenseCount).where(ClientLicenseCount.tenant_id == cid))).scalars().all()
        hist = (await db.execute(select(ClientLicenseHistory).where(ClientLicenseHistory.tenant_id == cid))).scalars().all()
    by_item: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for h in hist:
        by_item.setdefault((h.source, h.item), []).append({"observed_at": h.observed_at, "count": h.count})
    tracking: dict[str, datetime] = {}
    for r in held:
        tracking[r.source] = min(tracking.get(r.source, r.first_seen_at), r.first_seen_at)
    for h in hist:
        tracking[h.source] = min(tracking.get(h.source, h.observed_at), h.observed_at)
    out = []
    for r in held:
        then = count_at(by_item.get((r.source, r.item), []), r.count, r.first_seen_at, when, tracking[r.source])
        out.append({"source": r.source, "item": r.item, "unit": r.unit, "count": r.count, "available": r.available, "then": then, "change": delta(r.count, then), "first_seen_at": r.first_seen_at, "updated_at": r.updated_at})
    return sorted(out, key=lambda x: (x["source"], x["item"]))


@router.get("/clients/{client_id}", response_model=ClientCounts, summary="What each tool counts for one client, and how each count moved")
async def client_counts(client_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession, days: int = 30) -> ClientCounts:
    owner = current_user.tenant_id
    if client_id != owner:
        found = (await db.execute(select(Tenant.id).where(Tenant.id == client_id, Tenant.parent_tenant_id == owner))).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=404, detail="Client not found")
    now = datetime.now(UTC)
    rows = await _client_rows(db, owner, client_id, days, now)
    return ClientCounts(client_id=client_id, days=max(1, min(days, 400)), rows=[CountRow(**{k: v for k, v in r.items() if k != "then"}) for r in rows])


class TotalRow(BaseModel):
    source: str
    item: str
    unit: str
    clients: int
    total: int
    available: int | None = None
    change: int | None = None


class FleetTotals(BaseModel):
    generated_at: datetime
    days: int
    rows: list[TotalRow]


@router.get("/summary", response_model=FleetTotals, summary="Each tool's counts added across all clients, with the change over the window")
async def summary(current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession, days: int = 30) -> FleetTotals:
    owner = current_user.tenant_id
    ids, _names = await _scope(db, owner, None)
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for cid in ids[1:]:
        rows += await _client_rows(db, owner, cid, days, now)
    return FleetTotals(generated_at=now, days=max(1, min(days, 400)), rows=[TotalRow(**t) for t in totals(rows)])


class ChangeRow(BaseModel):
    client_id: uuid.UUID
    client_name: str
    source: str
    item: str
    unit: str
    count: int
    previous_count: int | None
    observed_at: datetime


@router.get("/changes", response_model=list[ChangeRow], summary="Every change to a count across all clients in the last days, newest first")
async def changes_log(
    current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession, days: int = 30, limit: int = 500, client_id: uuid.UUID | None = None
) -> list[ChangeRow]:
    owner = current_user.tenant_id
    ids, names = await _scope(db, owner, client_id)
    since = window_start(datetime.now(UTC), days)
    out: list[ChangeRow] = []
    for cid in ids if client_id is not None else ids[1:]:
        async with _as(db, owner, cid):
            rows = (await db.execute(select(ClientLicenseHistory).where(ClientLicenseHistory.tenant_id == cid, ClientLicenseHistory.observed_at >= since))).scalars().all()
        out += [
            ChangeRow(client_id=cid, client_name=names.get(cid) or str(cid), source=r.source, item=r.item, unit=r.unit, count=r.count, previous_count=r.previous_count, observed_at=r.observed_at) for r in rows
        ]
    out.sort(key=lambda c: c.observed_at, reverse=True)
    return out[: max(1, min(limit, 2000))]

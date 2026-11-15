"""Detected applications: the apps people consented to in a client's Microsoft 365 tenant, waiting for a person to deal with them (Secureframe parity plan, the vendor page's "Detected applications").

CORE reads each client's tenant through CIPP and reports the apps (``POST /inbox/core-feed/{token}/detected-applications``): name, how many consents there are, the scopes, whether one is risky. A person then:

* **Adds** an app, which makes a vendor of it (or, when a vendor of that name is already listed, links it to that one),
* **Ignores** it, which hides it (it can be brought back),
* **Links** it to a vendor already in the register, so several apps of one vendor show as one on the vendor page.

Nothing is deleted. Read with ``reports:read``, change with ``reports:write``; ``client_id`` reads or writes one of the caller's clients as the other compliance routes do.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import ScopeTenant
from app.api.v1.endpoints.inbox_core_feed import _verify_core_feed_token
from app.db.rls_scope import acting_as_tenant
from app.db.rls_sessions import adopt_tenant
from app.models.vendor_management import DetectedApplication, Vendor, VendorHistory
from app.services import compliance_audit as audit

router = APIRouter(prefix="/compliance/detected-applications", tags=["vendors"])
ingest_router = APIRouter(prefix="/inbox", tags=["vendors"])

MAX_APPS = 2000
STATUSES = ("new", "added", "linked", "ignored")
SOURCE_LABELS = {"cipp": "Microsoft 365"}


# ---- CORE reports the apps of one client ------------------------------------------------------------------------------------------------------------------


class AppIn(BaseModel):
    app_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)
    accounts: int = Field(default=0, ge=0, le=10_000_000)
    scopes: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=60)
    risky: bool = False
    first_seen: datetime | None = None


class AppsReport(BaseModel):
    vendor: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    vendor_client_id: str | None = Field(default=None, max_length=200)
    items: list[AppIn] = Field(max_length=MAX_APPS)


class AppsResponse(BaseModel):
    accepted: int = 0
    unmapped: int = 0
    ignored: int = 0


class _Item:
    """One entry the shared client mapping can place (it reads ``vendor_client_id`` of each)."""

    def __init__(self, vendor_client_id: str | None) -> None:
        self.vendor_client_id = vendor_client_id


class _View:
    def __init__(self, report: AppsReport) -> None:
        self.vendor = report.vendor
        self.items = [_Item(report.vendor_client_id)]


async def apply_applications(db: Any, owner: uuid.UUID, report: AppsReport) -> AppsResponse:
    """Store the apps under the client the tool's client id is mapped to (skipped and counted when it is not mapped yet or is ignored). A new app is ``new``; one already decided keeps its decision. The caller owns the transaction."""
    from app.api.v1.endpoints.signins import targets_by_tenant  # noqa: PLC0415

    by_tenant, unmapped, ignored, _waiting = await targets_by_tenant(db, owner, _View(report))  # type: ignore[arg-type]
    now = datetime.now(UTC)
    accepted = 0
    for tid in by_tenant:
        async with acting_as_tenant(db, tid):
            for it in report.items:
                values = {
                    "tenant_id": tid,
                    "source": report.vendor,
                    "app_id": it.app_id,
                    "name": it.name.strip(),
                    "accounts": it.accounts,
                    "scopes": it.scopes,
                    "risky": it.risky,
                    "first_seen": it.first_seen or now,
                    "last_seen": now,
                }
                stmt = pg_insert(DetectedApplication).values(values)
                update = {c: stmt.excluded[c] for c in ("name", "accounts", "scopes", "risky", "last_seen")}
                await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "source", "app_id"], set_=update))
                accepted += 1
    return AppsResponse(accepted=accepted, unmapped=unmapped, ignored=ignored)


@ingest_router.post("/core-feed/{tenant_token}/detected-applications", response_model=AppsResponse)
async def report_core_feed_applications(tenant_token: str, body: AppsReport, db: DBSession) -> AppsResponse:
    """Record the apps found in one client's Microsoft 365 tenant."""
    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    result = await apply_applications(db, owner, body)
    await db.commit()
    return result


# ---- reading and deciding ----------------------------------------------------------------------------------------------------------------------------------


class AppOut(BaseModel):
    id: uuid.UUID
    name: str
    source: str
    source_label: str
    accounts: int
    scopes: list[str]
    risky: bool
    first_seen: datetime
    last_seen: datetime
    status: str
    vendor_id: uuid.UUID | None
    vendor_name: str | None


class VendorChoice(BaseModel):
    id: uuid.UUID
    name: str


class AppList(BaseModel):
    apps: list[AppOut]
    counts: dict[str, int]
    vendors: list[VendorChoice]  # the vendors an app can be linked to


class LinkIn(BaseModel):
    vendor_id: uuid.UUID


def _out(a: DetectedApplication, vendor_names: dict[uuid.UUID, str]) -> AppOut:
    return AppOut(
        id=a.id,
        name=a.name,
        source=a.source,
        source_label=SOURCE_LABELS.get(a.source, a.source),
        accounts=a.accounts,
        scopes=list(a.scopes or []),
        risky=a.risky,
        first_seen=a.first_seen,
        last_seen=a.last_seen,
        status=a.status,
        vendor_id=a.vendor_id,
        vendor_name=vendor_names.get(a.vendor_id) if a.vendor_id else None,
    )


async def _vendors(db: Any, tenant: uuid.UUID) -> list[Vendor]:
    return list(
        (await db.execute(select(Vendor).where(Vendor.tenant_id == tenant, Vendor.status == "active").order_by(Vendor.name))).scalars()
    )


@router.get(
    "", response_model=AppList, summary="The applications found in the Microsoft 365 tenant, with how many are waiting for a decision"
)
async def list_applications(
    tenant: ScopeTenant,
    db: DBSession,
    _user: Annotated[AuthUser, Depends(require_permission("reports:read"))],
    show: str = Query("new", pattern="^(new|added|linked|ignored|all)$"),
) -> AppList:
    rows = list((await db.execute(select(DetectedApplication).where(DetectedApplication.tenant_id == tenant))).scalars())
    vendors = await _vendors(db, tenant)
    names = {v.id: v.name for v in vendors}
    counts = dict.fromkeys(STATUSES, 0)
    for r in rows:
        counts[r.status] += 1
    shown = [r for r in rows if show == "all" or r.status == show]
    shown.sort(key=lambda r: (-r.first_seen.timestamp(), r.name.lower()))
    return AppList(apps=[_out(r, names) for r in shown], counts=counts, vendors=[VendorChoice(id=v.id, name=v.name) for v in vendors])


async def _get(db: Any, tenant: uuid.UUID, app_id: uuid.UUID) -> DetectedApplication:
    row = (
        await db.execute(select(DetectedApplication).where(DetectedApplication.id == app_id, DetectedApplication.tenant_id == tenant))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return row


def _mark(row: DetectedApplication, user: Any, state: str, vendor_id: uuid.UUID | None) -> None:
    row.status = state
    row.vendor_id = vendor_id
    row.actioned_by = getattr(user, "email", None)
    row.actioned_at = datetime.now(UTC)


async def _note(db: Any, tenant: uuid.UUID, vendor_id: uuid.UUID, user: Any, action: str, detail: str) -> None:
    db.add(
        VendorHistory(
            id=uuid.uuid4(), tenant_id=tenant, vendor_id=vendor_id, actor=getattr(user, "email", None), action=action, detail=detail[:2000]
        )
    )


async def _one(db: Any, tenant: uuid.UUID, row: DetectedApplication) -> AppOut:
    names = {v.id: v.name for v in await _vendors(db, tenant)}
    return _out(row, names)


@router.post(
    "/{app_id}/add",
    response_model=AppOut,
    summary="Add the application as a vendor (or link it to the vendor of the same name that is already listed)",
)
async def add_application(
    app_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> AppOut:
    row = await _get(db, tenant, app_id)
    if row.status in ("added", "linked"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That application is already a vendor or linked to one.")
    existing = (
        (await db.execute(select(Vendor).where(Vendor.tenant_id == tenant, Vendor.status == "active", Vendor.name.ilike(row.name))))
        .scalars()
        .first()
    )
    if existing is not None:
        _mark(row, user, "linked", existing.id)
        await _note(db, tenant, existing.id, user, "application_linked", f"{row.name} ({row.accounts} accounts)")
    else:
        now = datetime.now(UTC)
        vendor = Vendor(
            id=uuid.uuid4(),
            tenant_id=tenant,
            name=row.name.strip()[:200],
            service="Found in the Microsoft 365 tenant",
            category="Other",
            risk_level="unassessed",
            created_by=getattr(user, "email", None),
            created_at=now,
            updated_at=now,
            notes=f"Added from a detected application ({row.accounts} account{'' if row.accounts == 1 else 's'}).",
        )
        db.add(vendor)
        await db.flush()
        await _note(db, tenant, vendor.id, user, "created", "added from a detected application")
        _mark(row, user, "added", vendor.id)
    await audit.note(db, tenant, user, "detected_application:added", "detected_application", app_id, name=row.name)
    await db.commit()
    return await _one(db, tenant, row)


@router.post(
    "/{app_id}/link",
    response_model=AppOut,
    summary="Link the application to a vendor already listed, so several apps of one vendor show as one",
)
async def link_application(
    app_id: uuid.UUID,
    body: LinkIn,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> AppOut:
    row = await _get(db, tenant, app_id)
    vendor = (
        await db.execute(select(Vendor).where(Vendor.id == body.vendor_id, Vendor.tenant_id == tenant, Vendor.status == "active"))
    ).scalar_one_or_none()
    if vendor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found")
    _mark(row, user, "linked", vendor.id)
    await _note(db, tenant, vendor.id, user, "application_linked", f"{row.name} ({row.accounts} accounts)")
    await audit.note(db, tenant, user, "detected_application:linked", "detected_application", app_id, name=row.name, vendor=str(vendor.id))
    await db.commit()
    return await _one(db, tenant, row)


@router.post("/{app_id}/ignore", response_model=AppOut, summary="Hide the application (it can be brought back)")
async def ignore_application(
    app_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> AppOut:
    row = await _get(db, tenant, app_id)
    _mark(row, user, "ignored", None)
    await audit.note(db, tenant, user, "detected_application:ignored", "detected_application", app_id, name=row.name)
    await db.commit()
    return await _one(db, tenant, row)


@router.post("/{app_id}/restore", response_model=AppOut, summary="Bring an ignored or linked application back to the waiting list")
async def restore_application(
    app_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> AppOut:
    row = await _get(db, tenant, app_id)
    if row.status == "added":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That application became a vendor; archive the vendor instead.")
    _mark(row, user, "new", None)
    await audit.note(db, tenant, user, "detected_application:restored", "detected_application", app_id, name=row.name)
    await db.commit()
    return await _one(db, tenant, row)

"""The stock Live Oak holds for clients: parts, drives, workstations and the NUCs, with who has each one and its history.

Replaces the SharePoint inventory lists. Every item belongs to a tenant: the client's own when it is held for that client, Live Oak's own when it is not (so a client portal can later show a client only its own items, with the row-level
security that already separates everything else). ``kind`` is ``stock`` (the LO inventory and the per-client lists) or ``nuc`` (listed by site, with its own columns).

Reading needs ``alerts:read``; adding, changing, checking in and out, and importing need ``mssp:manage``.
"""

from __future__ import annotations

import contextlib
import csv
import io
import re
import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.db.rls_scope import acting_as_tenant, cross_tenant_reads
from app.models.device import Device, DeviceSource
from app.models.inventory import InventoryEvent, InventoryItem
from app.models.tenant import Tenant
from app.services import inventory as inv
from app.services.client_matching import Candidate

router = APIRouter(prefix="/inventory", tags=["inventory"])

Kind = Literal["stock", "nuc"]
Status = Literal["checked_in", "checked_out", "offline", "retired"]


class DeviceLink(BaseModel):
    """The machine in the Devices page that this item is: matched on serial number, or on the NinjaOne device page the list carried."""

    device_id: uuid.UUID
    hostname: str
    last_seen: datetime
    how: Literal["serial", "ninjaone"]


class ItemOut(BaseModel):
    id: uuid.UUID
    kind: Kind
    client_id: uuid.UUID | None = Field(
        description="The client it is held for; None when it is Live Oak's own or its customer has not been matched to a client yet."
    )
    client_name: str | None
    customer_name: str | None
    name: str
    category: str | None
    serial: str | None
    model: str | None
    manufacturer: str | None
    quantity: int
    status: Status
    site: str | None
    person: str | None
    part_no: str | None
    has_charger: bool | None
    cpu: str | None
    memory: str | None
    storage: str | None
    ninja_url: str | None
    accounting_treatment: str | None
    deployed_at: date | None
    redeployed_at: date | None
    checked_out_at: date | None
    checked_in_at: date | None
    notes: str | None
    tags: list[str]
    ticket_url: str | None
    source: str
    updated_at: datetime
    device: DeviceLink | None = None


class Summary(BaseModel):
    total: int
    by_status: dict[str, int]
    categories: list[tuple[str, int]]
    unmatched_customers: int


class ItemList(BaseModel):
    items: list[ItemOut]
    total: int
    page: int
    pages: int
    summary: Summary


class ItemIn(BaseModel):
    kind: Kind = "stock"
    client_id: uuid.UUID | None = None
    customer_name: str | None = Field(default=None, max_length=200)
    name: str = Field(min_length=1, max_length=300)
    category: str | None = Field(default=None, max_length=80)
    serial: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=200)
    manufacturer: str | None = Field(default=None, max_length=100)
    quantity: int = Field(default=1, ge=0, le=100_000)
    status: Status = "checked_in"
    site: str | None = Field(default=None, max_length=200)
    person: str | None = Field(default=None, max_length=200)
    part_no: str | None = Field(default=None, max_length=60)
    has_charger: bool | None = None
    cpu: str | None = Field(default=None, max_length=200)
    memory: str | None = Field(default=None, max_length=60)
    storage: str | None = Field(default=None, max_length=60)
    ninja_url: str | None = Field(default=None, max_length=500, pattern=r"^https?://")
    accounting_treatment: str | None = Field(default=None, max_length=120)
    deployed_at: date | None = None
    redeployed_at: date | None = None
    notes: str | None = Field(default=None, max_length=4000)
    tags: list[Annotated[str, Field(max_length=40)]] = Field(default_factory=list, max_length=12)
    ticket_url: str | None = Field(default=None, max_length=500, pattern=r"^https?://")


class ItemPatch(BaseModel):
    """Any of an item's fields; only those sent change. Moving it to another client is ``client_id`` (``own`` is expressed by sending ``move_to_own``)."""

    client_id: uuid.UUID | None = None
    move_to_own: bool = False
    customer_name: str | None = Field(default=None, max_length=200)
    name: str | None = Field(default=None, min_length=1, max_length=300)
    category: str | None = Field(default=None, max_length=80)
    serial: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=200)
    manufacturer: str | None = Field(default=None, max_length=100)
    quantity: int | None = Field(default=None, ge=0, le=100_000)
    status: Status | None = None
    site: str | None = Field(default=None, max_length=200)
    person: str | None = Field(default=None, max_length=200)
    part_no: str | None = Field(default=None, max_length=60)
    has_charger: bool | None = None
    cpu: str | None = Field(default=None, max_length=200)
    memory: str | None = Field(default=None, max_length=60)
    storage: str | None = Field(default=None, max_length=60)
    ninja_url: str | None = Field(default=None, max_length=500, pattern=r"^https?://")
    accounting_treatment: str | None = Field(default=None, max_length=120)
    deployed_at: date | None = None
    redeployed_at: date | None = None
    notes: str | None = Field(default=None, max_length=4000)
    tags: list[Annotated[str, Field(max_length=40)]] | None = Field(default=None, max_length=12)
    ticket_url: str | None = Field(default=None, max_length=500, pattern=r"^https?://")


class MoveIn(BaseModel):
    person: str | None = Field(default=None, max_length=200)
    site: str | None = Field(default=None, max_length=200)
    ticket_url: str | None = Field(default=None, max_length=500, pattern=r"^https?://")
    note: str | None = Field(default=None, max_length=2000)


class EventOut(BaseModel):
    id: uuid.UUID
    at: datetime
    event: str
    actor: str | None
    person: str | None
    ticket_url: str | None
    note: str | None


FIELDS = [
    "customer_name",
    "name",
    "category",
    "serial",
    "model",
    "manufacturer",
    "quantity",
    "status",
    "site",
    "person",
    "part_no",
    "has_charger",
    "cpu",
    "memory",
    "storage",
    "ninja_url",
    "accounting_treatment",
    "deployed_at",
    "redeployed_at",
    "checked_out_at",
    "checked_in_at",
    "notes",
    "tags",
    "ticket_url",
]


async def _tenants(db: Any, owner: uuid.UUID) -> dict[uuid.UUID, str]:
    """The owner's clients (every one, hidden or not: stock held for an archived client is still stock)."""
    rows = (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == owner))).all()
    return {r.id: r.name for r in rows}


def _acting(db: Any, owner: uuid.UUID, tid: uuid.UUID) -> Any:
    return contextlib.nullcontext() if tid == owner else acting_as_tenant(db, tid)


def _out(item: InventoryItem, owner: uuid.UUID, names: dict[uuid.UUID, str], link: DeviceLink | None = None) -> ItemOut:
    data = {f: getattr(item, f) for f in ["kind", *FIELDS, "id", "source", "updated_at"]}
    data["tags"] = list(item.tags or [])
    return ItemOut(
        client_id=None if item.tenant_id == owner else item.tenant_id, client_name=names.get(item.tenant_id), device=link, **data
    )


async def _device_links(db: Any, scope: list[uuid.UUID], items: list[InventoryItem]) -> dict[uuid.UUID, DeviceLink]:
    """The machine each item is, for the items on a page: by serial number, else by the NinjaOne page its list carried. One read of the devices, not one per item."""
    serials = {inv.usable_serial(i.serial): i for i in items if inv.usable_serial(i.serial)}
    if serials:
        # A serial number held by more than one item (the maker's name left in the field, say) is not an identifier: it links nothing.
        async with cross_tenant_reads(db):
            shared = (
                await db.execute(
                    select(func.lower(InventoryItem.serial))
                    .where(
                        InventoryItem.tenant_id.in_(scope),
                        func.lower(InventoryItem.serial).in_([i.serial.lower() for i in serials.values() if i.serial]),
                    )
                    .group_by(func.lower(InventoryItem.serial))
                    .having(func.count() > 1)
                )
            ).all()
        held_twice = {inv.serial_key(r[0]) for r in shared}
        serials = {k: v for k, v in serials.items() if k not in held_twice}
    ninja_ids = {m.group(1): i for i in items if i.ninja_url and (m := re.search(r"deviceDashboard/(\d+)", i.ninja_url))}
    out: dict[uuid.UUID, DeviceLink] = {}
    if not serials and not ninja_ids:
        return out
    async with cross_tenant_reads(db):
        if serials:
            rows = (
                await db.execute(
                    select(Device.id, Device.hostname, Device.serial_number, Device.last_seen, Device.tenant_id).where(
                        Device.tenant_id.in_(scope),
                        func.lower(Device.serial_number).in_([i.serial.lower() for i in serials.values() if i.serial]),
                    )
                )
            ).all()
            for d in rows:
                item = serials.get(inv.serial_key(d.serial_number))
                if item is not None and item.id not in out:
                    out[item.id] = DeviceLink(device_id=d.id, hostname=d.hostname, last_seen=d.last_seen, how="serial")
        missing = {k: v for k, v in ninja_ids.items() if v.id not in out}
        if missing:
            rows = (
                await db.execute(
                    select(Device.id, Device.hostname, Device.last_seen, DeviceSource.external_id)
                    .join(DeviceSource, DeviceSource.device_id == Device.id)
                    .where(
                        DeviceSource.tenant_id.in_(scope), DeviceSource.vendor == "ninjaone", DeviceSource.external_id.in_(list(missing))
                    )
                )
            ).all()
            for d in rows:
                item = missing.get(d.external_id)
                if item is not None and item.id not in out:
                    out[item.id] = DeviceLink(device_id=d.id, hostname=d.hostname, last_seen=d.last_seen, how="ninjaone")
    return out


def _filters(
    kind: Kind,
    scope: list[uuid.UUID],
    owner: uuid.UUID,
    client: str | None,
    status: str | None,
    category: str | None,
    tag: str | None,
    search: str | None,
) -> list[Any]:
    f: list[Any] = [InventoryItem.kind == kind, InventoryItem.tenant_id.in_(scope)]
    if client == "own":
        f.append(and_(InventoryItem.tenant_id == owner))
    elif client:
        f.append(InventoryItem.tenant_id == uuid.UUID(client))
    if status:
        f.append(InventoryItem.status == status)
    if category:
        f.append(InventoryItem.category == category)
    if tag:
        f.append(InventoryItem.tags.contains([tag]))
    term = (search or "").strip()
    if term:
        like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        f.append(
            or_(
                *[
                    getattr(InventoryItem, col).ilike(like, escape="\\")
                    for col in ("name", "serial", "model", "customer_name", "person", "site", "notes", "part_no", "category")
                ]
            )
        )
    return f


@router.get("", response_model=ItemList, summary="The stock held for clients, filtered, with who has each item")
async def list_items(
    user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    kind: Kind = "stock",
    client: Annotated[
        str | None, Query(description="A client's id, or 'own' for Live Oak's own stock.", pattern=r"^(own|[0-9a-fA-F-]{36})$")
    ] = None,
    status: Status | None = None,
    category: str | None = Query(default=None, max_length=80),
    tag: str | None = Query(default=None, max_length=40),
    search: str | None = Query(default=None, max_length=100),
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ItemList:
    owner = user.tenant_id
    names = await _tenants(db, owner)
    scope = [owner, *names]
    if client and client != "own" and uuid.UUID(client) not in names:
        raise HTTPException(status_code=404, detail="Client not found")
    flt = _filters(kind, scope, owner, client, status, category, tag, search)
    base = _filters(kind, scope, owner, client, None, None, None, None)
    async with cross_tenant_reads(db):
        total = (await db.execute(select(func.count()).select_from(InventoryItem).where(and_(*flt)))).scalar_one()
        rows = (
            (
                await db.execute(
                    select(InventoryItem)
                    .where(and_(*flt))
                    .order_by(InventoryItem.name, InventoryItem.serial, InventoryItem.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        by_status = dict(
            (await db.execute(select(InventoryItem.status, func.count()).where(and_(*base)).group_by(InventoryItem.status))).all()
        )
        category_rows = (
            await db.execute(
                select(InventoryItem.category, func.count())
                .where(and_(*base), InventoryItem.category.is_not(None))
                .group_by(InventoryItem.category)
                .order_by(func.count().desc(), InventoryItem.category)
                .limit(30)
            )
        ).all()
        categories = [(row[0], row[1]) for row in category_rows]
        unmatched = (
            await db.execute(
                select(func.count(func.distinct(InventoryItem.customer_name))).where(
                    InventoryItem.kind == kind,
                    InventoryItem.tenant_id == owner,
                    InventoryItem.customer_name.is_not(None),
                    InventoryItem.customer_name != "",
                )
            )
        ).scalar_one()
    links = await _device_links(db, scope, list(rows))
    return ItemList(
        items=[_out(r, owner, names, links.get(r.id)) for r in rows],
        total=total,
        page=page,
        pages=max(1, (total + page_size - 1) // page_size),
        summary=Summary(total=sum(by_status.values()), by_status=by_status, categories=categories, unmatched_customers=unmatched),
    )


async def _find(db: Any, user: AuthUser, item_id: uuid.UUID) -> tuple[InventoryItem, dict[uuid.UUID, str]]:
    names = await _tenants(db, user.tenant_id)
    async with cross_tenant_reads(db):
        item = (
            await db.execute(
                select(InventoryItem).where(InventoryItem.id == item_id, InventoryItem.tenant_id.in_([user.tenant_id, *names]))
            )
        ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item, names


def _event(
    item: InventoryItem, event: str, actor: str | None, person: str | None = None, ticket_url: str | None = None, note: str | None = None
) -> InventoryEvent:
    return InventoryEvent(
        tenant_id=item.tenant_id, item_id=item.id, event=event, actor=actor, person=person, ticket_url=ticket_url, note=note
    )


@router.post("", response_model=ItemOut, status_code=201, summary="Add an item to the stock")
async def create_item(body: ItemIn, user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession) -> ItemOut:
    owner = user.tenant_id
    names = await _tenants(db, owner)
    if body.client_id is not None and body.client_id != owner and body.client_id not in names:
        raise HTTPException(status_code=404, detail="Client not found")
    tid = body.client_id or owner
    values = body.model_dump(exclude={"client_id"})
    async with _acting(db, owner, tid):
        item = InventoryItem(tenant_id=tid, source="manual", **values)
        db.add(item)
        await db.flush()
        db.add(_event(item, "created", user.email))
        await db.commit()
        await db.refresh(item)
    return _out(item, owner, names)


@router.patch("/{item_id}", response_model=ItemOut, summary="Change an item, or move it to another client")
async def update_item(
    item_id: uuid.UUID, body: ItemPatch, user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession
) -> ItemOut:
    owner = user.tenant_id
    item, names = await _find(db, user, item_id)
    changes = body.model_dump(exclude_unset=True, exclude={"client_id", "move_to_own"})
    target = owner if body.move_to_own else body.client_id
    if target is not None and target != owner and target not in names:
        raise HTTPException(status_code=404, detail="Client not found")
    async with _acting(db, owner, item.tenant_id):
        row = (await db.execute(select(InventoryItem).where(InventoryItem.id == item.id))).scalar_one()
        status_before = row.status
        for key, value in changes.items():
            setattr(row, key, value)
        note = ", ".join(sorted(changes)) or None
        if target is not None and target != row.tenant_id:
            row.tenant_id = target
            note = ((note + "; ") if note else "") + "moved to " + ("Live Oak" if target == owner else names[target])
            await db.execute(InventoryEvent.__table__.update().where(InventoryEvent.item_id == row.id).values(tenant_id=target))
        event = (
            "retired" if changes.get("status") == "retired" and status_before != "retired" else "moved" if target is not None else "updated"
        )
        db.add(_event(row, event, user.email, person=row.person, ticket_url=row.ticket_url, note=note))
        await db.commit()
        await db.refresh(row)
    return _out(row, owner, names)


async def _move(item_id: uuid.UUID, body: MoveIn, user: AuthUser, db: Any, to: str) -> ItemOut:
    owner = user.tenant_id
    item, names = await _find(db, user, item_id)
    allowed = inv.can_check_out(item.status) if to == "checked_out" else inv.can_check_in(item.status)
    if not allowed:
        raise HTTPException(
            status_code=409,
            detail=f"An item that is {item.status.replace('_', ' ')} cannot be checked {'out' if to == 'checked_out' else 'in'}",
        )
    today = datetime.now(UTC).date()
    async with _acting(db, owner, item.tenant_id):
        row = (await db.execute(select(InventoryItem).where(InventoryItem.id == item.id))).scalar_one()
        row.status = to
        if to == "checked_out":
            row.checked_out_at = today
            row.person = body.person or row.person
            if body.site:
                row.site = body.site
        else:
            row.checked_in_at = today
        if body.ticket_url:
            row.ticket_url = body.ticket_url
        db.add(_event(row, to, user.email, person=body.person or row.person, ticket_url=body.ticket_url, note=body.note))
        await db.commit()
        await db.refresh(row)
    return _out(row, owner, names)


@router.post("/{item_id}/check-out", response_model=ItemOut, summary="Check an item out to a person or a site")
async def check_out(
    item_id: uuid.UUID, body: MoveIn, user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession
) -> ItemOut:
    return await _move(item_id, body, user, db, "checked_out")


@router.post("/{item_id}/check-in", response_model=ItemOut, summary="Check an item back in")
async def check_in(
    item_id: uuid.UUID, body: MoveIn, user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession
) -> ItemOut:
    return await _move(item_id, body, user, db, "checked_in")


@router.get("/{item_id}/events", response_model=list[EventOut], summary="Everything that has happened to an item, newest first")
async def item_events(
    item_id: uuid.UUID, user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession
) -> list[EventOut]:
    item, _names = await _find(db, user, item_id)
    async with cross_tenant_reads(db):
        rows = (
            (
                await db.execute(
                    select(InventoryEvent).where(InventoryEvent.item_id == item.id).order_by(InventoryEvent.at.desc()).limit(200)
                )
            )
            .scalars()
            .all()
        )
    return [EventOut(id=r.id, at=r.at, event=r.event, actor=r.actor, person=r.person, ticket_url=r.ticket_url, note=r.note) for r in rows]


class ImportIn(BaseModel):
    kind: Kind
    csv_text: str = Field(max_length=8_000_000)
    default_client_id: uuid.UUID | None = Field(
        default=None, description="For a per-client list that has no Customer column: the client the whole file is for."
    )
    mapping: dict[str, str] = Field(
        default_factory=dict, description="A choice per customer name as written (lower case): a client's id, 'own' or 'skip'."
    )
    dry_run: bool = True


class CustomerPlacement(BaseModel):
    name: str
    rows: int
    placed: str  # exact | own | chosen | unmatched | skipped
    client_id: uuid.UUID | None
    client_name: str | None
    suggestions: list[dict[str, Any]]


class ImportOut(BaseModel):
    dry_run: bool
    rows: int
    created: int
    updated: int
    skipped: int
    problems: list[str]
    customers: list[CustomerPlacement]


@router.post(
    "/import", response_model=ImportOut, summary="Import an exported SharePoint list; a dry run first says where each customer would go"
)
async def import_items(body: ImportIn, user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession) -> ImportOut:
    owner = user.tenant_id
    names = await _tenants(db, owner)
    if body.default_client_id is not None and body.default_client_id != owner and body.default_client_id not in names:
        raise HTTPException(status_code=404, detail="Client not found")
    for pick in body.mapping.values():
        if pick not in (inv.OWN, inv.SKIP):
            try:
                tid = uuid.UUID(pick)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="A mapping choice is a client id, 'own' or 'skip'") from exc
            if tid != owner and tid not in names:
                raise HTTPException(status_code=404, detail="A mapped client was not found")
    try:
        rows = inv.parse_csv(body.csv_text, body.kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    candidates = [Candidate(str(t), n) for t, n in names.items()]
    chosen = {k.strip().lower(): v for k, v in body.mapping.items()}
    placed: dict[str, inv.Placement] = {}
    per_customer: dict[str, CustomerPlacement] = {}
    by_tenant: dict[uuid.UUID, list[inv.ParsedRow]] = {}
    problems: list[str] = []
    skipped = 0
    for r in rows:
        if r.problems:
            skipped += 1
            if len(problems) < 20:
                problems.append(f"line {r.line}: {', '.join(r.problems)}")
            continue
        key = (r.customer_name or "").strip().lower()
        if key not in placed:
            placed[key] = inv.place_customer(
                r.customer_name, str(owner), candidates, chosen, str(body.default_client_id) if body.default_client_id else None
            )
        p = placed[key]
        entry = per_customer.get(key)
        if entry is None:
            tid = uuid.UUID(p.tenant_id) if p.tenant_id else None
            how = "skipped" if p.tenant_id is None else p.how
            entry = per_customer[key] = CustomerPlacement(
                name=r.customer_name or "",
                rows=0,
                placed=how,
                client_id=None if tid is None or tid == owner else tid,
                client_name=names.get(tid) if tid else None,
                suggestions=[{"client_id": t, "client_name": n, "score": s} for t, n, s in p.suggestions],
            )
        entry.rows += 1
        if p.tenant_id is None:
            skipped += 1
            continue
        r.item["customer_name"] = r.customer_name  # kept as written, whoever it was placed under
        by_tenant.setdefault(uuid.UUID(p.tenant_id), []).append(r)
    created = updated = 0
    if not body.dry_run:
        for tid, group in by_tenant.items():
            async with _acting(db, owner, tid):
                existing = (
                    (await db.execute(select(InventoryItem).where(InventoryItem.tenant_id == tid, InventoryItem.kind == body.kind)))
                    .scalars()
                    .all()
                )
                by_ref = {e.external_ref: e for e in existing if e.external_ref}
                # A serial number only identifies an item when it is real and held by one item (here and in the file).
                held_twice = inv.shared_serials([{"serial": e.serial} for e in existing]) | inv.shared_serials([r.item for r in group])
                by_serial = {
                    inv.usable_serial(e.serial): e
                    for e in existing
                    if inv.usable_serial(e.serial) and inv.usable_serial(e.serial) not in held_twice
                }
                for r in group:
                    item = r.item
                    row = by_ref.get(item.get("external_ref") or "")
                    key = inv.usable_serial(item.get("serial"))
                    # A row that carries its list id is matched by that id alone: a re-import never merges two different rows because they share a serial.
                    if row is None and not item.get("external_ref") and key and key not in held_twice:
                        row = by_serial.get(key)
                    if row is None:
                        row = InventoryItem(tenant_id=tid, source="csv", **item)
                        db.add(row)
                        await db.flush()
                        db.add(_event(row, "created", user.email, note="imported from a SharePoint list"))
                        created += 1
                        if row.external_ref:
                            by_ref[row.external_ref] = row
                        if inv.usable_serial(row.serial) and inv.usable_serial(row.serial) not in held_twice:
                            by_serial[inv.usable_serial(row.serial)] = row
                    else:
                        for k, v in item.items():
                            if k in ("kind",):
                                continue
                            setattr(row, k, v)
                        db.add(_event(row, "updated", user.email, note="re-imported from a SharePoint list"))
                        updated += 1
            await db.commit()
    else:
        created = sum(len(g) for g in by_tenant.values())
    return ImportOut(
        dry_run=body.dry_run,
        rows=len(rows),
        created=created,
        updated=updated,
        skipped=skipped,
        problems=problems,
        customers=sorted(per_customer.values(), key=lambda c: (-c.rows, c.name.lower())),
    )


EXPORT_COLUMNS = [
    "client",
    "customer_name",
    "name",
    "category",
    "serial",
    "model",
    "manufacturer",
    "quantity",
    "status",
    "site",
    "person",
    "part_no",
    "has_charger",
    "cpu",
    "memory",
    "storage",
    "deployed_at",
    "redeployed_at",
    "checked_out_at",
    "checked_in_at",
    "ticket_url",
    "tags",
    "notes",
]


def _safe_cell(value: Any) -> str:
    """A cell for a spreadsheet: a value that starts with =, +, - or @ would be read as a formula, so it gets a quote in front."""
    text = "" if value is None else ", ".join(value) if isinstance(value, list) else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


@router.get("/export", summary="The filtered stock as a CSV file")
async def export_items(
    user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    kind: Kind = "stock",
    client: Annotated[str | None, Query(pattern=r"^(own|[0-9a-fA-F-]{36})$")] = None,
    status: Status | None = None,
    category: str | None = Query(default=None, max_length=80),
    tag: str | None = Query(default=None, max_length=40),
    search: str | None = Query(default=None, max_length=100),
) -> Response:
    owner = user.tenant_id
    names = await _tenants(db, owner)
    scope = [owner, *names]
    flt = _filters(kind, scope, owner, client, status, category, tag, search)
    async with cross_tenant_reads(db):
        rows = (
            (await db.execute(select(InventoryItem).where(and_(*flt)).order_by(InventoryItem.name, InventoryItem.serial).limit(20_000)))
            .scalars()
            .all()
        )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(EXPORT_COLUMNS)
    for r in rows:
        writer.writerow(
            [_safe_cell(names.get(r.tenant_id, "Live Oak")) if k == "client" else _safe_cell(getattr(r, k)) for k in EXPORT_COLUMNS]
        )
    return Response(
        content=out.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="inventory-{kind}.csv"'}
    )

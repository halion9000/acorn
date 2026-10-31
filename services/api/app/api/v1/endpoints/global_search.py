"""Search everything from the box at the top of the screen.

One question, answered across alerts, cases, devices, stock and NUCs, and clients. Typing a client's name also finds that client's alerts, cases, devices and stock, which is what people
usually mean. A few best matches per kind, newest first, each saying which client it belongs to; the screen links each one to the page that shows it.

Who can see what is the same as everywhere else here: the caller's own tenant and the clients it manages (an MSP sees its clients; a client's user sees only its own), read with the same
explicit tenant filter the stock list uses, and the route needs `alerts:read` like the stock list. Nothing is returned for a question shorter than two characters.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.db.rls_scope import cross_tenant_reads
from app.models.alert import Alert
from app.models.case import Case
from app.models.device import Device
from app.models.inventory import InventoryItem
from app.models.tenant import Tenant

router = APIRouter(prefix="/search", tags=["search"])

Kind = Literal["client", "alert", "case", "device", "stock", "nuc"]
PER_KIND = 5


class Hit(BaseModel):
    kind: Kind
    id: str
    title: str
    detail: str | None = None
    client: str | None = None
    client_id: str | None = None


class SearchOut(BaseModel):
    query: str
    hits: list[Hit]


def like(text: str) -> str:
    """The text as an ILIKE pattern that matches it literally (a % or _ typed by the person is not a wildcard)."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("", response_model=SearchOut, summary="Search alerts, cases, devices, stock and clients at once")
async def search(
    user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    q: Annotated[str, Query(max_length=100)],
    limit: Annotated[int, Query(ge=1, le=10)] = PER_KIND,
) -> SearchOut:
    text = q.strip()
    if len(text) < 2:
        return SearchOut(query=text, hits=[])
    pattern = like(text)
    owner = user.tenant_id
    rows = (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == owner))).all()
    names: dict[uuid.UUID, str] = {r.id: r.name for r in rows}
    scope = [owner, *names]
    # A client whose name matches brings its own records along.
    by_client = [tid for tid, name in names.items() if text.lower() in name.lower()]
    hits: list[Hit] = []

    def client_of(tid: uuid.UUID) -> tuple[str | None, str | None]:
        return (None, None) if tid == owner else (names.get(tid), str(tid))

    def add(kind: Kind, rid: object, title: str, detail: str | None, tid: uuid.UUID) -> None:
        name, cid = client_of(tid)
        hits.append(Hit(kind=kind, id=str(rid), title=title or "(untitled)", detail=detail, client=name, client_id=cid))

    async with cross_tenant_reads(db):
        for tid in by_client[:limit]:
            hits.append(Hit(kind="client", id=str(tid), title=names[tid], client=names[tid], client_id=str(tid)))
        alerts = (
            await db.execute(
                select(Alert.id, Alert.title, Alert.severity, Alert.status, Alert.tenant_id)
                .where(Alert.tenant_id.in_(scope), or_(Alert.title.ilike(pattern, escape="\\"), Alert.tenant_id.in_(by_client or [uuid.UUID(int=0)])))
                .order_by(Alert.created_at.desc())
                .limit(limit)
            )
        ).all()
        for a in alerts:
            add("alert", a.id, a.title, f"{a.severity} · {a.status}", a.tenant_id)
        cases = (
            await db.execute(
                select(Case.id, Case.case_number, Case.title, Case.status, Case.tenant_id)
                .where(
                    Case.tenant_id.in_(scope),
                    or_(Case.title.ilike(pattern, escape="\\"), Case.case_number.ilike(pattern, escape="\\"), Case.tenant_id.in_(by_client or [uuid.UUID(int=0)])),
                )
                .order_by(Case.created_at.desc())
                .limit(limit)
            )
        ).all()
        for c in cases:
            add("case", c.id, f"{c.case_number} {c.title}", c.status, c.tenant_id)
        devices = (
            await db.execute(
                select(Device.id, Device.hostname, Device.serial_number, Device.os, Device.tenant_id)
                .where(
                    Device.tenant_id.in_(scope),
                    or_(Device.hostname.ilike(pattern, escape="\\"), Device.serial_number.ilike(pattern, escape="\\"), Device.tenant_id.in_(by_client or [uuid.UUID(int=0)])),
                )
                .order_by(Device.last_seen.desc())
                .limit(limit)
            )
        ).all()
        for d in devices:
            add("device", d.id, d.hostname, " · ".join(x for x in (d.serial_number, d.os) if x) or None, d.tenant_id)
        items = (
            await db.execute(
                select(InventoryItem.id, InventoryItem.kind, InventoryItem.name, InventoryItem.serial, InventoryItem.person, InventoryItem.status, InventoryItem.tenant_id)
                .where(
                    InventoryItem.tenant_id.in_(scope),
                    or_(
                        InventoryItem.name.ilike(pattern, escape="\\"),
                        InventoryItem.serial.ilike(pattern, escape="\\"),
                        InventoryItem.person.ilike(pattern, escape="\\"),
                        InventoryItem.customer_name.ilike(pattern, escape="\\"),
                        InventoryItem.tenant_id.in_(by_client or [uuid.UUID(int=0)]),
                    ),
                )
                .order_by(InventoryItem.name)
                .limit(limit)
            )
        ).all()
        for i in items:
            kind: Kind = "nuc" if i.kind == "nuc" else "stock"
            add(kind, i.id, i.name, " · ".join(x for x in (i.serial, i.person, i.status) if x) or None, i.tenant_id)
    return SearchOut(query=text, hits=hits)

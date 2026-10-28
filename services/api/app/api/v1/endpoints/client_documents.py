"""A client's documentation (IT Glue) in the console: CORE sends it, people and Leafy search it.

``POST /core-feed/{token}/client-documents`` is CORE's report (the same token and client mapping as the other feeds). ``GET /client-documents`` searches it; ``GET /client-documents/summary`` says what is held.
Read only for the people using the console: nothing here changes IT Glue.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import UnmappedClient
from app.api.v1.endpoints.inbox_core_feed import _verify_core_feed_token
from app.db.rls_scope import cross_tenant_reads
from app.db.rls_sessions import adopt_tenant
from app.models.tenant import Tenant
from app.services import client_docs

router = APIRouter(prefix="/client-documents", tags=["client-documents"])
ingest_router = APIRouter(prefix="/inbox", tags=["client-documents"])

MAX_DOCS = 100


class ClientDocIn(BaseModel):
    vendor_client_id: str | None = Field(default=None, max_length=200)
    id: str = Field(min_length=1, max_length=80)
    kind: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    title: str = Field(min_length=1, max_length=300)
    folder: str | None = Field(default=None, max_length=300)
    body: str = Field(default="", max_length=client_docs.MAX_BODY * 4)
    url: str | None = Field(default=None, max_length=500)
    updated_at: datetime | None = None

    @field_validator("body")
    @classmethod
    def _cut(cls, v: str) -> str:
        """A long body is cut to what is stored, not refused: one huge document must not fail the whole batch."""
        return v[: client_docs.MAX_BODY]


class ClientDocsReport(BaseModel):
    vendor: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    items: list[ClientDocIn] = Field(max_length=MAX_DOCS)


class ClientDocsResponse(BaseModel):
    accepted: int
    unmapped: int = 0
    ignored: int = 0
    unmapped_clients: list[UnmappedClient] = Field(default_factory=list)


class DocHit(BaseModel):
    client_id: uuid.UUID
    client: str | None
    kind: str
    title: str
    folder: str | None = None
    url: str | None = None
    snippet: str


class DocSummary(BaseModel):
    client_id: uuid.UUID
    client: str | None
    kinds: dict[str, int]
    refreshed_at: datetime | None


@ingest_router.post("/core-feed/{tenant_token}/client-documents", response_model=ClientDocsResponse)
async def report_core_feed_client_documents(tenant_token: str, body: ClientDocsReport, db: DBSession) -> ClientDocsResponse:
    """Record the documentation CORE read from the documentation tool, under the client each record belongs to."""
    from app.api.v1.endpoints.signins import targets_by_tenant

    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    by_tenant, unmapped, ignored, waiting = await targets_by_tenant(db, owner, body)  # type: ignore[arg-type]
    accepted = await client_docs.apply_documents(db, by_tenant, body.vendor)
    await db.commit()
    return ClientDocsResponse(
        accepted=accepted,
        unmapped=unmapped,
        ignored=ignored,
        unmapped_clients=[UnmappedClient(vendor_client_id=w.vendor_client_id, name=w.name, devices=w.devices) for w in waiting],
    )


async def scope_clients(db: Any, owner: uuid.UUID) -> list[tuple[uuid.UUID, str | None]]:
    """The organization itself and each of its clients, as ``(id, name)``."""
    rows = (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == owner))).all()
    own = (await db.execute(select(Tenant.name).where(Tenant.id == owner))).scalar_one_or_none()
    return [(owner, own), *[(r[0], r[1]) for r in rows]]


async def find(db: Any, owner: uuid.UUID, query: str, client_id: uuid.UUID | None = None, limit: int = 8) -> list[DocHit]:
    """Search this organization's and its clients' documentation. A question that names a client looks only there; ``client_id`` pins one."""
    scope = await scope_clients(db, owner)
    names = dict(scope)
    if client_id is not None:
        ids = [client_id] if client_id in names else []
    else:
        named = client_docs.clients_named(query, [(cid, n) for cid, n in scope if n])
        ids = named or [cid for cid, _ in scope]
    async with cross_tenant_reads(db):
        hits = await client_docs.search_documents(db, ids, query, limit=limit)
    return [
        DocHit(
            client_id=h.tenant_id, client=names.get(h.tenant_id), kind=h.kind, title=h.title, folder=h.folder, url=h.url, snippet=h.snippet
        )
        for h in hits
    ]


@router.get("", response_model=list[DocHit], summary="Search the clients' documentation")
async def search_client_documents(
    user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    q: Annotated[str, Query(min_length=2, max_length=300)],
    client_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 8,
) -> list[DocHit]:
    return await find(db, user.tenant_id, q, client_id, limit)


@router.get("/summary", response_model=list[DocSummary], summary="What documentation is held, per client")
async def client_documents_summary(
    user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession
) -> list[DocSummary]:
    scope = await scope_clients(db, user.tenant_id)
    names = dict(scope)
    async with cross_tenant_reads(db):
        rows = await client_docs.summary(db, list(names))
    out: dict[uuid.UUID, DocSummary] = {}
    for tid, kind, count, refreshed in rows:
        row = out.setdefault(tid, DocSummary(client_id=tid, client=names.get(tid), kinds={}, refreshed_at=None))
        row.kinds[kind] = count
        if refreshed and (row.refreshed_at is None or refreshed > row.refreshed_at):
            row.refreshed_at = refreshed
    return sorted(out.values(), key=lambda r: (r.client or "").lower())

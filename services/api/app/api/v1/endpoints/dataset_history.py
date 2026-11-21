"""Read the saved versions of the datasets CORE sends (SIEM style storage, step 3): which datasets have history, the versions of one, and one old version whole.

Read with ``reports:read``. The versions belong to the organization (row-level security). Each version carries its SHA-256, and reading one recomputes it, so the answer says whether the stored copy is still exactly what was saved.
A version is never changed or deleted except by the retention purge (Settings > Data retention).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.services.dataset_versions import digest

router = APIRouter(prefix="/dataset-history", tags=["events"])

PAGE = 200


class DatasetSummary(BaseModel):
    key: str
    versions: int
    first: datetime
    latest: datetime


class VersionRow(BaseModel):
    id: int
    received_at: datetime
    sha256: str
    bytes: int


class VersionFull(VersionRow):
    key: str
    payload: dict[str, Any]
    # The SHA-256 was recomputed from the stored payload and matches the one saved with it.
    verified: bool


@router.get("", response_model=list[DatasetSummary], dependencies=[Depends(require_permission("reports:read"))], summary="The datasets that have saved versions")
async def list_datasets(user: AuthUser, db: DBSession) -> list[DatasetSummary]:
    rows = (
        await db.execute(
            text("SELECT key, count(*) AS n, min(received_at) AS first, max(received_at) AS latest FROM dataset_versions WHERE tenant_id = :t GROUP BY key ORDER BY key"), {"t": user.tenant_id}
        )
    ).all()
    return [DatasetSummary(key=r.key, versions=int(r.n), first=r.first, latest=r.latest) for r in rows]


@router.get("/{key}", response_model=list[VersionRow], dependencies=[Depends(require_permission("reports:read"))], summary="The saved versions of one dataset, newest first")
async def list_versions(key: str, user: AuthUser, db: DBSession, before: Annotated[int | None, Query(ge=1, le=9_000_000_000_000)] = None) -> list[VersionRow]:
    rows = (
        await db.execute(
            text(
                "SELECT id, received_at, sha256, length(payload::text) AS bytes FROM dataset_versions WHERE tenant_id = :t AND key = :k AND (CAST(:b AS BIGINT) IS NULL OR id < :b) ORDER BY id DESC LIMIT :n"
            ),
            {"t": user.tenant_id, "k": key, "b": before, "n": PAGE},
        )
    ).all()
    return [VersionRow(id=r.id, received_at=r.received_at, sha256=r.sha256, bytes=int(r.bytes)) for r in rows]


@router.get("/version/{version_id}", response_model=VersionFull, dependencies=[Depends(require_permission("reports:read"))], summary="One saved version whole, with a check that it is unchanged")
async def get_version(version_id: int, user: AuthUser, db: DBSession) -> VersionFull:
    r = (
        await db.execute(
            text("SELECT id, key, received_at, sha256, payload, length(payload::text) AS bytes FROM dataset_versions WHERE tenant_id = :t AND id = :i"), {"t": user.tenant_id, "i": version_id}
        )
    ).first()
    if r is None:
        raise HTTPException(status_code=404, detail="No such saved version")
    payload = r.payload if isinstance(r.payload, dict) else json.loads(r.payload)
    return VersionFull(id=r.id, key=r.key, received_at=r.received_at, sha256=r.sha256, bytes=int(r.bytes), payload=payload, verified=digest(payload) == r.sha256)

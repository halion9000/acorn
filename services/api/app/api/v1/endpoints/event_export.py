"""Export everything stored for one client when the client asks (SIEM style storage, step 5): a zip with the client's events as NDJSON and a manifest that lists each file with its count and SHA-256.

Run by staff (``mssp:manage``) and written to the audit log. Choose the source and dates, or take everything. Large exports are refused with a request to narrow the dates (the zip is built in memory), and the
file name says whose data it is. The manifest records the filters and the time, so the client can check that nothing was added or lost.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import text

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.event_search import build_query
from app.services.audit import emit_audit

router = APIRouter(prefix="/events", tags=["events"])

MAX_EVENTS = 200_000


def manifest_for(files: list[tuple[str, bytes, int]], client_id: str, filters: dict[str, Any], when: datetime) -> dict[str, Any]:
    """The manifest of an export (pure): each file's name, count of records and SHA-256, the filters used and when it was made."""
    return {
        "client_id": client_id,
        "generated_at": when.isoformat(),
        "filters": filters,
        "files": [{"name": name, "records": count, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data, count in files],
        "total_records": sum(count for _, _, count in files),
    }


def ndjson(rows: list[dict[str, Any]]) -> bytes:
    """One JSON object per line (pure)."""
    return ("\n".join(json.dumps(r, sort_keys=True, default=str, ensure_ascii=False) for r in rows) + ("\n" if rows else "")).encode("utf-8")


@router.get("/export", dependencies=[Depends(require_permission("mssp:manage"))], summary="Export one client's stored events as a zip (staff, when the client asks)")
async def export_client(
    request: Request,
    user: AuthUser,
    db: DBSession,
    client_id: Annotated[str, Query(pattern=r"^[0-9a-fA-F-]{36}$")],
    source: Annotated[str | None, Query(max_length=64)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Response:
    where, values = build_query(client_id, source, None, since, until, "", None)
    total = (await db.execute(text(f"SELECT count(*) FROM stored_events WHERE tenant_id = :tenant AND {where}"), {**values, "tenant": user.tenant_id})).scalar_one()
    if total > MAX_EVENTS:
        raise HTTPException(status_code=413, detail=f"That is {total} events; export a shorter date range (at most {MAX_EVENTS} at a time).")
    rows = (
        await db.execute(
            text(f"SELECT id, source, kind, event_time, pulled_at, external_id, payload FROM stored_events WHERE tenant_id = :tenant AND {where} ORDER BY event_time, id"),
            {**values, "tenant": user.tenant_id},
        )
    ).all()
    records = [{"id": r.id, "source": r.source, "kind": r.kind, "event_time": r.event_time.isoformat(), "pulled_at": r.pulled_at.isoformat(), "external_id": r.external_id, "payload": r.payload} for r in rows]
    when = datetime.now(UTC)
    files = [("events.ndjson", ndjson(records), len(records))]
    filters = {"source": source, "since": since.isoformat() if since else None, "until": until.isoformat() if until else None}
    manifest = json.dumps(manifest_for(files, client_id, filters, when), indent=2).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data, _ in files:
            z.writestr(name, data)
        z.writestr("manifest.json", manifest)
    await emit_audit(
        db=db,
        tenant_id=user.tenant_id,
        actor_id=user.user_id,
        action="events:exported",
        resource="client",
        resource_id=client_id,
        changes={"events": len(records), "source": source, "since": filters["since"], "until": filters["until"]},
        request=request,
    )
    await db.commit()
    name = f"events-{uuid.UUID(client_id).hex[:8]}-{when:%Y%m%d}.zip"
    return Response(content=buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})

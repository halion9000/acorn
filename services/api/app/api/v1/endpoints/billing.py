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
from app.models.client_alias import ClientAlias
from app.models.signin import BillingDifferenceNote, BillingItemMap, ClientLicenseCount, ClientLicenseHistory
from app.models.tenant import Tenant
from app.services.license_counts import BASELINE_TOOL, changes, count_at, count_series, delta, forecast_next, note_state, endpoint_disagreements, last_reported, reconcile, tools_without_counts, unbilled_clients, suggest, totals, unusual, window_start

router = APIRouter(prefix="/billing", tags=["billing"])
ingest_router = APIRouter(prefix="/inbox", tags=["inbox-core-feed"])

Unit = Literal["licence", "device", "user", "seat", "mailbox", "ticket", "other"]


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
async def client_counts(client_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("billing:view"))], db: DBSession, days: int = 30) -> ClientCounts:
    owner = current_user.tenant_id
    if client_id != owner:
        found = (await db.execute(select(Tenant.id).where(Tenant.id == client_id, Tenant.parent_tenant_id == owner))).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=404, detail="Client not found")
    now = datetime.now(UTC)
    rows = await _client_rows(db, owner, client_id, days, now)
    return ClientCounts(client_id=client_id, days=max(1, min(days, 400)), rows=[CountRow(**{k: v for k, v in r.items() if k != "then"}) for r in rows])


class SeriesPoint(BaseModel):
    at: datetime
    count: int


class CountSeries(BaseModel):
    client_id: uuid.UUID
    source: str
    item: str
    days: int
    points: list[SeriesPoint]
    # Where the count is heading: a straight line through the points read 30 days after the last one; None when there are fewer than three points or no trend.
    forecast_30d: int | None = None


@router.get("/clients/{client_id}/history", response_model=CountSeries, summary="One tool's count of one item for one client over time, as points for a chart")
async def client_count_history(
    client_id: uuid.UUID, source: str, item: str, current_user: Annotated[AuthUser, Depends(require_permission("billing:view"))], db: DBSession, days: int = 90
) -> CountSeries:
    owner = current_user.tenant_id
    if client_id != owner:
        found = (await db.execute(select(Tenant.id).where(Tenant.id == client_id, Tenant.parent_tenant_id == owner))).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=404, detail="Client not found")
    now = datetime.now(UTC)
    since = window_start(now, days)
    async with _as(db, owner, client_id):
        held = (await db.execute(select(ClientLicenseCount).where(ClientLicenseCount.tenant_id == client_id, ClientLicenseCount.source == source, ClientLicenseCount.item == item))).scalar_one_or_none()
        hist = (await db.execute(select(ClientLicenseHistory).where(ClientLicenseHistory.tenant_id == client_id, ClientLicenseHistory.source == source, ClientLicenseHistory.item == item))).scalars().all()
    if held is None and not hist:
        raise HTTPException(status_code=404, detail="No such count for this client")
    rows = [{"observed_at": h.observed_at, "count": h.count, "previous_count": h.previous_count} for h in hist]
    points = count_series(rows, held.count if held is not None else 0, now, since)
    return CountSeries(client_id=client_id, source=source, item=item, days=max(1, min(days, 400)), points=[SeriesPoint(**p) for p in points], forecast_30d=forecast_next(points))


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
async def summary(current_user: Annotated[AuthUser, Depends(require_permission("billing:view"))], db: DBSession, days: int = 30) -> FleetTotals:
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
    # More than a fifth of what it was (and at least five before): worth a second look.
    unusual: bool = False


@router.get("/changes", response_model=list[ChangeRow], summary="Every change to a count across all clients in the last days, newest first")
async def changes_log(
    current_user: Annotated[AuthUser, Depends(require_permission("billing:view"))], db: DBSession, days: int = 30, limit: int = 500, client_id: uuid.UUID | None = None, source: str | None = None
) -> list[ChangeRow]:
    owner = current_user.tenant_id
    ids, names = await _scope(db, owner, client_id)
    since = window_start(datetime.now(UTC), days)
    out: list[ChangeRow] = []
    for cid in ids if client_id is not None else ids[1:]:
        async with _as(db, owner, cid):
            stmt = select(ClientLicenseHistory).where(ClientLicenseHistory.tenant_id == cid, ClientLicenseHistory.observed_at >= since)
            if source:
                stmt = stmt.where(ClientLicenseHistory.source == source)  # "halopsa" is the history of what was billed: each time an invoice quantity was corrected, and by how much
            rows = (await db.execute(stmt)).scalars().all()
        out += [
            ChangeRow(client_id=cid, client_name=names.get(cid) or str(cid), source=r.source, item=r.item, unit=r.unit, count=r.count, previous_count=r.previous_count, observed_at=r.observed_at, unusual=unusual(r.count, r.previous_count)) for r in rows
        ]
    out.sort(key=lambda c: c.observed_at, reverse=True)
    return out[: max(1, min(limit, 2000))]


# ---- what is billed against what is counted ----------------------------------------------------------------------------------------------------------------------------

BILLED_SOURCE = "halopsa"


class CountedRef(BaseModel):
    source: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    item: str = Field(min_length=1, max_length=80)


class MapIn(BaseModel):
    invoice_item: str = Field(min_length=1, max_length=120)
    counted: list[CountedRef] = Field(max_length=12)


class MapRow(BaseModel):
    invoice_item: str
    counted: list[CountedRef]


class MapOut(BaseModel):
    mapped: list[MapRow]
    # Invoice lines HaloPSA bills that nobody has mapped yet, with the counts one probably equals (a person confirms it), and how many clients are billed for it.
    unmapped: list[dict[str, Any]]
    # The counts the tools hold, to map to: (tool, item) pairs.
    counted_items: list[CountedRef]


async def _all_client_counts(db: Any, owner: uuid.UUID) -> tuple[dict[uuid.UUID, list[dict[str, Any]]], dict[uuid.UUID, str]]:
    ids, names = await _scope(db, owner, None)
    out: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for cid in ids[1:]:
        async with _as(db, owner, cid):
            held = (await db.execute(select(ClientLicenseCount).where(ClientLicenseCount.tenant_id == cid))).scalars().all()
        out[cid] = [{"source": r.source, "item": r.item, "count": r.count, "unit": r.unit} for r in held]
    return out, names


async def _mapping(db: Any, owner: uuid.UUID) -> dict[str, list[dict[str, str]]]:
    rows = (await db.execute(select(BillingItemMap).where(BillingItemMap.tenant_id == owner))).scalars().all()
    return {r.invoice_item: [c for c in (r.counted or []) if isinstance(c, dict) and c.get("source") and c.get("item")] for r in rows}


@router.get("/map", response_model=MapOut, summary="Which tool counts each invoice line is checked against, and the lines still to map")
async def billing_map(current_user: Annotated[AuthUser, Depends(require_permission("billing:view"))], db: DBSession) -> MapOut:
    owner = current_user.tenant_id
    mapping = await _mapping(db, owner)
    per_client, _names = await _all_client_counts(db, owner)
    billed_clients: dict[str, int] = {}
    tool_items: set[tuple[str, str]] = set()
    for rows in per_client.values():
        for r in rows:
            if r["source"] == BILLED_SOURCE:
                if r.get("unit") != "ticket":  # a count of tickets is not an invoice line
                    billed_clients[r["item"]] = billed_clients.get(r["item"], 0) + 1
            else:
                tool_items.update([(r["source"], r["item"])])
    unmapped = [{"invoice_item": i, "clients": n, "suggestion": suggest(i)} for i, n in sorted(billed_clients.items(), key=lambda kv: (-kv[1], kv[0])) if i not in mapping]
    return MapOut(
        mapped=[MapRow(invoice_item=i, counted=[CountedRef(**c) for c in cs]) for i, cs in sorted(mapping.items())],
        unmapped=unmapped,
        counted_items=[CountedRef(source=s, item=i) for s, i in sorted(tool_items)],
    )


@router.put("/map", response_model=MapRow, summary="Say which tool counts an invoice line should equal")
async def save_map(body: MapIn, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession) -> MapRow:
    owner = current_user.tenant_id
    item = " ".join(body.invoice_item.split())
    if not item:
        raise HTTPException(status_code=422, detail="Name the invoice line")
    counted = [c.model_dump() for c in body.counted]
    values = {"tenant_id": owner, "invoice_item": item, "counted": counted, "updated_by": current_user.user_id, "updated_at": datetime.now(UTC)}
    stmt = pg_insert(BillingItemMap).values(values)
    await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "invoice_item"], set_={c: stmt.excluded[c] for c in ("counted", "updated_by", "updated_at")}))
    await db.commit()
    return MapRow(invoice_item=item, counted=body.counted)


@router.delete("/map", status_code=204, summary="Stop checking an invoice line against tool counts")
async def delete_map(invoice_item: str, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession) -> None:
    owner = current_user.tenant_id
    await db.execute(delete(BillingItemMap).where(BillingItemMap.tenant_id == owner, BillingItemMap.invoice_item == " ".join(invoice_item.split())))
    await db.commit()


class ReconcileRow(BaseModel):
    client_id: uuid.UUID
    client_name: str
    invoice_item: str
    billed: int
    counted: int
    difference: int
    parts: list[dict[str, Any]]
    # "accepted": a person said this difference is fine and it has not changed since; "stale": there is a note but the difference is no longer the one it was written for; "none".
    note_state: str = "none"
    note: str | None = None


class ReconcileOut(BaseModel):
    generated_at: datetime
    rows: list[ReconcileRow]
    # How many billed lines were left out because nobody has mapped them.
    unmapped_lines: int


async def _notes(db: Any, owner: uuid.UUID) -> dict[tuple[uuid.UUID, str], dict[str, Any]]:
    """{(client, invoice line): {note, difference}}. An older database without the table gives none."""
    try:
        async with db.begin_nested():
            rows = (await db.execute(select(BillingDifferenceNote).where(BillingDifferenceNote.tenant_id == owner))).scalars().all()
    except Exception:  # noqa: BLE001
        return {}
    return {(r.client_id, r.invoice_item): {"note": r.note, "difference": r.difference} for r in rows}


class NoteIn(BaseModel):
    client_id: uuid.UUID
    invoice_item: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=1, max_length=400)
    # The difference (counted minus billed) the note is written for: the line is accepted only while it stays this number.
    difference: int


@router.put("/notes", status_code=204, summary="Accept a difference between billed and counted for one client's invoice line, with a reason")
async def save_note(body: NoteIn, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession) -> None:
    owner = current_user.tenant_id
    if body.client_id != owner:
        found = (await db.execute(select(Tenant.id).where(Tenant.id == body.client_id, Tenant.parent_tenant_id == owner))).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=404, detail="Client not found")
    note = " ".join(body.note.split())
    item = " ".join(body.invoice_item.split())
    if len(note) < 3 or not item:
        raise HTTPException(status_code=422, detail="Give a reason of at least 3 characters")
    values = {"tenant_id": owner, "client_id": body.client_id, "invoice_item": item, "note": note, "difference": body.difference, "updated_by": current_user.user_id, "updated_at": datetime.now(UTC)}
    stmt = pg_insert(BillingDifferenceNote).values(values)
    await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "client_id", "invoice_item"], set_={c: stmt.excluded[c] for c in ("note", "difference", "updated_by", "updated_at")}))
    await db.commit()


@router.delete("/notes", status_code=204, summary="Stop accepting a difference for one client's invoice line")
async def delete_note(client_id: uuid.UUID, invoice_item: str, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession) -> None:
    owner = current_user.tenant_id
    await db.execute(delete(BillingDifferenceNote).where(BillingDifferenceNote.tenant_id == owner, BillingDifferenceNote.client_id == client_id, BillingDifferenceNote.invoice_item == " ".join(invoice_item.split())))
    await db.commit()


@router.get("/reconcile", response_model=ReconcileOut, summary="Where what is billed and what the tools count disagree, biggest difference first")
async def reconcile_billing(
    current_user: Annotated[AuthUser, Depends(require_permission("billing:view"))], db: DBSession, include_matches: bool = False, limit: int = 500
) -> ReconcileOut:
    owner = current_user.tenant_id
    mapping = await _mapping(db, owner)
    per_client, names = await _all_client_counts(db, owner)
    notes = await _notes(db, owner)
    out: list[ReconcileRow] = []
    unmapped_lines = 0
    for cid, rows in per_client.items():
        billed = [{"item": r["item"], "count": r["count"]} for r in rows if r["source"] == BILLED_SOURCE and r.get("unit") != "ticket"]
        held = [r for r in rows if r["source"] != BILLED_SOURCE]
        result = reconcile(billed, held, mapping)
        unmapped_lines += len(result["unmapped"])
        for r in result["rows"]:
            if include_matches or r["difference"] != 0:
                n = notes.get((cid, r["invoice_item"]))
                out.append(ReconcileRow(client_id=cid, client_name=names.get(cid) or str(cid), note_state=note_state(n, r["difference"]), note=n["note"] if n else None, **r))
    out.sort(key=lambda r: (-abs(r.difference), r.client_name.lower(), r.invoice_item))
    return ReconcileOut(generated_at=datetime.now(UTC), rows=out[: max(1, min(limit, 2000))], unmapped_lines=unmapped_lines)


class DisagreementRow(BaseModel):
    client_id: uuid.UUID
    client_name: str
    tool: str
    tool_count: int
    # What the RMM manages for the same client.
    baseline_count: int
    # tool_count minus baseline_count: negative means the tool covers fewer machines than the RMM manages.
    gap: int


class DataQualityOut(BaseModel):
    generated_at: datetime
    baseline_tool: str
    rows: list[DisagreementRow]
    # Tools that have clients mapped to them but have never stored a count (some count nothing by design).
    no_counts: list[str] = []
    # Clients the RMM manages machines for that have no billed line at all (counted, never billed), most machines first. Empty when no client has any billing data yet.
    unbilled: list[DisagreementRow] = []


@router.get("/data-quality", response_model=DataQualityOut, summary="Clients where a security tool counts noticeably fewer or more machines than the RMM manages, biggest gap first")
async def data_quality(current_user: Annotated[AuthUser, Depends(require_permission("billing:view"))], db: DBSession, limit: int = 500) -> DataQualityOut:
    owner = current_user.tenant_id
    per_client, names = await _all_client_counts(db, owner)
    rows = [DisagreementRow(client_id=d["client"], client_name=names.get(d["client"]) or str(d["client"]), tool=d["tool"], tool_count=d["tool_count"], baseline_count=d["baseline_count"], gap=d["gap"]) for d in endpoint_disagreements(per_client)]
    mapped = {v for (v,) in (await db.execute(select(ClientAlias.vendor).where(ClientAlias.tenant_id == owner, ClientAlias.child_tenant_id.is_not(None), ClientAlias.ignored.is_(False)).distinct())).all()}
    counted = {r["source"] for rs in per_client.values() for r in rs}
    # Only meaningful once billing data exists at all: otherwise every client would look unbilled.
    unbilled = (
        [DisagreementRow(client_id=u["client"], client_name=names.get(u["client"]) or str(u["client"]), tool=BILLED_SOURCE, tool_count=0, baseline_count=u["machines"], gap=-u["machines"]) for u in unbilled_clients(per_client, BILLED_SOURCE)]
        if BILLED_SOURCE in counted
        else []
    )
    return DataQualityOut(generated_at=datetime.now(UTC), baseline_tool=BASELINE_TOOL, rows=rows[: max(1, min(limit, 2000))], no_counts=tools_without_counts(mapped, counted), unbilled=unbilled[: max(1, min(limit, 2000))])


class LastReportedRow(BaseModel):
    client_id: uuid.UUID
    client_name: str
    source: str
    last_reported_at: datetime
    days_ago: int
    # More than two days ago: the daily report from this tool for this client stopped arriving.
    silent: bool


@router.get("/last-reported", response_model=list[LastReportedRow], summary="When each tool last reported a count for each client, silent ones first")
async def last_reported_grid(
    current_user: Annotated[AuthUser, Depends(require_permission("billing:view"))], db: DBSession, only_silent: bool = False, limit: int = 1000
) -> list[LastReportedRow]:
    owner = current_user.tenant_id
    ids, names = await _scope(db, owner, None)
    rows: list[dict[str, Any]] = []
    for cid in ids[1:]:
        async with _as(db, owner, cid):
            held = (await db.execute(select(ClientLicenseCount.source, ClientLicenseCount.updated_at).where(ClientLicenseCount.tenant_id == cid))).all()
        rows += [{"client": cid, "source": src, "updated_at": at} for src, at in held]
    out = [
        LastReportedRow(client_id=r["client"], client_name=names.get(r["client"]) or str(r["client"]), source=r["source"], last_reported_at=r["last_reported_at"], days_ago=r["days_ago"], silent=r["silent"])
        for r in last_reported(rows, datetime.now(UTC))
    ]
    if only_silent:
        out = [r for r in out if r.silent]
    return out[: max(1, min(limit, 5000))]

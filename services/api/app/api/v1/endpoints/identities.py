"""The Identities page: every person (e-mail identity) the connected tools know, one row each, with the tools that know them, their multi-factor state and the alerts that name them.

``GET /identities`` lists them (filters and sorting), ``GET /identities/detail`` is one person with their alerts and recent sign-ins, and ``POST /inbox/core-feed/{token}/identities`` is where CORE reports the
people of each tool (Datto SaaS Protection, Dropsuite, Huntress SAT, HaloPSA...). Microsoft 365 people come from the list CIPP already fills. Read only; nothing here changes a person in any tool.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.alerts import FINISHED_STATUSES
from app.api.v1.endpoints.devices import DevicesResponse, UnmappedClient, _scope
from app.api.v1.endpoints.inbox_core_feed import _verify_core_feed_token
from app.db.rls_scope import acting_as_tenant, cross_tenant_reads
from app.db.rls_sessions import adopt_tenant
from app.models.alert import Alert
from app.models.identity_source import IdentitySource
from app.models.person_ticket import PersonTicket
from app.models.signin import DirectoryAuditEvent, IdentityMfaUser, SigninEvent
from app.services.alert_suppression import SUPPRESSED, source_of
from app.services.identity_people import (
    MICROSOFT,
    SORTS,
    Person,
    add_alert_sources,
    attach_alerts,
    build_people,
    filter_people,
    normalize_email,
    sort_people,
)

router = APIRouter(prefix="/identities", tags=["identities"])
ingest_router = APIRouter(prefix="/inbox", tags=["inbox-core-feed"])

ALERT_LOOKBACK_DAYS = 90
MAX_ALERTS_READ = 20000


# ---- reading -----------------------------------------------------------------------------------------------------------------------------------------------


class SourceOut(BaseModel):
    vendor: str
    external_id: str
    enabled: bool | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class BackupOut(BaseModel):
    vendor: str
    status: str
    detail: str


class ExposureOut(BaseModel):
    count: int
    latest: str | None = None
    password: bool = False
    stealer_log: bool = False
    malware: bool = False
    # The most recent breaches: {name, date, data}, where data is the kinds of data that leaked (labels, never values).
    breaches: list[dict] = Field(default_factory=list)


class PersonOut(BaseModel):
    key: str
    client_id: uuid.UUID
    client_name: str | None = None
    email: str
    display_name: str | None = None
    kind: str
    enabled: bool | None = None
    admin: bool = False
    licensed: bool | None = None
    mfa: str
    mfa_methods: str | None = None
    tools: list[str]
    sources: list[SourceOut] = Field(default_factory=list)
    open_alerts: int = 0
    top_severity: str | None = None
    alerts_by_source: dict[str, int] = Field(default_factory=dict)
    backups: list[BackupOut] = Field(default_factory=list)
    exposure: ExposureOut | None = None
    # HaloPSA tickets about this person in the window CORE reads, and when the newest was opened (the list page only; the person's own panel lists the tickets).
    tickets: int = 0
    last_ticket_at: datetime | None = None


class IdentitySummary(BaseModel):
    total: int
    with_alerts: int
    without_mfa: int
    admins: int
    disabled: int
    # People known to only one tool (so no other tool has them): the ones to look at when a tool is missing someone.
    in_one_tool: int
    tools: dict[str, int] = Field(default_factory=dict)
    # How many people have an open alert from each tool, so the page can offer them as a filter.
    alert_sources: dict[str, int] = Field(default_factory=dict)
    # People a backup tool reports a problem for (no recent backup, an error, paused or unprotected).
    backup_problems: int = 0
    # People whose address turned up in a breach, and those where it was serious (a password, a stealer log or malware).
    exposed: int = 0
    exposed_serious: int = 0


class IdentityList(BaseModel):
    summary: IdentitySummary
    items: list[PersonOut]
    total: int
    page: int
    page_size: int
    pages: int


def _out(p: Person, with_sources: bool = False) -> PersonOut:
    return PersonOut(
        key=p.key,
        client_id=p.tenant_id,
        client_name=p.client_name,
        email=p.email,
        display_name=p.display_name,
        kind=p.kind,
        enabled=p.enabled,
        admin=p.admin,
        licensed=p.licensed,
        mfa=p.mfa,
        mfa_methods=p.mfa_methods,
        tools=p.vendors,
        sources=[SourceOut(vendor=s.vendor, external_id=s.external_id, enabled=s.enabled, details=s.details) for s in p.sources]
        if with_sources
        else [],
        open_alerts=p.open_alerts,
        top_severity=p.top_severity,
        alerts_by_source=p.alerts_by_source,
        backups=[BackupOut(vendor=b.vendor, status=b.status, detail=b.detail) for b in p.backups],
        exposure=ExposureOut(
            count=p.exposure.count,
            latest=p.exposure.latest,
            password=p.exposure.password,
            stealer_log=p.exposure.stealer_log,
            malware=p.exposure.malware,
            breaches=p.exposure.breaches,
        )
        if p.exposure is not None
        else None,
    )


async def _people(db: Any, owner: uuid.UUID, client_id: uuid.UUID | None) -> tuple[list[Person], dict[str, list[Any]]]:
    """Every person in scope with alerts attached, and the alerts by person."""
    scope, clients = await _scope(db, owner, client_id)
    names = dict(clients)
    names.setdefault(owner, "This organization")
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=ALERT_LOOKBACK_DAYS)
    async with cross_tenant_reads(db):
        users = (
            (await db.execute(select(IdentityMfaUser).where(IdentityMfaUser.tenant_id.in_(scope), IdentityMfaUser.source == MICROSOFT)))
            .scalars()
            .all()
        )
        sources = (await db.execute(select(IdentitySource).where(IdentitySource.tenant_id.in_(scope)))).scalars().all()
        alerts = (
            (
                await db.execute(
                    select(Alert)
                    .where(Alert.tenant_id.in_(scope), Alert.status != SUPPRESSED, Alert.created_at >= cutoff)
                    .order_by(Alert.created_at.desc())
                    .limit(MAX_ALERTS_READ)
                )
            )
            .scalars()
            .all()
        )
    named = [a for a in alerts if a.affected_users]
    people = add_alert_sources(build_people(names, list(users), list(sources), now), named, names, source_of)
    return people, attach_alerts(people, [a for a in named if a.status not in FINISHED_STATUSES], source_of)


def summarize(people: list[Person]) -> IdentitySummary:
    tools: dict[str, int] = {}
    alert_sources: dict[str, int] = {}
    for p in people:
        for v in p.vendors:
            tools[v] = tools.get(v, 0) + 1
        for v in p.alerts_by_source:
            alert_sources[v] = alert_sources.get(v, 0) + 1
    return IdentitySummary(
        total=len(people),
        with_alerts=sum(1 for p in people if p.open_alerts > 0),
        without_mfa=sum(1 for p in people if p.mfa == "none" and p.enabled is not False),
        admins=sum(1 for p in people if p.admin),
        disabled=sum(1 for p in people if p.enabled is False),
        in_one_tool=sum(1 for p in people if len(p.vendors) == 1),
        tools=dict(sorted(tools.items())),
        alert_sources=dict(sorted(alert_sources.items())),
        backup_problems=sum(1 for p in people if any(b.status != "ok" for b in p.backups)),
        exposed=sum(1 for p in people if p.exposure is not None),
        exposed_serious=sum(
            1 for p in people if p.exposure is not None and (p.exposure.password or p.exposure.stealer_log or p.exposure.malware)
        ),
    )


@router.get("", response_model=IdentityList, dependencies=[Depends(require_permission("alerts:read"))])
async def list_identities(
    user: AuthUser,
    db: DBSession,
    page: int = Query(default=1, ge=1, le=100_000),
    page_size: int = Query(default=50, ge=1, le=200),
    client_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    source: str | None = Query(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$", description="Only people this tool knows."),
    only_in: str | None = Query(
        default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$", description="Only people known to this one tool and no other."
    ),
    has_alerts: bool = Query(default=False),
    backup: str | None = Query(
        default=None,
        pattern="^(ok|problem|none)$",
        description="ok: every backup tool is fine; problem: some backup tool reports one; none: no backup tool knows the person.",
    ),
    alert_source: str | None = Query(
        default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$", description="Only people with an open alert from this tool."
    ),
    exposed: str | None = Query(
        default=None,
        pattern="^(any|serious)$",
        description="any: the address was found in a breach; serious: with a password, a stealer log or malware.",
    ),
    mfa: str | None = Query(default=None, pattern="^(covered|registered_not_required|none|unknown)$"),
    admin: bool = Query(default=False),
    disabled: bool = Query(default=False),
    kind: str | None = Query(default=None, pattern="^(user|guest|shared|other)$"),
    sort: str = Query(default="alerts"),
) -> IdentityList:
    """The people across the connected tools, with the tools that know each, their multi-factor state and their open alerts. The summary counts everyone in scope, whatever the filters."""
    if sort not in SORTS:
        raise HTTPException(status_code=422, detail=f"sort must be one of: {', '.join(SORTS)}")
    people, _ = await _people(db, user.tenant_id, client_id)
    rows = sort_people(
        filter_people(
            people,
            search=search,
            source=source,
            only_in=only_in,
            has_alerts=has_alerts,
            alert_source=alert_source,
            backup=backup,
            exposed=exposed,
            mfa=mfa,
            admin=admin,
            disabled=disabled,
            kind=kind,
        ),
        sort,
    )
    total = len(rows)
    start = (page - 1) * page_size
    items = [_out(p) for p in rows[start : start + page_size]]
    return IdentityList(
        summary=summarize(people),
        items=await with_ticket_counts(db, items),
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


def people_csv(rows: list[PersonOut]) -> str:
    """The people as CSV: client, address, name, kind, state, multi-factor, tools and open alerts. A cell that would run as a formula is made text."""
    import csv
    import io

    from app.api.v1.endpoints.devices import csv_cell

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Client", "Address", "Name", "Kind", "Enabled", "Administrator", "Multi-factor", "Known to", "Open alerts"])
    for p in rows:
        writer.writerow(
            [
                csv_cell(p.client_name),
                csv_cell(p.email),
                csv_cell(p.display_name),
                csv_cell(p.kind),
                "" if p.enabled is None else ("yes" if p.enabled else "no"),
                "yes" if p.admin else "no",
                csv_cell(p.mfa),
                csv_cell(", ".join(sorted(p.tools))),
                p.open_alerts,
            ]
        )
    return out.getvalue()


@router.get(
    "/export.csv", summary="The people the page is showing, as a CSV file", dependencies=[Depends(require_permission("alerts:read"))]
)
async def export_identities(
    user: AuthUser,
    db: DBSession,
    client_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    source: str | None = Query(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$"),
    only_in: str | None = Query(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$"),
    has_alerts: bool = Query(default=False),
    backup: str | None = Query(default=None, pattern="^(ok|problem|none)$"),
    alert_source: str | None = Query(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$"),
    exposed: str | None = Query(default=None, pattern="^(any|serious)$"),
    mfa: str | None = Query(default=None, pattern="^(covered|registered_not_required|none|unknown)$"),
    admin: bool = Query(default=False),
    disabled: bool = Query(default=False),
    kind: str | None = Query(default=None, pattern="^(user|guest|shared|other)$"),
    sort: str = Query(default="alerts"),
) -> Response:
    if sort not in SORTS:
        raise HTTPException(status_code=422, detail=f"sort must be one of: {', '.join(SORTS)}")
    people, _ = await _people(db, user.tenant_id, client_id)
    rows = sort_people(
        filter_people(
            people,
            search=search,
            source=source,
            only_in=only_in,
            has_alerts=has_alerts,
            alert_source=alert_source,
            backup=backup,
            exposed=exposed,
            mfa=mfa,
            admin=admin,
            disabled=disabled,
            kind=kind,
        ),
        sort,
    )
    return Response(
        content=people_csv([_out(p) for p in rows]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="identities.csv"'},
    )


class AlertBrief(BaseModel):
    id: uuid.UUID
    title: str
    severity: str
    status: str
    source: str | None = None
    created_at: datetime | None = None


class SigninBrief(BaseModel):
    last_30_days: int = 0
    failed: int = 0
    unusual: int = 0
    countries: list[str] = Field(default_factory=list)
    last_at: datetime | None = None


class TicketBrief(BaseModel):
    id: str
    summary: str
    status: str | None = None
    opened_at: datetime
    closed_at: datetime | None = None
    url: str | None = None
    source: str


TICKETS_SHOWN = 5
SIGNINS_SHOWN = 10
CHANGES_SHOWN = 10


class SigninRow(BaseModel):
    at: datetime
    app: str | None = None
    country: str | None = None
    city: str | None = None
    ip: str | None = None
    success: bool
    mfa: bool | None = None
    unusual: bool = False


class ChangeRow(BaseModel):
    at: datetime
    activity: str
    actor: str
    target: str | None = None
    detail: str | None = None
    success: bool = True


async def _tolerant(db: Any, statement: Any) -> list[Any]:
    """Rows for a part of the person's panel that must never stop the rest from loading: a table or column an older database does not have yet (a migration waiting for the next restart) gives an empty list."""
    try:
        async with db.begin_nested():
            return list((await db.execute(statement)).scalars().all())
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("identity panel: a section could not be read", exc_info=True)
        return []


def attach_ticket_counts(items: list[PersonOut], counts: dict[tuple[uuid.UUID, str], tuple[int, datetime]]) -> list[PersonOut]:
    """The people with their ticket count and newest ticket, matched on the client and the lower-case address (the way the tickets are stored)."""
    out = []
    for p in items:
        n, newest = counts.get((p.client_id, p.email.lower()), (0, None))
        out.append(p.model_copy(update={"tickets": n, "last_ticket_at": newest}) if n else p)
    return out


async def with_ticket_counts(db: Any, items: list[PersonOut]) -> list[PersonOut]:
    """One grouped read for the people on this page. A database that does not have the table yet (a migration waiting for the next restart) shows no tickets and the list still loads."""
    if not items:
        return items
    tenants = {p.client_id for p in items}
    emails = {p.email.lower() for p in items}
    try:
        async with cross_tenant_reads(db), db.begin_nested():
            rows = (
                await db.execute(
                    select(PersonTicket.tenant_id, PersonTicket.user_email, func.count(), func.max(PersonTicket.opened_at))
                    .where(PersonTicket.tenant_id.in_(tenants), PersonTicket.user_email.in_(emails))
                    .group_by(PersonTicket.tenant_id, PersonTicket.user_email)
                )
            ).all()
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("identity list: ticket counts could not be read", exc_info=True)
        return items
    return attach_ticket_counts(items, {(t, e): (n, newest) for t, e, n, newest in rows})


def signin_rows(events: list[Any]) -> list[SigninRow]:
    """The person's latest sign-ins, newest first."""
    latest = sorted(events, key=lambda e: e.occurred_at, reverse=True)[:SIGNINS_SHOWN]
    return [
        SigninRow(
            at=e.occurred_at,
            app=e.app,
            country=e.country,
            city=e.city,
            ip=e.ip_address,
            success=e.success,
            mfa=e.mfa,
            unusual=e.anomaly_score is not None,
        )
        for e in latest
    ]


class PersonDetail(BaseModel):
    person: PersonOut
    alerts: list[AlertBrief]
    signins: SigninBrief
    tickets: list[TicketBrief] = Field(default_factory=list)
    recent_signins: list[SigninRow] = Field(default_factory=list)
    changes: list[ChangeRow] = Field(default_factory=list)


@router.get("/detail", response_model=PersonDetail, dependencies=[Depends(require_permission("alerts:read"))])
async def identity_detail(
    user: AuthUser, db: DBSession, client_id: uuid.UUID, email: Annotated[str, Query(max_length=320)]
) -> PersonDetail:
    """One person: every tool's record of them, the open alerts that name them, and a summary of their recent sign-ins."""
    wanted = normalize_email(email)
    if wanted is None:
        raise HTTPException(status_code=422, detail="That is not an e-mail address")
    people, alerts = await _people(db, user.tenant_id, client_id)
    found = next((p for p in people if p.email == wanted and p.tenant_id == client_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="No such person")
    since = datetime.now(UTC) - timedelta(days=30)
    async with cross_tenant_reads(db):
        events = (
            (
                await db.execute(
                    select(SigninEvent).where(
                        SigninEvent.tenant_id == client_id,
                        func.lower(SigninEvent.user_principal) == wanted,
                        SigninEvent.occurred_at >= since,
                    )
                )
            )
            .scalars()
            .all()
        )
    brief = SigninBrief(
        last_30_days=len(events),
        failed=sum(1 for e in events if not e.success),
        unusual=sum(1 for e in events if e.anomaly_score is not None),
        countries=sorted({e.country for e in events if e.country})[:12],
        last_at=max((e.occurred_at for e in events), default=None),
    )
    rows = alerts.get(found.key, [])[:25]
    async with cross_tenant_reads(db):
        change_rows = await _tolerant(
            db,
            select(DirectoryAuditEvent)
            .where(
                DirectoryAuditEvent.tenant_id == client_id,
                DirectoryAuditEvent.occurred_at >= since,
                or_(func.lower(DirectoryAuditEvent.target) == wanted, func.lower(DirectoryAuditEvent.actor) == wanted),
            )
            .order_by(DirectoryAuditEvent.occurred_at.desc())
            .limit(CHANGES_SHOWN),
        )
        ticket_rows = await _tolerant(
            db,
            select(PersonTicket)
            .where(PersonTicket.tenant_id == client_id, PersonTicket.user_email == wanted)
            .order_by(PersonTicket.opened_at.desc())
            .limit(TICKETS_SHOWN),
        )
    return PersonDetail(
        person=_out(found, with_sources=True),
        alerts=[
            AlertBrief(
                id=a.id,
                title=a.title,
                severity=a.severity,
                status=a.status,
                source=(a.raw_event or {}).get("source") if isinstance(a.raw_event, dict) else None,
                created_at=a.created_at,
            )
            for a in rows
        ],
        signins=brief,
        recent_signins=signin_rows(events),
        changes=[
            ChangeRow(at=c.occurred_at, activity=c.activity, actor=c.actor, target=c.target, detail=c.detail, success=c.success)
            for c in change_rows
        ],
        tickets=[
            TicketBrief(
                id=t.ticket_id, summary=t.summary, status=t.status, opened_at=t.opened_at, closed_at=t.closed_at, url=t.url, source=t.source
            )
            for t in ticket_rows
        ],
    )


# ---- CORE reports the people of each tool ------------------------------------------------------------------------------------------------------------------


class IdentityIn(BaseModel):
    vendor_client_id: str | None = Field(default=None, max_length=200)
    external_id: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None
    kind: str = Field(default="user", pattern="^(user|guest|shared|other)$")
    details: dict[str, Any] = Field(default_factory=dict)


class IdentitiesReport(BaseModel):
    vendor: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    items: list[IdentityIn] = Field(max_length=1000)


class _View:
    """Lets the shared client mapping place a report's people (it reads ``vendor`` and ``items``)."""

    def __init__(self, report: IdentitiesReport) -> None:
        self.vendor = report.vendor
        self.items = report.items


async def apply_identities(db: Any, owner: uuid.UUID, report: IdentitiesReport) -> DevicesResponse:
    """Store each person under the client their tool client id is mapped to; skip (and count) those whose client is not mapped yet. The caller owns the transaction."""
    from app.api.v1.endpoints.signins import targets_by_tenant

    by_tenant, unmapped, ignored, waiting = await targets_by_tenant(db, owner, _View(report))  # type: ignore[arg-type]
    now = datetime.now(UTC)
    accepted = 0
    for tid, items in by_tenant.items():
        async with acting_as_tenant(db, tid):
            for it in items:
                email = normalize_email(it.email)
                if email is None:
                    continue
                values = {
                    "tenant_id": tid,
                    "vendor": report.vendor,
                    "external_id": it.external_id,
                    "email": email,
                    "display_name": it.display_name,
                    "enabled": it.enabled,
                    "kind": it.kind,
                    "details": it.details,
                    "refreshed_at": now,
                }
                stmt = pg_insert(IdentitySource).values(values)
                update = {c: stmt.excluded[c] for c in values if c not in ("tenant_id", "vendor", "external_id")}
                await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "vendor", "external_id"], set_=update))
                accepted += 1
    return DevicesResponse(
        accepted=accepted,
        unmapped=unmapped,
        ignored=ignored,
        unmapped_clients=[UnmappedClient(vendor_client_id=w.vendor_client_id, name=w.name, devices=w.devices) for w in waiting],
    )


@ingest_router.post("/core-feed/{tenant_token}/identities", response_model=DevicesResponse)
async def report_core_feed_identities(tenant_token: str, body: IdentitiesReport, db: DBSession) -> DevicesResponse:
    """Record the people a tool reports, under the client each belongs to."""
    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    result = await apply_identities(db, owner, body)
    await db.commit()
    return result


# ---- CORE reports each person's recent tickets -------------------------------------------------------------------------------------------------------------

MAX_TICKETS = 500
TICKET_DAYS = 90


class PersonTicketIn(BaseModel):
    vendor_client_id: str | None = Field(default=None, max_length=200)
    id: str = Field(min_length=1, max_length=40)
    summary: str = Field(min_length=1, max_length=300)
    status: str | None = Field(default=None, max_length=80)
    opened_at: datetime
    updated_at: datetime | None = None
    closed_at: datetime | None = None
    user_email: str = Field(min_length=3, max_length=320)
    user_name: str | None = Field(default=None, max_length=255)
    url: str | None = Field(default=None, max_length=500)


class PersonTicketsReport(BaseModel):
    vendor: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    items: list[PersonTicketIn] = Field(max_length=MAX_TICKETS)


class PersonTicketsResponse(BaseModel):
    accepted: int
    unmapped: int = 0
    ignored: int = 0
    unmapped_clients: list[UnmappedClient] = Field(default_factory=list)


async def apply_person_tickets(
    db: Any, owner: uuid.UUID, report: PersonTicketsReport, now: datetime | None = None
) -> PersonTicketsResponse:
    """Store each ticket under the client its tool client id is mapped to (a ticket whose client is not mapped yet is counted and skipped), and forget those older than 90 days. The caller owns the transaction."""
    from app.api.v1.endpoints.signins import targets_by_tenant

    now = now or datetime.now(UTC)
    by_tenant, unmapped, ignored, waiting = await targets_by_tenant(db, owner, report)  # type: ignore[arg-type]
    accepted = 0
    for tid, items in by_tenant.items():
        async with acting_as_tenant(db, tid):
            values = []
            seen: set[str] = set()
            for it in items:
                email = normalize_email(it.user_email)
                if email is None or it.id in seen:
                    continue
                seen.add(it.id)
                values.append(
                    {
                        "tenant_id": tid,
                        "source": report.vendor,
                        "ticket_id": it.id,
                        "summary": it.summary,
                        "status": it.status,
                        "opened_at": it.opened_at if it.opened_at.tzinfo else it.opened_at.replace(tzinfo=UTC),
                        "updated_at": it.updated_at,
                        "closed_at": (it.closed_at if it.closed_at.tzinfo else it.closed_at.replace(tzinfo=UTC)) if it.closed_at else None,
                        "user_email": email,
                        "user_name": it.user_name,
                        "url": it.url,
                        "received_at": now,
                    }
                )
            if values:
                stmt = pg_insert(PersonTicket).values(values)
                update = {c: stmt.excluded[c] for c in values[0] if c not in ("tenant_id", "source", "ticket_id")}
                await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "source", "ticket_id"], set_=update))
                accepted += len(values)
            await db.execute(
                delete(PersonTicket).where(PersonTicket.tenant_id == tid, PersonTicket.opened_at < now - timedelta(days=TICKET_DAYS))
            )
    return PersonTicketsResponse(
        accepted=accepted,
        unmapped=unmapped,
        ignored=ignored,
        unmapped_clients=[UnmappedClient(vendor_client_id=w.vendor_client_id, name=w.name, devices=w.devices) for w in waiting],
    )


@ingest_router.post("/core-feed/{tenant_token}/person-tickets", response_model=PersonTicketsResponse)
async def report_core_feed_person_tickets(tenant_token: str, body: PersonTicketsReport, db: DBSession) -> PersonTicketsResponse:
    """Record each person's recent tickets, under the client each belongs to."""
    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    result = await apply_person_tickets(db, owner, body)
    await db.commit()
    return result

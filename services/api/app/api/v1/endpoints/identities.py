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
from app.models.identity_merge import IdentityMerge
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
    counts_as,
    filter_people,
    is_active,
    never_expires,
    normalize_email,
    sort_people,
)
from app.services.timeutil import as_utc, as_utc_or_none

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


class AliasOut(BaseModel):
    email: str
    reason: str


class BecBadge(BaseModel):
    """The newest business email compromise search for any of the person's addresses: how it stands, CIPP's own rating when it finished, and when it was started."""

    status: str  # pending, running, done or failed (an open one nobody reported on for a long time is failed)
    level: str | None = None
    at: datetime


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
    # Password set never to expire (true / false), or null when CIPP's user list could not say.
    password_never_expires: bool | None = None
    # Last sign-in: active / inactive (90+ days) / never, or null when the client's sign-in data is not available.
    signin_state: str | None = None
    days_since_signin: int | None = None
    tools: list[str]
    sources: list[SourceOut] = Field(default_factory=list)
    open_alerts: int = 0
    top_severity: str | None = None
    alerts_by_source: dict[str, int] = Field(default_factory=dict)
    backups: list[BackupOut] = Field(default_factory=list)
    exposure: ExposureOut | None = None
    # Against the client's HaloPSA users: "cloud_not_in_halo" (an enabled cloud account no Halo user matches) or "halo_inactive_cloud_enabled" (Halo says they are gone, the cloud account is on). Null otherwise.
    halo_check: str | None = None
    # HaloPSA tickets about this person in the window CORE reads, and when the newest was opened (the list page only; the person's own panel lists the tickets).
    tickets: int = 0
    last_ticket_at: datetime | None = None
    # The other addresses of this same human, folded into this row, each with why (a rule, or "merged by hand").
    aliases: list[AliasOut] = Field(default_factory=list)
    # The newest BEC search for any of this person's addresses, on the list page only.
    bec: BecBadge | None = None


class IdentitySummary(BaseModel):
    total: int
    with_alerts: int
    without_mfa: int
    admins: int
    disabled: int
    # People known to only one tool (so no other tool has them): the ones to look at when a tool is missing someone.
    in_one_tool: int
    # Cloud accounts that need a look against HaloPSA (see Person.halo_check).
    cloud_not_in_halo: int = 0
    halo_inactive_cloud_enabled: int = 0
    tools: dict[str, int] = Field(default_factory=dict)
    # How many people have an open alert from each tool, so the page can offer them as a filter.
    alert_sources: dict[str, int] = Field(default_factory=dict)
    # People a backup tool reports a problem for (no recent backup, an error, paused or unprotected).
    backup_problems: int = 0
    # People whose address turned up in a breach, and those where it was serious (a password, a stealer log or malware).
    exposed: int = 0
    exposed_serious: int = 0
    # Guests (people from outside the organization with an account in it).
    guests: int = 0
    # Active identities: a licensed Microsoft 365 or Google account, not a guest, not disabled (identity_people.is_active).
    active: int = 0
    # Failed password sign-ins in the last 24 hours across the people in scope, and the people with BRUTE_FORCE_FAILURES or more of them. Steps that only ask for more proof (MFA prompts) are not failures.
    failed_signins_24h: int = 0
    brute_force: int = 0
    # People Microsoft turned away in the last 24 hours because the account is locked out (error 50053: too many wrong passwords, so it refuses even the right one).
    locked_out: int = 0
    # Working accounts whose password is set never to expire, and how many accounts CIPP could say it for (the rest are unknown, not "expires").
    password_never_expires: int = 0
    password_policy_known: int = 0
    # Working own accounts with no sign-in for 90+ days, and ones with none on record; and how many accounts the client's sign-in data covered (the rest are unknown, not "active").
    inactive_90: int = 0
    never_signed_in: int = 0
    signin_state_known: int = 0


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
        password_never_expires=p.password_never_expires,
        signin_state=p.signin_state,
        days_since_signin=p.days_since_signin,
        tools=p.vendors,
        aliases=[AliasOut(email=a, reason=p.alias_reasons.get(a, "merged")) for a in p.aliases],
        sources=[SourceOut(vendor=s.vendor, external_id=s.external_id, enabled=s.enabled, details=s.details) for s in p.sources]
        if with_sources
        else [],
        open_alerts=p.open_alerts,
        top_severity=p.top_severity,
        alerts_by_source=p.alerts_by_source,
        halo_check=p.halo_check,
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


BRUTE_FORCE_FAILURES = 10
# Microsoft "errors" that are the sign-in asking for more (MFA, enrolment, a challenge, "stay signed in?"), not a wrong password or a refusal.
NOT_FAILURES = (50072, 50074, 50076, 50140, 50158)


async def signin_failures(db: Any, scope: Any, now: datetime) -> tuple[int, int]:
    """(failed sign-ins in the last 24 hours, people with BRUTE_FORCE_FAILURES or more of them) for the tenants in scope."""
    async with cross_tenant_reads(db):
        rows = (
            await db.execute(
                select(SigninEvent.user_principal, func.count())
                .where(
                    SigninEvent.tenant_id.in_(scope),
                    SigninEvent.success.is_(False),
                    SigninEvent.occurred_at >= now - timedelta(hours=24),
                    or_(SigninEvent.error_code.is_(None), SigninEvent.error_code.notin_(NOT_FAILURES)),
                )
                .group_by(SigninEvent.user_principal)
            )
        ).all()
    return sum(n for _, n in rows), sum(1 for _, n in rows if n >= BRUTE_FORCE_FAILURES)


async def failing_people(db: Any, scope: Any, now: datetime, minimum: int) -> set[tuple[uuid.UUID, str]]:
    """The (client, address) of each person with at least ``minimum`` failed sign-ins in the last 24 hours: 1 is "failed sign-ins", BRUTE_FORCE_FAILURES is "possible brute force". The same rows and the same
    exclusions as ``signin_failures``, so the list a tile opens holds exactly the people the tile counted."""
    async with cross_tenant_reads(db):
        rows = (
            await db.execute(
                select(SigninEvent.tenant_id, SigninEvent.user_principal, func.count())
                .where(
                    SigninEvent.tenant_id.in_(scope),
                    SigninEvent.success.is_(False),
                    SigninEvent.occurred_at >= now - timedelta(hours=24),
                    or_(SigninEvent.error_code.is_(None), SigninEvent.error_code.notin_(NOT_FAILURES)),
                )
                .group_by(SigninEvent.tenant_id, SigninEvent.user_principal)
            )
        ).all()
    counts: dict[tuple[uuid.UUID, str], int] = {}
    for tenant, principal, n in rows:
        key = (tenant, str(principal or "").lower())
        counts[key] = counts.get(key, 0) + int(n)
    return {k for k, n in counts.items() if n >= minimum}


# Microsoft's error for an account locked out by too many wrong passwords ("smart lockout"). Every sign-in it refuses after that carries it, even with the right password.
LOCKED_OUT_ERROR = 50053


async def locked_out_people(db: Any, scope: Any, now: datetime) -> set[tuple[uuid.UUID, str]]:
    """The (client, address) of each person with a sign-in refused as locked out in the last 24 hours. A person who signed in successfully AFTER the last refusal is no longer locked out and is left out."""
    async with cross_tenant_reads(db):
        rows = (
            await db.execute(
                select(
                    SigninEvent.tenant_id,
                    SigninEvent.user_principal,
                    func.max(SigninEvent.occurred_at).filter(SigninEvent.error_code == LOCKED_OUT_ERROR),
                    func.max(SigninEvent.occurred_at).filter(SigninEvent.success.is_(True)),
                )
                .where(SigninEvent.tenant_id.in_(scope), SigninEvent.occurred_at >= now - timedelta(hours=24))
                .group_by(SigninEvent.tenant_id, SigninEvent.user_principal)
            )
        ).all()
    out: set[tuple[uuid.UUID, str]] = set()
    for tenant, principal, locked_at, ok_at in rows:
        if locked_at is not None and (ok_at is None or ok_at < locked_at):
            out.add((tenant, str(principal or "").lower()))
    return out


async def signin_filter_people(db: Any, scope: Any, now: datetime, which: str) -> set[tuple[uuid.UUID, str]]:
    """The people a sign-in tile or filter value stands for: failed, brute_force or locked_out."""
    if which == "locked_out":
        return await locked_out_people(db, scope, now)
    return await failing_people(db, scope, now, 1 if which == "failed" else BRUTE_FORCE_FAILURES)


async def owner_decisions(db: Any, scope: Any) -> tuple[list[tuple[uuid.UUID, str, str]], list[tuple[uuid.UUID, str, str]]]:
    """The owner's hand merges and "not the same person" marks for the clients in scope, as (client, address, address)."""
    async with cross_tenant_reads(db):
        rows = (await db.execute(select(IdentityMerge).where(IdentityMerge.tenant_id.in_(scope)))).scalars().all()
    merges = [(r.tenant_id, r.address_a, r.address_b) for r in rows if r.kind == "merge"]
    separate = [(r.tenant_id, r.address_a, r.address_b) for r in rows if r.kind == "separate"]
    return merges, separate


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
    merges, separate = await owner_decisions(db, scope)
    people = add_alert_sources(
        build_people(names, list(users), list(sources), now, merges=merges, separate=separate), named, names, source_of
    )
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
        cloud_not_in_halo=sum(1 for p in people if p.halo_check == "cloud_not_in_halo"),
        halo_inactive_cloud_enabled=sum(1 for p in people if p.halo_check == "halo_inactive_cloud_enabled"),
        tools=dict(sorted(tools.items())),
        alert_sources=dict(sorted(alert_sources.items())),
        backup_problems=sum(1 for p in people if p.enabled is not False and any(b.status != "ok" for b in p.backups)),
        exposed=sum(1 for p in people if p.exposure is not None),
        guests=sum(1 for p in people if p.kind == "guest"),
        active=sum(1 for p in people if is_active(p)),
        password_never_expires=sum(1 for p in people if never_expires(p)),
        password_policy_known=sum(1 for p in people if p.password_never_expires is not None),
        inactive_90=sum(1 for p in people if counts_as(p, "inactive")),
        never_signed_in=sum(1 for p in people if counts_as(p, "never")),
        signin_state_known=sum(1 for p in people if p.signin_state is not None),
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
    halo_check: str | None = Query(
        default=None,
        pattern="^(cloud_not_in_halo|halo_inactive_cloud_enabled)$",
        description="Only people whose cloud account needs a look against the client's HaloPSA users.",
    ),
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
    enabled: bool = Query(default=False, description="Only accounts that are not disabled."),
    active: bool = Query(default=False, description="Only active identities: a licensed account, not a guest, not disabled."),
    kind: str | None = Query(default=None, pattern="^(user|guest|shared|other)$"),
    password_never_expires: bool = Query(
        default=False, description="Only working accounts whose password is set never to expire (the tile's list)."
    ),
    inactivity: str | None = Query(
        default=None,
        pattern="^(inactive|never)$",
        description="inactive: working accounts with no sign-in for 90+ days; never: no sign-in on record (the two tiles' lists). Unknown is never listed.",
    ),
    signin: str | None = Query(
        default=None,
        pattern="^(failed|brute_force|locked_out)$",
        description="failed: at least one failed sign-in in the last 24 hours; brute_force: ten or more; locked_out: refused as locked out and not signed in since (the three tiles' lists).",
    ),
    sort: str = Query(default="alerts"),
) -> IdentityList:
    """The people across the connected tools, with the tools that know each, their multi-factor state and their open alerts. The summary counts everyone in scope, whatever the filters."""
    if sort not in SORTS:
        raise HTTPException(status_code=422, detail=f"sort must be one of: {', '.join(SORTS)}")
    people, _ = await _people(db, user.tenant_id, client_id)
    scope, _clients = await _scope(db, user.tenant_id, client_id)
    failed, brute = await signin_failures(db, scope, datetime.now(UTC))
    locked = await locked_out_people(db, scope, datetime.now(UTC))
    if signin:
        failing = await signin_filter_people(db, scope, datetime.now(UTC), signin)
        people_in_filter = [p for p in people if any((p.tenant_id, a.lower()) in failing for a in p.addresses)]
    else:
        people_in_filter = people
    rows = sort_people(
        filter_people(
            people_in_filter,
            search=search,
            source=source,
            only_in=only_in,
            has_alerts=has_alerts,
            halo_check=halo_check,
            alert_source=alert_source,
            backup=backup,
            exposed=exposed,
            mfa=mfa,
            admin=admin,
            disabled=disabled,
            enabled=enabled,
            active=active,
            kind=kind,
            password_never_expires=password_never_expires,
            inactivity=inactivity,
        ),
        sort,
    )
    total = len(rows)
    start = (page - 1) * page_size
    items = [_out(p) for p in rows[start : start + page_size]]
    return IdentityList(
        summary=summarize(people).model_copy(
            update={
                "failed_signins_24h": failed,
                "brute_force": brute,
                "locked_out": sum(1 for p in people if any((p.tenant_id, a.lower()) in locked for a in p.addresses)),
            }
        ),
        items=await with_bec_badges(db, await with_ticket_counts(db, items)),
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
    halo_check: str | None = Query(
        default=None,
        pattern="^(cloud_not_in_halo|halo_inactive_cloud_enabled)$",
        description="Only people whose cloud account needs a look against the client's HaloPSA users.",
    ),
    backup: str | None = Query(default=None, pattern="^(ok|problem|none)$"),
    alert_source: str | None = Query(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$"),
    exposed: str | None = Query(default=None, pattern="^(any|serious)$"),
    mfa: str | None = Query(default=None, pattern="^(covered|registered_not_required|none|unknown)$"),
    admin: bool = Query(default=False),
    disabled: bool = Query(default=False),
    enabled: bool = Query(default=False, description="Only accounts that are not disabled."),
    active: bool = Query(default=False, description="Only active identities: a licensed account, not a guest, not disabled."),
    kind: str | None = Query(default=None, pattern="^(user|guest|shared|other)$"),
    signin: str | None = Query(default=None, pattern="^(failed|brute_force|locked_out)$"),
    password_never_expires: bool = Query(default=False, description="Only working accounts whose password is set never to expire."),
    inactivity: str | None = Query(default=None, pattern="^(inactive|never)$"),
    sort: str = Query(default="alerts"),
) -> Response:
    if sort not in SORTS:
        raise HTTPException(status_code=422, detail=f"sort must be one of: {', '.join(SORTS)}")
    people, _ = await _people(db, user.tenant_id, client_id)
    if signin:
        scope, _clients = await _scope(db, user.tenant_id, client_id)
        failing = await signin_filter_people(db, scope, datetime.now(UTC), signin)
        people = [p for p in people if any((p.tenant_id, a.lower()) in failing for a in p.addresses)]
    rows = sort_people(
        filter_people(
            people,
            search=search,
            source=source,
            only_in=only_in,
            has_alerts=has_alerts,
            halo_check=halo_check,
            alert_source=alert_source,
            backup=backup,
            exposed=exposed,
            mfa=mfa,
            admin=admin,
            disabled=disabled,
            enabled=enabled,
            active=active,
            kind=kind,
            password_never_expires=password_never_expires,
            inactivity=inactivity,
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


def attach_bec(items: list[PersonOut], cases: dict[tuple[uuid.UUID, str], tuple[str, str | None, datetime]]) -> list[PersonOut]:
    """Each person with their newest BEC search, looked up by the client and every address they are known by (a search may have been made for an alias), the newest start winning."""
    out = []
    for p in items:
        addresses = [p.email, *(a.email for a in p.aliases)]
        found = [cases[(p.client_id, a.lower())] for a in addresses if (p.client_id, a.lower()) in cases]
        if not found:
            out.append(p)
            continue
        status, level, at = max(found, key=lambda c: c[2])
        out.append(p.model_copy(update={"bec": BecBadge(status=status, level=level, at=at)}))
    return out


async def with_bec_badges(db: Any, items: list[PersonOut]) -> list[PersonOut]:
    """One read for the people on this page: their newest BEC search each. A database without the table yet shows no badge and the list still loads."""
    if not items:
        return items
    from app.api.v1.endpoints.identity_bec import effective_status  # noqa: PLC0415
    from app.models.bec_case import BecCase  # noqa: PLC0415

    tenants = {p.client_id for p in items}
    emails = {a.lower() for p in items for a in [p.email, *(x.email for x in p.aliases)]}
    now = datetime.now(UTC)
    try:
        async with cross_tenant_reads(db), db.begin_nested():
            rows = (
                (
                    await db.execute(
                        select(BecCase)
                        .where(BecCase.tenant_id.in_(tenants), func.lower(BecCase.email).in_(emails))
                        .order_by(BecCase.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("identity list: BEC searches could not be read", exc_info=True)
        return items
    newest: dict[tuple[uuid.UUID, str], tuple[str, str | None, datetime]] = {}
    for r in rows:
        key = (r.tenant_id, r.email.lower())
        if key in newest:
            continue
        status, _message = effective_status(r, now)
        level = (r.summary or {}).get("level") if status == "done" else None
        newest[key] = (status, level if isinstance(level, str) else None, r.created_at)
    return attach_bec(items, newest)


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


class DuplicateOut(BaseModel):
    client_id: uuid.UUID
    client_name: str | None
    a: PersonOut
    b: PersonOut
    score: int
    confidence: str  # high or medium
    reasons: list[str]
    both_licensed: bool  # two paid seats: merging is a deliberate choice


class DuplicatesOut(BaseModel):
    items: list[DuplicateOut]
    total: int


@router.get(
    "/duplicates",
    response_model=DuplicatesOut,
    dependencies=[Depends(require_permission("alerts:read"))],
    summary="Pairs of people of one client who may be the same human, that no automatic rule joined",
)
async def list_duplicates(
    user: AuthUser,
    db: DBSession,
    client_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> DuplicatesOut:
    """Likely-but-uncertain pairs, strongest first: the same name, or the same name before the @ on another domain, inside one client. A pair the owner marked "not the same person" is left out; confirming one
    is the existing Merge (POST /identities/merges) and dismissing one is the existing Not the same person (POST /identities/merges/separate). Nothing here changes anything."""
    from app.services.identity_duplicates import find_duplicates  # noqa: PLC0415

    people, _ = await _people(db, user.tenant_id, client_id)
    scope, _clients = await _scope(db, user.tenant_id, client_id)
    _merges, separate = await owner_decisions(db, scope)
    found = find_duplicates(people, separate, limit)
    return DuplicatesOut(
        items=[
            DuplicateOut(
                client_id=p.client_id,
                client_name=p.a.client_name,
                a=_out(p.a),
                b=_out(p.b),
                score=p.score,
                confidence=p.label,
                reasons=p.reasons,
                both_licensed=p.both_licensed,
            )
            for p in found
        ],
        total=len(found),
    )


@router.get("/detail", response_model=PersonDetail, dependencies=[Depends(require_permission("alerts:read"))])
async def identity_detail(
    user: AuthUser, db: DBSession, client_id: uuid.UUID, email: Annotated[str, Query(max_length=320)]
) -> PersonDetail:
    """One person: every tool's record of them, the open alerts that name them, and a summary of their recent sign-ins."""
    wanted = normalize_email(email)
    if wanted is None:
        raise HTTPException(status_code=422, detail="That is not an e-mail address")
    people, alerts = await _people(db, user.tenant_id, client_id)
    found = next((p for p in people if p.tenant_id == client_id and wanted in p.addresses), None)
    if found is None:
        raise HTTPException(status_code=404, detail="No such person")
    addresses = found.addresses
    since = datetime.now(UTC) - timedelta(days=30)
    async with cross_tenant_reads(db):
        events = (
            (
                await db.execute(
                    select(SigninEvent).where(
                        SigninEvent.tenant_id == client_id,
                        func.lower(SigninEvent.user_principal).in_(addresses),
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
                or_(func.lower(DirectoryAuditEvent.target).in_(addresses), func.lower(DirectoryAuditEvent.actor).in_(addresses)),
            )
            .order_by(DirectoryAuditEvent.occurred_at.desc())
            .limit(CHANGES_SHOWN),
        )
        ticket_rows = await _tolerant(
            db,
            select(PersonTicket)
            .where(PersonTicket.tenant_id == client_id, PersonTicket.user_email.in_(addresses))
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
                        "opened_at": as_utc(it.opened_at),
                        "updated_at": as_utc_or_none(it.updated_at),
                        "closed_at": as_utc_or_none(it.closed_at),
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

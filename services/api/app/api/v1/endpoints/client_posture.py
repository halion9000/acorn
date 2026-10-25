"""One client's security posture on a single page: devices, second-factor coverage, open alerts and cases. Read-only; every number comes from data AiSOC already holds.

``GET /api/v1/client-posture/{client_id}``. The same figures are on the Devices, Multi-factor status, Alerts and Cases pages; this puts them side by side for a client review.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, bindparam, func, not_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.alerts import FINISHED_STATUSES, has_ticket_expr
from app.api.v1.endpoints.devices import ClientRollup, _load_cached, _master_of, _scope, rollup_of
from app.api.v1.endpoints.identity import counts_for_mfa
from app.db.rls_scope import acting_as_tenant
from app.models.alert import Alert
from app.models.client_alias import ClientAlias
from app.models.identity_source import IdentitySource
from app.models.signin import ClientCheckAcceptance, ClientCheckHistory, ClientM365Check, CoreSweepRun, IdentityMfaUser
from app.models.tenant import Tenant
from app.services.domain_posture import DohResolver, DomainPosture, Resolver, candidate_domains, check_domains
from app.services.web_posture import LiveProbe, WebPosture, WebProbe, web_posture
from app.services.infra_review import TOOL_CHECK_SOURCES, saas_products

router = APIRouter(prefix="/client-posture", tags=["posture"])

_CASE_FINISHED = ("resolved", "closed")


class PostureDevices(BaseModel):
    devices: int = 0
    needs_attention: int = 0
    stale_agents: int = 0
    not_in_huntress: int = 0
    offline: int = 0


class PostureIdentity(BaseModel):
    people: int
    with_mfa: int
    not_required: int
    without_mfa: int
    admins_without_mfa: int
    refreshed_at: datetime | None = None


class PostureAlerts(BaseModel):
    open: int
    critical: int
    high: int
    without_ticket: int


class PostureTool(BaseModel):
    """A tool this client is mapped to, and its id for the client in that tool (the id the tool's own page for the client is addressed by)."""

    vendor: str
    vendor_client_id: str
    vendor_client_name: str | None = None
    # What the tool protects for this client, when it says (Datto SaaS Protection: "microsoft", "google" or "both"), so a link can open the right page.
    product: str | None = None


class PostureCheck(BaseModel):
    """One plain check a tool reported for this client (ThreatMate's security score, patching, end-of-life software): met, partly or not met, and what it saw."""

    key: str
    status: str
    evidence: str
    # Since when the check has had this status (the last time it changed), when A.C.O.R.N has seen it change; None for a check seen only once, before history was kept.
    since: datetime | None = None
    # Set when a person has accepted this check for the client (and it has not run out).
    accepted: "CheckAcceptanceOut | None" = None


class CheckAcceptanceOut(BaseModel):
    reason: str
    accepted_at: datetime
    expires_at: datetime | None = None


class ToolChecksOut(BaseModel):
    checks: list[PostureCheck]
    refreshed_at: datetime | None = None


class ClientPosture(BaseModel):
    client_id: uuid.UUID
    client_name: str | None
    generated_at: datetime
    devices: PostureDevices
    # None when no multi-factor data has arrived for this client (CIPP not connected or not mapped).
    identity: PostureIdentity | None
    alerts: PostureAlerts
    open_cases: int
    # The tools this client is mapped to (Huntress, NinjaOne...), for the page to show and link to the client's page in each.
    tools: list[PostureTool] = []
    # What each tool says about the client as plain checks (ThreatMate, Liongard, IT Glue, Field Effect...), by the tool's source name; only tools the client is mapped to, and only once CORE has sent them.
    tool_checks: dict[str, ToolChecksOut] = {}


def devices_part(rollups: list[ClientRollup], client_id: uuid.UUID) -> PostureDevices:
    """The client's row of the device rollup, or zeros when it has no devices."""
    for r in rollups:
        if r.client_id == client_id:
            return PostureDevices(
                devices=r.devices,
                needs_attention=r.needs_attention,
                stale_agents=r.stale_agents,
                not_in_huntress=r.not_in_huntress,
                offline=r.offline,
            )
    return PostureDevices()


async def _all_tool_checks(db: Any, owner: uuid.UUID, client_id: uuid.UUID, aliases: list[Any]) -> dict[str, ToolChecksOut]:
    """The checks each tool sent for this client. Only tools the client is mapped to are read (none at all, no query, for a client mapped to none of them); a tool that sent nothing is left out."""
    mapped = {v for v, _, _ in aliases}
    sources = [source for source, vendor in TOOL_CHECK_SOURCES.items() if vendor in mapped]
    if not sources:
        return {}
    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        rows = (await db.execute(select(ClientM365Check).where(ClientM365Check.tenant_id == client_id, ClientM365Check.source.in_(sources)))).scalars().all()
        since_rows = (
            await db.execute(
                select(ClientCheckHistory.key, func.max(ClientCheckHistory.observed_at)).where(ClientCheckHistory.tenant_id == client_id, ClientCheckHistory.source.in_(sources)).group_by(ClientCheckHistory.key)
            )
        ).all()
        accepted_rows = (await db.execute(select(ClientCheckAcceptance).where(ClientCheckAcceptance.tenant_id == client_id))).scalars().all()
    since = {k: t for k, t in since_rows}
    now = datetime.now(UTC)
    accepted = {a.key: CheckAcceptanceOut(reason=a.reason, accepted_at=a.accepted_at, expires_at=a.expires_at) for a in accepted_rows if a.expires_at is None or a.expires_at > now}
    out: dict[str, ToolChecksOut] = {}
    for row in rows:
        checks = [
            PostureCheck(key=str(c["key"]), status=str(c["status"]), evidence=str(c.get("evidence", "")), since=since.get(str(c["key"])), accepted=accepted.get(str(c["key"])))
            for c in (row.checks or [])
            if isinstance(c, dict) and c.get("key") and c.get("status")
        ]
        if checks:
            out[row.source] = ToolChecksOut(checks=checks, refreshed_at=row.refreshed_at)
    return dict(sorted(out.items()))


@router.get(
    "/{client_id}", response_model=ClientPosture, summary="One client's devices, Multi-Factor coverage, open alerts and cases side by side"
)
async def client_posture(
    client_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession
) -> ClientPosture:
    owner = current_user.tenant_id
    if client_id != owner:
        found = (await db.execute(select(Tenant.id).where(Tenant.id == client_id, Tenant.parent_tenant_id == owner))).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=404, detail="Client not found")
    scope, clients = await _scope(db, owner, client_id)
    master = _master_of(await db.get(Tenant, owner))
    loaded = await _load_cached(db, owner, scope, clients, master)
    devices = devices_part(rollup_of([d for d in loaded if d.hidden_since is None]), client_id)

    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        users = (await db.execute(select(IdentityMfaUser).where(IdentityMfaUser.tenant_id == client_id))).scalars().all()
        row = (
            await db.execute(
                select(
                    func.count(),
                    func.count().filter(Alert.severity == "critical"),
                    func.count().filter(Alert.severity == "high"),
                    func.count().filter(not_(has_ticket_expr())),
                ).where(and_(Alert.tenant_id == client_id, Alert.status.notin_(FINISHED_STATUSES)))
            )
        ).one()
        cases = (
            await db.execute(
                text("SELECT count(*) FROM cases WHERE tenant_id = :t AND status NOT IN :done").bindparams(
                    bindparam("done", expanding=True)
                ),
                {"t": client_id, "done": list(_CASE_FINISHED)},
            )
        ).scalar_one()
    aliases = (
        await db.execute(
            select(ClientAlias.vendor, ClientAlias.vendor_client_id, ClientAlias.vendor_client_name)
            .where(ClientAlias.tenant_id == owner, ClientAlias.child_tenant_id == client_id, ClientAlias.ignored.is_(False))
            .order_by(ClientAlias.vendor, ClientAlias.vendor_client_name)
        )
    ).all()
    saas_checks: list[dict] = []
    if any(v == "datto-saas" for v, _, _ in aliases):
        async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
            saas_row = (
                (
                    await db.execute(
                        select(ClientM365Check).where(ClientM365Check.tenant_id == client_id, ClientM365Check.source == "datto-saas")
                    )
                )
                .scalars()
                .first()
            )
        saas_checks = [c for c in (saas_row.checks if saas_row is not None else []) if isinstance(c, dict)]
    tool_checks = await _all_tool_checks(db, owner, client_id, aliases)
    tools = [
        PostureTool(
            vendor=v, vendor_client_id=i, vendor_client_name=n or None, product=saas_products(saas_checks) if v == "datto-saas" else None
        )
        for v, i, n in aliases
    ]
    identity = PostureIdentity(refreshed_at=max(u.refreshed_at for u in users), **counts_for_mfa(list(users))) if users else None
    name = clients.get(client_id)
    return ClientPosture(
        client_id=client_id,
        client_name=name,
        generated_at=datetime.now(UTC),
        devices=devices,
        identity=identity,
        alerts=PostureAlerts(open=row[0], critical=row[1], high=row[2], without_ticket=row[3]),
        open_cases=cases,
        tools=tools,
        tool_checks=tool_checks,
    )


def get_resolver() -> Resolver:
    """The DNS resolver the domain checks use (replaced in tests)."""
    return DohResolver()


def get_probe() -> WebProbe:
    """What looks at a domain's website (replaced in tests)."""
    return LiveProbe()


class DomainWithWeb(DomainPosture):
    # What the domain's website shows; None when no website answered, which is normal for a mail-only domain.
    web: WebPosture | None = None


class ClientDomains(BaseModel):
    client_id: uuid.UUID
    # The domains looked at: those of the people held for the client, most used first.
    domains: list[DomainWithWeb]
    generated_at: datetime


@router.get("/{client_id}/domains", response_model=ClientDomains, summary="SPF, DMARC, DKIM and MX of the domains a client's people use")
async def client_domains(
    client_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession
) -> ClientDomains:
    """Looks the client's e-mail domains up in public DNS right now (nothing is stored). The domains are taken from the e-mail addresses of its people, so a client with none shows none."""
    owner = current_user.tenant_id
    if client_id != owner:
        found = (await db.execute(select(Tenant.id).where(Tenant.id == client_id, Tenant.parent_tenant_id == owner))).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=404, detail="Client not found")
    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        upns = (await db.execute(select(IdentityMfaUser.upn).where(IdentityMfaUser.tenant_id == client_id))).scalars().all()
        mails = (await db.execute(select(IdentitySource.email).where(IdentitySource.tenant_id == client_id))).scalars().all()
    checked = await check_domains(candidate_domains([*upns, *mails]), get_resolver())
    probe = get_probe()
    now = datetime.now(UTC)
    webs = await asyncio.gather(*(probe.probe(d.domain) for d in checked))
    domains = [DomainWithWeb(**d.model_dump(), web=web_posture(w, now)) for d, w in zip(checked, webs, strict=True)]
    return ClientDomains(client_id=client_id, domains=domains, generated_at=now)


# ---- history, accepted risks, and how CORE's sweeps are doing -----------------------------------------------------------------------------------------------------------


class CheckHistoryRow(BaseModel):
    key: str
    source: str
    status: str
    previous_status: str | None
    evidence: str
    observed_at: datetime


class CheckHistoryOut(BaseModel):
    client_id: uuid.UUID
    rows: list[CheckHistoryRow]


async def _client_of_owner(db: Any, owner: uuid.UUID, client_id: uuid.UUID) -> None:
    if client_id != owner:
        found = (await db.execute(select(Tenant.id).where(Tenant.id == client_id, Tenant.parent_tenant_id == owner))).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=404, detail="Client not found")


@router.get("/{client_id}/check-history", response_model=CheckHistoryOut, summary="When each of a client's tool checks appeared or changed status")
async def check_history(
    client_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
    key: str | None = None,
    limit: int = 200,
) -> CheckHistoryOut:
    owner = current_user.tenant_id
    await _client_of_owner(db, owner, client_id)
    limit = max(1, min(limit, 500))
    stmt = select(ClientCheckHistory).where(ClientCheckHistory.tenant_id == client_id)
    if key:
        stmt = stmt.where(ClientCheckHistory.key == key)
    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        rows = (await db.execute(stmt.order_by(ClientCheckHistory.observed_at.desc(), ClientCheckHistory.id.desc()).limit(limit))).scalars().all()
    return CheckHistoryOut(
        client_id=client_id,
        rows=[CheckHistoryRow(key=r.key, source=r.source, status=r.status, previous_status=r.previous_status, evidence=r.evidence, observed_at=r.observed_at) for r in rows],
    )


class AcceptIn(BaseModel):
    reason: str
    # Days from now until the acceptance runs out; none means until someone removes it.
    expires_in_days: int | None = None


MAX_ACCEPT_DAYS = 730
MAX_ACCEPTANCES_PER_CLIENT = 200


@router.put("/{client_id}/acceptances/{key}", response_model=CheckAcceptanceOut, summary="Accept a failing check for a client, with a reason and an optional end date")
async def accept_check(
    client_id: uuid.UUID, key: str, body: AcceptIn, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession
) -> CheckAcceptanceOut:
    owner = current_user.tenant_id
    await _client_of_owner(db, owner, client_id)
    reason = " ".join(body.reason.split())
    if len(reason) < 3 or len(reason) > 400:
        raise HTTPException(status_code=422, detail="Give a reason of 3 to 400 characters")
    if not key or len(key) > 80 or not all(c.isalnum() or c in "_-" for c in key):
        raise HTTPException(status_code=422, detail="That is not a check key")
    if body.expires_in_days is not None and not 1 <= body.expires_in_days <= MAX_ACCEPT_DAYS:
        raise HTTPException(status_code=422, detail=f"The end date must be 1 to {MAX_ACCEPT_DAYS} days away")
    now = datetime.now(UTC)
    expires = now + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        existing = (await db.execute(select(ClientCheckAcceptance).where(ClientCheckAcceptance.tenant_id == client_id, ClientCheckAcceptance.key == key))).scalar_one_or_none()
        if existing is None:
            count = (await db.execute(select(func.count()).select_from(ClientCheckAcceptance).where(ClientCheckAcceptance.tenant_id == client_id))).scalar_one()
            if count >= MAX_ACCEPTANCES_PER_CLIENT:
                raise HTTPException(status_code=422, detail=f"A client can have at most {MAX_ACCEPTANCES_PER_CLIENT} accepted checks")
        values = {"tenant_id": client_id, "key": key, "reason": reason, "accepted_by": current_user.user_id, "accepted_at": now, "expires_at": expires}
        stmt = pg_insert(ClientCheckAcceptance).values(values)
        await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "key"], set_={c: stmt.excluded[c] for c in values if c not in ("tenant_id", "key")}))
        await db.commit()
    return CheckAcceptanceOut(reason=reason, accepted_at=now, expires_at=expires)


@router.delete("/{client_id}/acceptances/{key}", status_code=204, summary="Stop accepting a check for a client")
async def remove_acceptance(client_id: uuid.UUID, key: str, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession) -> None:
    owner = current_user.tenant_id
    await _client_of_owner(db, owner, client_id)
    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        existing = (await db.execute(select(ClientCheckAcceptance).where(ClientCheckAcceptance.tenant_id == client_id, ClientCheckAcceptance.key == key))).scalar_one_or_none()
        if existing is not None:
            await db.delete(existing)
            await db.commit()


class SweepRunOut(BaseModel):
    source: str
    title: str
    ran_at: datetime
    accounts: int
    sent: int
    failed: int
    waiting: int
    skipped: int
    first_error: str
    # "ok", "failed" (clients failed and none was sent), "partly" (some failed) or "stale" (not run for 48 hours, whatever its last result).
    health: str


STALE_AFTER = timedelta(hours=48)


def sweep_health(sent: int, failed: int, ran_at: datetime, now: datetime) -> str:
    if now - ran_at > STALE_AFTER:
        return "stale"
    if failed > 0:
        return "partly" if sent > 0 else "failed"
    return "ok"


@router.get("/sweeps/runs", response_model=list[SweepRunOut], summary="The latest pass of each of CORE's per-client sweeps, and whether it reached A.C.O.R.N")
async def sweep_runs(current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> list[SweepRunOut]:
    owner = current_user.tenant_id
    rows = (await db.execute(select(CoreSweepRun).where(CoreSweepRun.tenant_id == owner).order_by(CoreSweepRun.source))).scalars().all()
    now = datetime.now(UTC)
    return [
        SweepRunOut(
            source=r.source,
            title=r.title,
            ran_at=r.ran_at,
            accounts=r.accounts,
            sent=r.sent,
            failed=r.failed,
            waiting=r.waiting,
            skipped=r.skipped,
            first_error=r.first_error,
            health=sweep_health(r.sent, r.failed, r.ran_at, now),
        )
        for r in rows
    ]

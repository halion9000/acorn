"""One client's security posture on a single page: devices, second-factor coverage, open alerts and cases. Read-only; every number comes from data AiSOC already holds.

``GET /api/v1/client-posture/{client_id}``. The same figures are on the Devices, Multi-factor status, Alerts and Cases pages; this puts them side by side for a client review.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, bindparam, delete, func, not_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.alerts import FINISHED_STATUSES, has_ticket_expr
from app.api.v1.endpoints.devices import ClientRollup, _as, _load_cached, _master_of, _scope, rollup_of
from app.api.v1.endpoints.identity import counts_for_mfa
from app.db.rls_scope import acting_as_tenant
from app.models.alert import Alert
from app.models.client_alias import ClientAlias
from app.models.identity_source import IdentitySource
from app.services.audit import emit_audit
from app.models.signin import ClientCheckAcceptance, ClientCheckHistory, ClientM365Check, CheckWeight, ClientCheckComment, ClientCheckItemHistory, ClientCheckOwner, ClientScoreHistory, ClientScoreTarget, CoreSweepRun, IdentityMfaUser
from app.models.tenant import Tenant
from app.services.domain_posture import DohResolver, DomainPosture, Resolver, candidate_domains, check_domains
from app.services.web_posture import LiveProbe, WebPosture, WebProbe, web_posture
from app.services import fleet_cache
from app.services.score_history import load_weights
from app.services.score_history import trend as score_trend
from app.services.fleet_posture import MAX_WEIGHT, average_score, below_target, classify_change, is_overdue, score_breakdown, search_checks, similar_size_average, tool_rows, tool_scorecards, BOARDS, FleetCheck, board_rows, coverage_matrix, expiring_acceptances, rank_clients, stale_sources, summarize
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
    # The accounts, machines or systems behind the verdict, when the tool says which.
    items: list[str] = []
    # Set when a person has accepted this check for the client (and it has not run out).
    accepted: "CheckAcceptanceOut | None" = None
    # Who is looking after this check and by when; overdue is true once the date has passed and the check is still not met.
    owner: str | None = None
    due_date: date | None = None
    overdue: bool = False
    # How many comments are in the thread on this check.
    comments: int = 0


class CheckAcceptanceOut(BaseModel):
    reason: str
    accepted_at: datetime
    expires_at: datetime | None = None
    # The check does not apply to this client (as opposed to a risk that does and was accepted).
    not_applicable: bool = False


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


def _items_of(check: dict) -> list[str]:
    """The short strings a check carries as its list (ignoring anything else, and capped)."""
    raw = check.get("items")
    return [i[:120] for i in raw if isinstance(i, str) and i.strip()][:40] if isinstance(raw, list) else []


async def _owners_of(db: Any, client_id: uuid.UUID) -> dict[str, tuple[str, date | None]]:
    """{check key: (owner, due date)} for one client. Read inside that client's scope. An older database without the table gives none."""
    try:
        async with db.begin_nested():
            return {r.key: (r.owner, r.due_date) for r in (await db.execute(select(ClientCheckOwner).where(ClientCheckOwner.tenant_id == client_id))).scalars().all()}
    except Exception:  # noqa: BLE001
        return {}


async def _comment_counts(db: Any, client_id: uuid.UUID) -> dict[str, int]:
    """{check key: number of comments} for one client, read inside that client's scope. An older database without the table gives none."""
    try:
        async with db.begin_nested():
            return {k: n for k, n in (await db.execute(select(ClientCheckComment.key, func.count()).where(ClientCheckComment.tenant_id == client_id).group_by(ClientCheckComment.key))).all()}
    except Exception:  # noqa: BLE001
        return {}


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
        owners = await _owners_of(db, client_id)
        comment_counts = await _comment_counts(db, client_id)
    since = {k: t for k, t in since_rows}
    now = datetime.now(UTC)
    accepted = {a.key: CheckAcceptanceOut(reason=a.reason, accepted_at=a.accepted_at, expires_at=a.expires_at, not_applicable=a.not_applicable) for a in accepted_rows if a.expires_at is None or a.expires_at > now}
    out: dict[str, ToolChecksOut] = {}
    for row in rows:
        checks = [
            PostureCheck(
                key=str(c["key"]),
                status=str(c["status"]),
                evidence=str(c.get("evidence", "")),
                since=since.get(str(c["key"])),
                accepted=accepted.get(str(c["key"])),
                items=_items_of(c),
                owner=owners.get(str(c["key"]), (None, None))[0],
                due_date=owners.get(str(c["key"]), (None, None))[1],
                overdue=is_overdue(str(c["status"]), owners.get(str(c["key"]), (None, None))[1], datetime.now(UTC).date()),
                comments=comment_counts.get(str(c["key"]), 0),
            )
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
    limit: Annotated[int, Query(ge=1, le=5000)] = 200,
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


class ScoreDay(BaseModel):
    day: str
    score: int | None
    met: int
    partly: int
    not_met: int
    accepted: int


class ScoreHistoryOut(BaseModel):
    client_id: uuid.UUID
    days: int
    rows: list[ScoreDay]
    # First and last score in the window and which way it went: better, worse, same or none.
    first: int | None
    last: int | None
    change: int | None
    direction: str


@router.get("/{client_id}/score-history", response_model=ScoreHistoryOut, summary="A client's check score day by day, and whether it got better or worse")
async def score_history(client_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, days: Annotated[int, Query(ge=1, le=730)] = 90) -> ScoreHistoryOut:
    owner = current_user.tenant_id
    await _client_of_owner(db, owner, client_id)
    days = max(2, min(days, 730))
    since = (datetime.now(UTC) - timedelta(days=days)).date()
    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        rows = (await db.execute(select(ClientScoreHistory).where(ClientScoreHistory.tenant_id == client_id, ClientScoreHistory.day >= since).order_by(ClientScoreHistory.day))).scalars().all()
    shown = [{"day": r.day.isoformat(), "score": r.score, "met": r.met, "partly": r.partly, "not_met": r.not_met, "accepted": r.accepted} for r in rows]
    t = score_trend(shown)
    return ScoreHistoryOut(client_id=client_id, days=days, rows=[ScoreDay(**r) for r in shown], first=t["first"], last=t["last"], change=t["change"], direction=t["direction"])


class OwnerIn(BaseModel):
    # A person's name; none (or blank) removes the owner and the date.
    owner: str | None = None
    due_date: date | None = None


class OwnerOut(BaseModel):
    key: str
    owner: str | None
    due_date: date | None


@router.put("/{client_id}/owners/{key}", response_model=OwnerOut, summary="Say who is looking after a check for a client and by when, or clear it")
async def set_check_owner(
    client_id: uuid.UUID, key: str, body: OwnerIn, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession, request: Request = None  # type: ignore[assignment]
) -> OwnerOut:
    owner = current_user.tenant_id
    await _client_of_owner(db, owner, client_id)
    if not key or len(key) > 80 or not all(c.isalnum() or c in "_-" for c in key):
        raise HTTPException(status_code=422, detail="That is not a check key")
    name = " ".join((body.owner or "").split())
    if len(name) > 80:
        raise HTTPException(status_code=422, detail="A name is at most 80 characters")
    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        if not name:
            await db.execute(delete(ClientCheckOwner).where(ClientCheckOwner.tenant_id == client_id, ClientCheckOwner.key == key))
        else:
            values = {"tenant_id": client_id, "key": key, "owner": name, "due_date": body.due_date, "updated_by": current_user.user_id, "updated_at": datetime.now(UTC)}
            stmt = pg_insert(ClientCheckOwner).values(values)
            await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "key"], set_={c: stmt.excluded[c] for c in values if c not in ("tenant_id", "key")}))
        await db.commit()
    await emit_audit(
        db=db,
        tenant_id=owner,
        actor_id=current_user.user_id,
        action="posture:check_owner_set" if name else "posture:check_owner_cleared",
        resource="client_check",
        resource_id=f"{client_id}:{key}",
        changes={"client": str(client_id), "key": key, "owner": name or None, "due_date": body.due_date.isoformat() if body.due_date and name else None},
        request=request,
    )
    await db.commit()
    fleet_cache.clear()
    return OwnerOut(key=key, owner=name or None, due_date=body.due_date if name else None)


class ItemEventOut(BaseModel):
    item: str
    event: str
    observed_at: datetime


class ItemHistoryOut(BaseModel):
    client_id: uuid.UUID
    key: str
    events: list[ItemEventOut]


@router.get("/{client_id}/checks/{key}/item-history", response_model=ItemHistoryOut, summary="When machines or accounts joined or left the list behind one of a client's checks, newest first")
async def check_item_history(client_id: uuid.UUID, key: str, current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, limit: Annotated[int, Query(ge=1, le=5000)] = 200) -> ItemHistoryOut:
    owner = current_user.tenant_id
    await _client_of_owner(db, owner, client_id)
    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        rows = (
            await db.execute(
                select(ClientCheckItemHistory)
                .where(ClientCheckItemHistory.tenant_id == client_id, ClientCheckItemHistory.key == key)
                .order_by(ClientCheckItemHistory.observed_at.desc(), ClientCheckItemHistory.id.desc())
                .limit(max(1, min(limit, 500)))
            )
        ).scalars().all()
    return ItemHistoryOut(client_id=client_id, key=key, events=[ItemEventOut(item=r.item, event=r.event, observed_at=r.observed_at) for r in rows])


MAX_COMMENTS_PER_CHECK = 200


class CommentIn(BaseModel):
    body: str


class CommentOut(BaseModel):
    id: int
    author: str
    body: str
    created_at: datetime


class CommentsOut(BaseModel):
    client_id: uuid.UUID
    key: str
    comments: list[CommentOut]


def _check_key_ok(key: str) -> bool:
    return bool(key) and len(key) <= 80 and all(c.isalnum() or c in "_-" for c in key)


@router.get("/{client_id}/checks/{key}/comments", response_model=CommentsOut, summary="The comments on one of a client's checks, oldest first")
async def check_comments(client_id: uuid.UUID, key: str, current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> CommentsOut:
    owner = current_user.tenant_id
    await _client_of_owner(db, owner, client_id)
    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        rows = (await db.execute(select(ClientCheckComment).where(ClientCheckComment.tenant_id == client_id, ClientCheckComment.key == key).order_by(ClientCheckComment.created_at, ClientCheckComment.id))).scalars().all()
    return CommentsOut(client_id=client_id, key=key, comments=[CommentOut(id=r.id, author=r.author, body=r.body, created_at=r.created_at) for r in rows])


@router.post("/{client_id}/checks/{key}/comments", response_model=CommentOut, status_code=201, summary="Add a comment to one of a client's checks")
async def add_check_comment(client_id: uuid.UUID, key: str, body: CommentIn, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession) -> CommentOut:
    owner = current_user.tenant_id
    await _client_of_owner(db, owner, client_id)
    if not _check_key_ok(key):
        raise HTTPException(status_code=422, detail="That is not a check key")
    text_ = " ".join(body.body.split())
    if not 1 <= len(text_) <= 1000:
        raise HTTPException(status_code=422, detail="A comment is 1 to 1000 characters")
    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        count = (await db.execute(select(func.count()).select_from(ClientCheckComment).where(ClientCheckComment.tenant_id == client_id, ClientCheckComment.key == key))).scalar_one()
        if count >= MAX_COMMENTS_PER_CHECK:
            raise HTTPException(status_code=422, detail=f"A check can have at most {MAX_COMMENTS_PER_CHECK} comments")
        row = ClientCheckComment(tenant_id=client_id, key=key, author=(getattr(current_user, "email", None) or str(current_user.user_id) or "unknown")[:200], body=text_)
        db.add(row)
        await db.flush()
        out = CommentOut(id=row.id, author=row.author, body=row.body, created_at=row.created_at or datetime.now(UTC))
        await db.commit()
    return out


class TargetIn(BaseModel):
    # 1 to 100; none removes the target.
    target: int | None = None


class TargetOut(BaseModel):
    client_id: uuid.UUID
    target: int | None


@router.put("/{client_id}/target", response_model=TargetOut, summary="Set the score a client should stay at or above, or remove it")
async def set_target(client_id: uuid.UUID, body: TargetIn, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession) -> TargetOut:
    owner = current_user.tenant_id
    await _client_of_owner(db, owner, client_id)
    if body.target is not None and not 1 <= body.target <= 100:
        raise HTTPException(status_code=422, detail="A target is a score from 1 to 100")
    if body.target is None:
        await db.execute(delete(ClientScoreTarget).where(ClientScoreTarget.tenant_id == owner, ClientScoreTarget.client_id == client_id))
    else:
        values = {"tenant_id": owner, "client_id": client_id, "target": body.target, "updated_by": current_user.user_id, "updated_at": datetime.now(UTC)}
        stmt = pg_insert(ClientScoreTarget).values(values)
        await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "client_id"], set_={c: stmt.excluded[c] for c in values if c not in ("tenant_id", "client_id")}))
    await db.commit()
    fleet_cache.clear()
    return TargetOut(client_id=client_id, target=body.target)


class AcceptIn(BaseModel):
    reason: str
    # Days from now until the acceptance runs out; none means until someone removes it.
    expires_in_days: int | None = None
    # The check does not apply to this client at all (no firewall, no domain controller). Has no end date.
    not_applicable: bool = False


MAX_ACCEPT_DAYS = 730
MAX_ACCEPTANCES_PER_CLIENT = 200


@router.put("/{client_id}/acceptances/{key}", response_model=CheckAcceptanceOut, summary="Accept a failing check for a client, with a reason and an optional end date")
async def accept_check(
    client_id: uuid.UUID, key: str, body: AcceptIn, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession, request: Request = None  # type: ignore[assignment]
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
    if body.not_applicable and body.expires_in_days is not None:
        raise HTTPException(status_code=422, detail="A check that does not apply has no end date")
    now = datetime.now(UTC)
    expires = now + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        existing = (await db.execute(select(ClientCheckAcceptance).where(ClientCheckAcceptance.tenant_id == client_id, ClientCheckAcceptance.key == key))).scalar_one_or_none()
        if existing is None:
            count = (await db.execute(select(func.count()).select_from(ClientCheckAcceptance).where(ClientCheckAcceptance.tenant_id == client_id))).scalar_one()
            if count >= MAX_ACCEPTANCES_PER_CLIENT:
                raise HTTPException(status_code=422, detail=f"A client can have at most {MAX_ACCEPTANCES_PER_CLIENT} accepted checks")
        values = {"tenant_id": client_id, "key": key, "reason": reason, "accepted_by": current_user.user_id, "accepted_at": now, "expires_at": expires, "not_applicable": body.not_applicable}
        stmt = pg_insert(ClientCheckAcceptance).values(values)
        await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "key"], set_={c: stmt.excluded[c] for c in values if c not in ("tenant_id", "key")}))
        await db.commit()
    await emit_audit(
        db=db,
        tenant_id=owner,
        actor_id=current_user.user_id,
        action="posture:check_not_applicable" if body.not_applicable else "posture:check_accepted",
        resource="client_check",
        resource_id=f"{client_id}:{key}",
        changes={"client": str(client_id), "key": key, "reason": reason, "expires_at": expires.isoformat() if expires else None},
        request=request,
    )
    await db.commit()
    fleet_cache.clear()
    return CheckAcceptanceOut(reason=reason, accepted_at=now, expires_at=expires, not_applicable=body.not_applicable)


MAX_BULK_CLIENTS = 200


class BulkAcceptIn(AcceptIn):
    key: str
    client_ids: list[uuid.UUID]


class BulkSkipped(BaseModel):
    client_id: uuid.UUID
    detail: str


class BulkAcceptOut(BaseModel):
    accepted: int
    skipped: list[BulkSkipped]


@router.post("/fleet/acceptances", response_model=BulkAcceptOut, summary="Accept the same check for several clients at once with one reason, or mark it not applicable to them")
async def accept_check_for_many(
    body: BulkAcceptIn, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession, request: Request = None  # type: ignore[assignment]
) -> BulkAcceptOut:
    """One reason, and one end date (or none), for the same check on each listed client. A client that is not yours, or that is over its limit, is skipped and named; the rest are done."""
    ids = list(dict.fromkeys(body.client_ids))
    if not ids or len(ids) > MAX_BULK_CLIENTS:
        raise HTTPException(status_code=422, detail=f"Give 1 to {MAX_BULK_CLIENTS} clients")
    # What is wrong for one client is wrong for all: say so once instead of skipping every client.
    reason = " ".join(body.reason.split())
    if len(reason) < 3 or len(reason) > 400:
        raise HTTPException(status_code=422, detail="Give a reason of 3 to 400 characters")
    if not body.key or len(body.key) > 80 or not all(c.isalnum() or c in "_-" for c in body.key):
        raise HTTPException(status_code=422, detail="That is not a check key")
    if body.expires_in_days is not None and not 1 <= body.expires_in_days <= MAX_ACCEPT_DAYS:
        raise HTTPException(status_code=422, detail=f"The end date must be 1 to {MAX_ACCEPT_DAYS} days away")
    if body.not_applicable and body.expires_in_days is not None:
        raise HTTPException(status_code=422, detail="A check that does not apply has no end date")
    single = AcceptIn(reason=reason, expires_in_days=body.expires_in_days, not_applicable=body.not_applicable)
    accepted = 0
    skipped: list[BulkSkipped] = []
    for cid in ids:
        try:
            await accept_check(cid, body.key, single, current_user, db, request)
            accepted += 1
        except HTTPException as e:
            skipped.append(BulkSkipped(client_id=cid, detail=str(e.detail)))
    return BulkAcceptOut(accepted=accepted, skipped=skipped)


@router.delete("/{client_id}/acceptances/{key}", status_code=204, summary="Stop accepting a check for a client")
async def remove_acceptance(
    client_id: uuid.UUID, key: str, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession, request: Request = None  # type: ignore[assignment]
) -> None:
    owner = current_user.tenant_id
    await _client_of_owner(db, owner, client_id)
    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        existing = (await db.execute(select(ClientCheckAcceptance).where(ClientCheckAcceptance.tenant_id == client_id, ClientCheckAcceptance.key == key))).scalar_one_or_none()
        removed = existing is not None
        if existing is not None:
            await db.delete(existing)
            await db.commit()
    if removed:
        await emit_audit(
            db=db, tenant_id=owner, actor_id=current_user.user_id, action="posture:check_acceptance_removed", resource="client_check", resource_id=f"{client_id}:{key}", changes={"client": str(client_id), "key": key}, request=request
        )
        await db.commit()
    fleet_cache.clear()


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


@router.get("/sweeps/latest", response_model=list[SweepRunOut], summary="The latest pass of each of CORE's per-client sweeps, and whether it reached A.C.O.R.N")
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


# ---- every client side by side --------------------------------------------------------------------------------------------------------------------------------------


async def _fleet_checks(db: Any, owner: uuid.UUID) -> tuple[list[FleetCheck], dict[uuid.UUID, str], dict[uuid.UUID, dict[str, datetime]]]:
    """The latest tool checks of every shown client, with since-when and whether each is accepted. One read per client (each under that client's own scope); kept for 30 seconds (see fleet_cache)."""
    key = f"fleet:{owner}"
    cached = fleet_cache.get(key)
    if cached is not None:
        return cached
    result = await _read_fleet_checks(db, owner)
    fleet_cache.put(key, result)
    return result


async def _read_fleet_checks(db: Any, owner: uuid.UUID) -> tuple[list[FleetCheck], dict[uuid.UUID, str], dict[uuid.UUID, dict[str, datetime]]]:
    _ids, clients = await _scope(db, owner, None)
    shown, names = _ids[1:], clients
    sources = list(TOOL_CHECK_SOURCES)
    now = datetime.now(UTC)
    out: list[FleetCheck] = []
    refreshed: dict[uuid.UUID, dict[str, datetime]] = {}
    for cid in shown:
        async with _as(db, owner, cid):
            rows = (await db.execute(select(ClientM365Check).where(ClientM365Check.tenant_id == cid, ClientM365Check.source.in_(sources)))).scalars().all()
            if not rows:
                continue
            since = {k: t for k, t in (await db.execute(select(ClientCheckHistory.key, func.max(ClientCheckHistory.observed_at)).where(ClientCheckHistory.tenant_id == cid).group_by(ClientCheckHistory.key))).all()}
            accepted = {a.key for a in (await db.execute(select(ClientCheckAcceptance).where(ClientCheckAcceptance.tenant_id == cid))).scalars().all() if a.expires_at is None or a.expires_at > now}
            owners = await _owners_of(db, cid)
        refreshed[cid] = {r.source: r.refreshed_at for r in rows}
        for r in rows:
            for c in r.checks or []:
                if isinstance(c, dict) and c.get("key") and c.get("status"):
                    key = str(c["key"])
                    out.append(
                        FleetCheck(client_id=str(cid), client_name=names.get(cid) or str(cid), source=r.source, key=key, status=str(c["status"]), evidence=str(c.get("evidence", "")), refreshed_at=r.refreshed_at, since=since.get(key), accepted=key in accepted, items=tuple(_items_of(c)), owner=owners.get(key, (None, None))[0], due_date=owners.get(key, (None, None))[1])
                    )
    return out, names, refreshed


class FleetClient(BaseModel):
    client_id: uuid.UUID
    client_name: str | None
    score: int | None
    met: int
    partly: int
    not_met: int
    accepted: int
    # Tools whose rows for this client are older than 48 hours.
    stale_tools: list[str] = []
    # The score a person said this client should stay at or above, and whether it is under it.
    target: int | None = None
    below_target: bool = False


class FleetOut(BaseModel):
    generated_at: datetime
    clients: list[FleetClient]
    # The mean score of the clients that have one.
    average_score: int | None = None


@router.get("/fleet/summary", response_model=FleetOut, summary="Every client's check score, worst first")
async def fleet_summary(current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> FleetOut:
    owner = current_user.tenant_id
    checks, names, refreshed = await _fleet_checks(db, owner)
    now = datetime.now(UTC)
    by_client: dict[str, list[FleetCheck]] = {}
    for c in checks:
        by_client.setdefault(c.client_id, []).append(c)
    try:
        async with db.begin_nested():  # an older database without the table must still show the fleet
            targets = {cid: t for cid, t in (await db.execute(select(ClientScoreTarget.client_id, ClientScoreTarget.target).where(ClientScoreTarget.tenant_id == owner))).all()}
    except Exception:  # noqa: BLE001
        targets = {}
    summaries = []
    weights = await load_weights(db, owner)
    for cid, rows in by_client.items():
        s = summarize(rows, weights)
        target = targets.get(uuid.UUID(cid))
        summaries.append({"client_id": uuid.UUID(cid), "client_name": names.get(uuid.UUID(cid)), "stale_tools": stale_sources(refreshed.get(uuid.UUID(cid), {}), now), "target": target, "below_target": below_target(s["score"], target), **s})
    ranked = rank_clients(summaries)
    return FleetOut(generated_at=now, clients=[FleetClient(**s) for s in ranked], average_score=average_score([s["score"] for s in ranked]))


class WeightOut(BaseModel):
    key: str
    weight: int


class WeightIn(BaseModel):
    weight: int


@router.get("/fleet/weights", response_model=list[WeightOut], summary="The checks whose weight differs from the default of 1")
async def fleet_weights(current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> list[WeightOut]:
    return [WeightOut(key=k, weight=w) for k, w in sorted((await load_weights(db, current_user.tenant_id)).items())]


@router.put("/fleet/weights/{key}", response_model=WeightOut, summary="Make a check count more (2 to 5 times) towards every client's score, or 1 for the default")
async def set_weight(key: str, body: WeightIn, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession) -> WeightOut:
    owner = current_user.tenant_id
    if not _check_key_ok(key):
        raise HTTPException(status_code=422, detail="That is not a check key")
    if not 1 <= body.weight <= MAX_WEIGHT:
        raise HTTPException(status_code=422, detail=f"A weight is 1 to {MAX_WEIGHT}")
    if body.weight == 1:
        await db.execute(delete(CheckWeight).where(CheckWeight.tenant_id == owner, CheckWeight.key == key))
    else:
        values = {"tenant_id": owner, "key": key, "weight": body.weight, "updated_by": current_user.user_id, "updated_at": datetime.now(UTC)}
        stmt = pg_insert(CheckWeight).values(values)
        await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "key"], set_={c: stmt.excluded[c] for c in ("weight", "updated_by", "updated_at")}))
    await db.commit()
    fleet_cache.clear()
    return WeightOut(key=key, weight=body.weight)


class ScoreBreakdownRow(BaseModel):
    source: str
    key: str
    status: str
    weight: int
    points_lost: float


class ScoreBreakdownOut(BaseModel):
    client_id: uuid.UUID
    score: int | None
    lost: float
    rows: list[ScoreBreakdownRow]


@router.get("/{client_id}/score-breakdown", response_model=ScoreBreakdownOut, summary="Where a client's lost points went: each check that is not met and what it cost, biggest first")
async def client_score_breakdown(client_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> ScoreBreakdownOut:
    owner = current_user.tenant_id
    await _client_of_owner(db, owner, client_id)
    checks, _names, _refreshed = await _fleet_checks(db, owner)
    mine = [c for c in checks if c.client_id == str(client_id)]
    b = score_breakdown(mine, await load_weights(db, owner))
    return ScoreBreakdownOut(client_id=client_id, score=b["score"], lost=b["lost"], rows=[ScoreBreakdownRow(**r) for r in b["rows"]])


class CompareOut(BaseModel):
    client_id: uuid.UUID
    score: int | None
    fleet_average: int | None
    # Machines the RMM manages for this client; 0 when it has no RMM count (then there is no size comparison).
    size: int
    similar_average: int | None
    similar_clients: int


@router.get("/{client_id}/compare", response_model=CompareOut, summary="A client's score next to the fleet average and the average of clients about the same size")
async def compare_client(client_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> CompareOut:
    from app.api.v1.endpoints.billing import _all_client_counts  # noqa: PLC0415 - billing reads sizes; imported here to keep the modules apart
    from app.services.license_counts import BASELINE_ITEMS, BASELINE_TOOL  # noqa: PLC0415

    owner = current_user.tenant_id
    await _client_of_owner(db, owner, client_id)
    checks, _names, _refreshed = await _fleet_checks(db, owner)
    weights = await load_weights(db, owner)
    by_client: dict[str, list[FleetCheck]] = {}
    for c in checks:
        by_client.setdefault(c.client_id, []).append(c)
    scores = {cid: summarize(rows, weights)["score"] for cid, rows in by_client.items()}
    per_client, _n = await _all_client_counts(db, owner)
    sizes = {str(cid): sum(int(r["count"]) for r in rows if r["source"] == BASELINE_TOOL and r["item"] in BASELINE_ITEMS) for cid, rows in per_client.items()}
    mine = str(client_id)
    others = {cid: (sizes.get(cid, 0), sc) for cid, sc in scores.items() if cid != mine}
    similar = similar_size_average(sizes.get(mine, 0), others)
    return CompareOut(client_id=client_id, score=scores.get(mine), fleet_average=average_score(list(scores.values())), size=sizes.get(mine, 0), similar_average=similar["average"], similar_clients=similar["clients"])


class ToolScorecard(BaseModel):
    source: str
    checks: int
    met: int
    partly: int
    not_met: int
    clients_with_problems: int
    percent_fine: int | None


@router.get("/fleet/tools", response_model=list[ToolScorecard], summary="Each tool's checks across all clients: how many are fine and how many clients have a problem from it, worst first")
async def fleet_tools(current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> list[ToolScorecard]:
    checks, _names, _refreshed = await _fleet_checks(db, current_user.tenant_id)
    return [ToolScorecard(**t) for t in tool_scorecards(checks)]


class SearchHit(BaseModel):
    client_id: uuid.UUID
    client_name: str
    source: str
    key: str
    status: str
    evidence: str
    matched_items: list[str] = []
    matched_text: bool = False
    accepted: bool = False


@router.get("/fleet/search", response_model=list[SearchHit], summary="Find the checks of all clients that mention a machine, account or word")
async def fleet_search(current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, q: str, limit: Annotated[int, Query(ge=1, le=5000)] = 100) -> list[SearchHit]:
    """Which client has host SRV-02, or an account called jsmith, or an expiring certificate: searches what every tool reported (evidence, check name and the machines or accounts behind each check)."""
    checks, _names, _refreshed = await _fleet_checks(db, current_user.tenant_id)
    return [SearchHit(**{**h, "client_id": uuid.UUID(h["client_id"])}) for h in search_checks(checks, q, max(1, min(limit, 300)))]


class FleetBoardRow(BaseModel):
    client_id: uuid.UUID
    client_name: str
    source: str
    key: str
    status: str
    evidence: str
    since: datetime | None = None
    accepted: bool = False
    items: list[str] = []
    owner: str | None = None
    due_date: date | None = None
    overdue: bool = False


class FleetBoardOut(BaseModel):
    board: str
    title: str
    keys: list[str]
    rows: list[FleetBoardRow]


@router.get("/fleet/boards", summary="The boards that gather related checks across all clients")
async def fleet_boards(current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))]) -> dict[str, dict[str, Any]]:
    return {name: {"title": title, "keys": list(keys)} for name, (title, keys) in BOARDS.items()}


@router.get("/fleet/boards/{board}", response_model=FleetBoardOut, summary="One board: the clients whose related checks are not fine")
async def fleet_board(
    board: str, current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, include_met: bool = False, limit: Annotated[int, Query(ge=1, le=5000)] = 500
) -> FleetBoardOut:
    if board not in BOARDS:
        raise HTTPException(status_code=404, detail="No such board")
    title, keys = BOARDS[board]
    checks, _names, _refreshed = await _fleet_checks(db, current_user.tenant_id)
    rows = board_rows(checks, keys, include_met=include_met)[: max(1, min(limit, 2000))]
    return FleetBoardOut(
        board=board,
        title=title,
        keys=list(keys),
        rows=[FleetBoardRow(client_id=uuid.UUID(r.client_id), client_name=r.client_name, source=r.source, key=r.key, status=r.status, evidence=r.evidence, since=r.since, accepted=r.accepted, items=list(r.items), owner=r.owner, due_date=r.due_date, overdue=is_overdue(r.status, r.due_date, datetime.now(UTC).date())) for r in rows],
    )


@router.get("/fleet/tools/{source}/checks", response_model=FleetBoardOut, summary="The checks one tool reported across clients that are not fine, to see what its problems are")
async def fleet_tool_checks(
    source: str, current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, include_met: bool = False, limit: Annotated[int, Query(ge=1, le=5000)] = 2000
) -> FleetBoardOut:
    checks, _names, _refreshed = await _fleet_checks(db, current_user.tenant_id)
    rows = tool_rows(checks, source, include_met=include_met)[:limit]
    today = datetime.now(UTC).date()
    return FleetBoardOut(
        board=source,
        title=source,
        keys=sorted({c.key for c in rows}),
        rows=[FleetBoardRow(client_id=uuid.UUID(r.client_id), client_name=r.client_name, source=r.source, key=r.key, status=r.status, evidence=r.evidence, since=r.since, accepted=r.accepted, items=list(r.items), owner=r.owner, due_date=r.due_date, overdue=is_overdue(r.status, r.due_date, today)) for r in rows],
    )


@router.get("/fleet/coverage", summary="Which tool each client is mapped to, and which tools it is missing")
async def fleet_coverage(current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession) -> dict[str, Any]:
    owner = current_user.tenant_id
    ids, names = await _scope(db, owner, None)
    shown = {str(i): names.get(i) or str(i) for i in ids[1:]}
    rows = (
        await db.execute(
            select(ClientAlias.child_tenant_id, ClientAlias.vendor).where(ClientAlias.tenant_id == owner, ClientAlias.ignored.is_(False), ClientAlias.child_tenant_id.is_not(None))
        )
    ).all()
    return coverage_matrix([(str(c), v) for c, v in rows if str(c) in shown], shown)


class FleetChange(BaseModel):
    client_id: uuid.UUID
    client_name: str
    key: str
    source: str
    status: str
    previous_status: str | None
    observed_at: datetime


@router.get("/fleet/changes", response_model=list[FleetChange], summary="Checks that appeared or changed status across all clients in the last days")
async def fleet_changes(current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, days: Annotated[int, Query(ge=1, le=400)] = 1, limit: Annotated[int, Query(ge=1, le=5000)] = 300) -> list[FleetChange]:
    owner = current_user.tenant_id
    days = max(1, min(days, 90))
    ids, names = await _scope(db, owner, None)
    since = datetime.now(UTC) - timedelta(days=days)
    out: list[FleetChange] = []
    for cid in ids[1:]:
        async with _as(db, owner, cid):
            rows = (await db.execute(select(ClientCheckHistory).where(ClientCheckHistory.tenant_id == cid, ClientCheckHistory.observed_at >= since))).scalars().all()
        out += [FleetChange(client_id=cid, client_name=names.get(cid) or str(cid), key=r.key, source=r.source, status=r.status, previous_status=r.previous_status, observed_at=r.observed_at) for r in rows]
    # Worsening first (a check that became not met), then the newest.
    out.sort(key=lambda c: (c.status != "not_met", -c.observed_at.timestamp()))
    return out[: max(1, min(limit, 1000))]


class DigestItem(BaseModel):
    client_id: uuid.UUID
    client_name: str
    text: str


class DigestOut(BaseModel):
    generated_at: datetime
    days: int
    worse: list[DigestItem]
    better: list[DigestItem]
    overdue: list[DigestItem]
    expiring: list[DigestItem]
    below_target: list[DigestItem]
    # How many there are in all when a list was cut to its first entries.
    counts: dict[str, int]


@router.get("/fleet/digest", response_model=DigestOut, summary="One digest for the owner: what got worse and better lately, what is overdue, what accepted risks end soon and who is below target")
async def fleet_digest(current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, days: Annotated[int, Query(ge=1, le=400)] = 1, limit: Annotated[int, Query(ge=1, le=5000)] = 15) -> DigestOut:
    days = max(1, min(days, 30))
    limit = max(1, min(limit, 50))
    now = datetime.now(UTC)
    changes = await fleet_changes(current_user, db, days=days, limit=1000)
    worse, better = [], []
    for c in changes:
        how = classify_change(c.status, c.previous_status)
        item = DigestItem(client_id=c.client_id, client_name=c.client_name, text=f"{c.key.replace('_', ' ')} is now {c.status.replace('_', ' ')}")
        if how == "worse":
            worse.append(item)
        elif how == "better":
            better.append(item)
    checks, names, _refreshed = await _fleet_checks(db, current_user.tenant_id)
    today = now.date()
    overdue = sorted(
        (DigestItem(client_id=uuid.UUID(c.client_id), client_name=c.client_name, text=f"{c.key.replace('_', ' ')} is overdue ({c.owner or 'no owner'}, due {c.due_date})") for c in checks if not c.accepted and is_overdue(c.status, c.due_date, today)),
        key=lambda i: (i.client_name.lower(), i.text),
    )
    ending = await fleet_acceptances(current_user, db, within_days=7, limit=1000)
    expiring = [DigestItem(client_id=a.client_id, client_name=a.client_name, text=f"accepted risk {a.key.replace('_', ' ')} ends {a.expires_at.date() if a.expires_at else ''} ({a.reason})") for a in ending]
    summary = await fleet_summary(current_user, db)
    below = [DigestItem(client_id=c.client_id, client_name=c.client_name or str(c.client_id), text=f"score {c.score}% is under its target of {c.target}%") for c in summary.clients if c.below_target]
    lists = {"worse": worse, "better": better, "overdue": overdue, "expiring": expiring, "below_target": below}
    return DigestOut(generated_at=now, days=days, counts={k: len(v) for k, v in lists.items()}, **{k: v[:limit] for k, v in lists.items()})


class FleetAcceptance(BaseModel):
    client_id: uuid.UUID
    client_name: str
    key: str
    reason: str
    accepted_at: datetime
    expires_at: datetime | None
    # The check does not apply to the client at all, as opposed to a risk that does and was accepted.
    not_applicable: bool = False


@router.get("/fleet/acceptances", response_model=list[FleetAcceptance], summary="Accepted risks across all clients that still stand, the ones about to run out first")
async def fleet_acceptances(current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession, within_days: Annotated[int | None, Query(ge=1, le=3650)] = None, limit: Annotated[int, Query(ge=1, le=5000)] = 300) -> list[FleetAcceptance]:
    owner = current_user.tenant_id
    ids, names = await _scope(db, owner, None)
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for cid in ids[1:]:
        async with _as(db, owner, cid):
            found = (await db.execute(select(ClientCheckAcceptance).where(ClientCheckAcceptance.tenant_id == cid))).scalars().all()
        rows += [{"client_id": cid, "client_name": names.get(cid) or str(cid), "key": a.key, "reason": a.reason, "accepted_at": a.accepted_at, "expires_at": a.expires_at, "not_applicable": a.not_applicable} for a in found]
    kept = expiring_acceptances(rows, now, None if within_days is None else max(1, min(within_days, 400)))
    return [FleetAcceptance(**r) for r in kept[: max(1, min(limit, 1000))]]

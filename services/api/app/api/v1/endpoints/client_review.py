"""A client review on one page: tool coverage, Multi-Factor, Microsoft Secure Score, the last 30 days of alerts and cases, and a cyber-insurance readiness checklist. Read-only; every number comes
from data AiSOC already holds, and what it does not hold is reported as unknown rather than guessed.

``GET /api/v1/client-review/{client_id}``. For a quarterly business review or a cyber-insurance questionnaire; the checklist answers are evidence from the connected tools, not a certification.
``POST /api/v1/inbox/core-feed/{token}/vcio-reviews``: CORE's daily summary of a client's vCIO Toolbox recommendations and risks (authenticated by the secret in the path, like the other core-feed routes).
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints, model_validator
from sqlalchemy import and_, bindparam, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.alerts import FINISHED_STATUSES
from app.api.v1.endpoints.client_posture import devices_part
from app.api.v1.endpoints.devices import UnmappedClient, _load_cached, _master_of, _scope, rollup_of
from app.api.v1.endpoints.identity import counts_for_mfa
from app.api.v1.endpoints.inbox_core_feed import _verify_core_feed_token
from app.api.v1.endpoints.signins import targets_by_tenant
from app.db.rls_scope import acting_as_tenant
from app.db.rls_sessions import adopt_tenant
from app.models.alert import Alert
from app.models.client_alias import ClientAlias
from app.models.client_review_answer import ClientReviewAnswer
from app.models.signin import (
    ClientCheckHistory,
    ClientCheckItemHistory,
    ClientM365Check,
    ClientVcioReview,
    CoreSweepRun,
    CoreTool,
    IdentityMfaUser,
    IdentitySecureScore,
)
from app.models.tenant import Tenant
from app.services import fleet_cache, review_history
from app.services.assessment_review import AssessAnswer, assessment_answers
from app.services.check_history import changes as check_changes
from app.services.check_history import item_changes
from app.services.client_review import DeviceFacts, Readiness, device_facts, readiness
from app.services.infra_review import CIPP_BASELINE_SOURCE, SAAS_SOURCES, TOOL_CHECK_SOURCES
from app.services.m365_review import M365Answer, m365_answers
from app.services.review_overrides import (
    MAX_PER_CLIENT,
    clean_answer,
    merge_assess,
    merge_m365,
    merge_readiness,
    merge_tech,
    readiness_counts,
)
from app.services.sat_review import SAT_SOURCE
from app.services.score_history import load_weights, record_today
from app.services.tech_stack import TechAnswer, tech_stack

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/client-review", tags=["posture"])
ingest_router = APIRouter(prefix="/inbox", tags=["inbox-core-feed"])

WINDOW_DAYS = 30
_CASE_FINISHED = ("resolved", "closed")


class ReviewAlerts(BaseModel):
    open: int
    critical_open: int
    high_open: int
    opened_30d: int
    closed_30d: int


class ReviewCases(BaseModel):
    open: int
    opened_30d: int
    resolved_30d: int


class ReviewScore(BaseModel):
    percent: float
    current: float
    max: float
    average: float | None = None
    taken_at: datetime


class VcioRecommendation(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    priority: str | None = Field(default=None, max_length=20)
    adoption: str = Field(max_length=40)
    due: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    on_roadmap: bool = False


class VcioRecommendations(BaseModel):
    total: int = Field(ge=0, le=100000)
    pending: int = Field(ge=0, le=100000)
    adopted: int = Field(ge=0, le=100000)
    declined: int = Field(ge=0, le=100000)
    top: list[VcioRecommendation] = Field(default_factory=list, max_length=15)


class VcioRisk(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=60)
    priority: str | None = Field(default=None, max_length=20)
    impact: float | None = None
    likelihood: float | None = None
    score: float | None = None
    inherent: str | None = Field(default=None, max_length=20)


class VcioReviewReport(BaseModel):
    vendor: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    vendor_client_id: str = Field(min_length=1, max_length=200)
    recommendations: VcioRecommendations
    risks: list[VcioRisk] = Field(default_factory=list, max_length=30)


class VcioReviewResponse(BaseModel):
    accepted: int
    unmapped: int = 0
    ignored: int = 0
    unmapped_clients: list[UnmappedClient] = Field(default_factory=list)


class _VcioView:
    """Lets the shared client mapping place a report that belongs to one client, as a list of one item."""

    def __init__(self, report: VcioReviewReport) -> None:
        self.vendor = report.vendor
        self.items = [report]


async def apply_vcio_review(db: Any, owner: uuid.UUID, report: VcioReviewReport, now: datetime | None = None) -> VcioReviewResponse:
    """Replace the client's vCIO Toolbox summary with this report. The caller owns the transaction."""
    now = now or datetime.now(UTC)
    by_tenant, unmapped, ignored, waiting = await targets_by_tenant(db, owner, _VcioView(report))
    accepted = 0
    for tid in by_tenant:
        async with acting_as_tenant(db, tid):
            values = {
                "tenant_id": tid,
                "source": report.vendor,
                "recommendations": report.recommendations.model_dump(),
                "risks": [r.model_dump() for r in report.risks],
                "refreshed_at": now,
            }
            stmt = pg_insert(ClientVcioReview).values(values)
            update = {c: stmt.excluded[c] for c in values if c not in ("tenant_id", "source")}
            await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "source"], set_=update))
            accepted += 1
    return VcioReviewResponse(accepted=accepted, unmapped=unmapped, ignored=ignored, unmapped_clients=waiting)


@ingest_router.post("/core-feed/{tenant_token}/vcio-reviews", response_model=VcioReviewResponse)
async def report_core_feed_vcio_review(tenant_token: str, body: VcioReviewReport, db: DBSession) -> VcioReviewResponse:
    """Record one client's vCIO Toolbox recommendations and risks (replacing the last summary)."""
    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    result = await apply_vcio_review(db, owner, body)
    await db.commit()
    return result


class M365CheckIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]{1,60}$")
    status: str = Field(pattern=r"^(met|partly|not_met)$")
    evidence: str = Field(default="", max_length=300)
    # The accounts, machines or systems behind the verdict, so the page can list them (at most 40, each short). A tool that has none sends none.
    items: list[Annotated[str, StringConstraints(max_length=120)]] = Field(default_factory=list, max_length=40)


def m365_baseline_query(client_id: uuid.UUID) -> Any:
    """The client's Microsoft 365 baseline row: the one CIPP sends under its own source. Every other tool's checks (training, backups, the tools in ``TOOL_CHECK_SOURCES``) are rows of their own."""
    return select(ClientM365Check).where(ClientM365Check.tenant_id == client_id, ClientM365Check.source == CIPP_BASELINE_SOURCE)


class M365ChecksReport(BaseModel):
    vendor: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    vendor_client_id: str = Field(min_length=1, max_length=200)
    checks: list[M365CheckIn] = Field(default_factory=list, max_length=80)
    # Where the checks are kept when that is not the tool's own name (CIPP's Microsoft 365 baseline is its own name; its extra checks are "cipp-health"). Only a tool in ``TOOL_CHECK_SOURCES`` may name
    # a source, and only its own, so a report can never overwrite another tool's rows or the baseline.
    source: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")

    @model_validator(mode="after")
    def _own_source_only(self) -> M365ChecksReport:
        if self.source is not None and TOOL_CHECK_SOURCES.get(self.source) != self.vendor:
            raise ValueError(f"{self.vendor} may not write checks under {self.source}")
        return self


class _M365View:
    """Lets the shared client mapping place a report that belongs to one client, as a list of one item."""

    def __init__(self, report: M365ChecksReport) -> None:
        self.vendor = report.vendor
        self.items = [report]


async def apply_m365_checks(db: Any, owner: uuid.UUID, report: M365ChecksReport, now: datetime | None = None) -> VcioReviewResponse:
    """Replace the client's Microsoft 365 baseline checks with this report. The caller owns the transaction."""
    now = now or datetime.now(UTC)
    by_tenant, unmapped, ignored, waiting = await targets_by_tenant(db, owner, _M365View(report))
    accepted = 0
    weights = await load_weights(
        db, owner
    )  # the owner's weights are read here, in the owner's scope: the client scope below cannot see them
    for tid in by_tenant:
        async with acting_as_tenant(db, tid):
            source = report.source or report.vendor
            new_checks = [c.model_dump() for c in report.checks]
            # What changed since the last report goes into the history (a check appearing, or its status moving), so the page can say since when and show a trend.
            previous = (
                await db.execute(select(ClientM365Check.checks).where(ClientM365Check.tenant_id == tid, ClientM365Check.source == source))
            ).scalar_one_or_none()
            for change in check_changes(previous, new_checks, source):
                db.add(ClientCheckHistory(tenant_id=tid, observed_at=now, **change))
            try:
                async with db.begin_nested():  # an older database without the table must not lose the checks
                    for event in item_changes(previous, new_checks):
                        db.add(ClientCheckItemHistory(tenant_id=tid, observed_at=now, **event))
            except Exception:  # noqa: BLE001
                logger.warning("item history not recorded for %s", tid, exc_info=True)
            values = {"tenant_id": tid, "source": source, "checks": new_checks, "refreshed_at": now}
            stmt = pg_insert(ClientM365Check).values(values)
            update = {c: stmt.excluded[c] for c in values if c not in ("tenant_id", "source")}
            await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "source"], set_=update))
            try:
                async with (
                    db.begin_nested()
                ):  # a failure to keep the daily score (an older database without the table) must not lose the checks
                    await record_today(db, tid, now, weights)
            except Exception:  # noqa: BLE001
                logger.warning("score history not recorded for %s", tid, exc_info=True)
            accepted += 1
    fleet_cache.clear()
    return VcioReviewResponse(accepted=accepted, unmapped=unmapped, ignored=ignored, unmapped_clients=waiting)


class AnswerIn(BaseModel):
    section: str
    key: str = Field(max_length=400)
    # A typed status (replaces the one A.C.O.R.N worked out), and for the technology questions a typed answer; either, both or neither. A note changes no answer.
    status: str | None = None
    answer: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=4000)


class AnswerOut(BaseModel):
    section: str
    key: str
    status: str | None = None
    answer: str | None = None
    note: str | None = None
    updated_at: datetime | None = None
    # True when the row was removed because nothing was left in it (every field empty).
    cleared: bool = False


async def _own_or_client(db: Any, owner: uuid.UUID, client_id: uuid.UUID) -> None:
    if client_id != owner:
        found = (await db.execute(select(Tenant.id).where(Tenant.id == client_id, Tenant.parent_tenant_id == owner))).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=404, detail="Client not found")


@router.put("/{client_id}/answers", response_model=AnswerOut, summary="Type an answer or a note into one question of a client's review")
async def save_review_answer(
    client_id: uuid.UUID, body: AnswerIn, current_user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession
) -> AnswerOut:
    """Set a question's status or answer (replacing the one A.C.O.R.N worked out) and/or add a note. Sending nothing in all three fields clears the question back to the automatic answer."""
    owner = current_user.tenant_id
    await _own_or_client(db, owner, client_id)
    st, ans, note = clean_answer(body.section, body.key, body.status, body.answer, body.note)
    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        existing = (
            await db.execute(
                select(ClientReviewAnswer).where(
                    ClientReviewAnswer.tenant_id == client_id,
                    ClientReviewAnswer.section == body.section,
                    ClientReviewAnswer.key == body.key,
                )
            )
        ).scalar_one_or_none()
        if st is None and ans is None and note is None:
            if existing is not None:
                await db.delete(existing)
                await review_history.record_manual(
                    db, client_id, body.section, body.key, status=None, answer=None, note=None, actor=current_user.email, cleared=True
                )
                await db.commit()
            return AnswerOut(section=body.section, key=body.key, cleared=True)
        if existing is None:
            count = (
                await db.execute(select(func.count()).select_from(ClientReviewAnswer).where(ClientReviewAnswer.tenant_id == client_id))
            ).scalar_one()
            if count >= MAX_PER_CLIENT:
                raise HTTPException(status_code=422, detail=f"A client can have at most {MAX_PER_CLIENT} typed answers")
        now = datetime.now(UTC)
        values = {
            "tenant_id": client_id,
            "section": body.section,
            "key": body.key,
            "status": st,
            "answer": ans,
            "note": note,
            "updated_by": current_user.user_id,
            "updated_at": now,
        }
        stmt = pg_insert(ClientReviewAnswer).values(values)
        update = {c: stmt.excluded[c] for c in values if c not in ("tenant_id", "section", "key")}
        await db.execute(stmt.on_conflict_do_update(index_elements=["tenant_id", "section", "key"], set_=update))
        await review_history.record_manual(
            db, client_id, body.section, body.key, status=st, answer=ans, note=note, actor=current_user.email, now=now
        )
        await db.commit()
    return AnswerOut(section=body.section, key=body.key, status=st, answer=ans, note=note, updated_at=now)


@ingest_router.post("/core-feed/{tenant_token}/m365-checks", response_model=VcioReviewResponse)
async def report_core_feed_m365_checks(tenant_token: str, body: M365ChecksReport, db: DBSession) -> VcioReviewResponse:
    """Record one client's Microsoft 365 baseline checks (replacing the last report)."""
    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    result = await apply_m365_checks(db, owner, body)
    await db.commit()
    return result


class SweepRunIn(BaseModel):
    source: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    title: str = Field(min_length=1, max_length=120)
    accounts: int = Field(ge=0, le=100000)
    sent: int = Field(ge=0, le=100000)
    failed: int = Field(ge=0, le=100000)
    waiting: int = Field(ge=0, le=100000)
    skipped: int = Field(ge=0, le=100000)
    first_error: str = Field(default="", max_length=300)


class SweepRunsReport(BaseModel):
    runs: list[SweepRunIn] = Field(min_length=1, max_length=60)


class SweepRunsResponse(BaseModel):
    updated: int


async def apply_sweep_runs(db: Any, owner: uuid.UUID, report: SweepRunsReport, now: datetime | None = None) -> int:
    """Keep the latest pass of each sweep CORE ran. The caller owns the transaction."""
    now = now or datetime.now(UTC)
    for run in report.runs:
        values = {"tenant_id": owner, "ran_at": now, **run.model_dump()}
        stmt = pg_insert(CoreSweepRun).values(values)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["tenant_id", "source"], set_={c: stmt.excluded[c] for c in values if c not in ("tenant_id", "source")}
            )
        )
    return len(report.runs)


@ingest_router.post("/core-feed/{tenant_token}/sweep-runs", response_model=SweepRunsResponse)
async def report_core_feed_sweep_runs(tenant_token: str, body: SweepRunsReport, db: DBSession) -> SweepRunsResponse:
    """Record the latest pass of each of CORE's per-client sweeps (how many clients it reached, and why some did not)."""
    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    updated = await apply_sweep_runs(db, owner, body)
    await db.commit()
    return SweepRunsResponse(updated=updated)


class ReviewVcio(BaseModel):
    recommendations: VcioRecommendations
    risks: list[VcioRisk]
    refreshed_at: datetime


class ClientReview(BaseModel):
    client_id: uuid.UUID
    client_name: str | None
    generated_at: datetime
    window_days: int
    devices: DeviceFacts
    # The people counts (see /identity/mfa-summary); None when no multi-factor data has arrived for this client.
    mfa: dict[str, int] | None
    secure_score: ReviewScore | None
    alerts: ReviewAlerts
    cases: ReviewCases
    readiness: Readiness
    # What vCIO Toolbox holds for the client (recommendations by adoption, the pending ones that matter most, risks); None when CORE has not sent it.
    vcio: ReviewVcio | None = None
    # Suggested answers to the vCIO Toolbox review template's technology questions, from what A.C.O.R.N can see (nothing is sent to vCIO Toolbox).
    tech_stack: list[TechAnswer] = Field(default_factory=list)
    # Suggested answers to the template's Microsoft 365 questions (checks CORE read through CIPP, plus the multi-factor list); the rest are needs_person.
    m365: list[M365Answer] = Field(default_factory=list)
    m365_refreshed_at: datetime | None = None
    # Suggested answers to the template's infrastructure, workstation, backup and Google Workspace questions, only where a check A.C.O.R.N runs speaks to one; the rest are needs_person.
    assess: list[AssessAnswer] = Field(default_factory=list)


class HistoryEntry(BaseModel):
    at: datetime
    source: str  # automatic: A.C.O.R.N's own reading changed; manual: a person typed
    status: str | None = None
    detail: str | None = None
    note: str | None = None
    actor: str | None = None


@router.get(
    "/{client_id}/history",
    response_model=list[HistoryEntry],
    summary="The changes to one question of a client's review over time: A.C.O.R.N's own readings and what people typed",
)
async def question_history(
    client_id: uuid.UUID,
    section: Annotated[str, Query(pattern="^(readiness|tech|m365|assess)$")],
    key: Annotated[str, Query(min_length=1, max_length=400)],
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
) -> list[HistoryEntry]:
    await _own_or_client(db, current_user.tenant_id, client_id)
    async with contextlib.nullcontext() if client_id == current_user.tenant_id else acting_as_tenant(db, client_id):
        rows = await review_history.history(db, client_id, section, key)
    return [HistoryEntry(**r) for r in rows]


@router.get(
    "/{client_id}",
    response_model=ClientReview,
    summary="One client's coverage, identity, alerts and cases for a review, with a cyber-insurance readiness checklist",
)
async def client_review(
    client_id: uuid.UUID, current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: DBSession
) -> ClientReview:
    owner = current_user.tenant_id
    if client_id != owner:
        found = (await db.execute(select(Tenant.id).where(Tenant.id == client_id, Tenant.parent_tenant_id == owner))).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=404, detail="Client not found")
    scope, clients = await _scope(db, owner, client_id)
    master = _master_of(await db.get(Tenant, owner))
    shown = [d for d in await _load_cached(db, owner, scope, clients, master) if d.hidden_since is None]
    rolled = devices_part(rollup_of(shown), client_id)
    # Which tools this client is mapped to an organization in (a tool with no mapped client at all cannot say).
    aliases = (
        await db.execute(
            select(ClientAlias.vendor, ClientAlias.child_tenant_id).where(
                ClientAlias.tenant_id == owner, ClientAlias.ignored.is_(False), ClientAlias.child_tenant_id.is_not(None)
            )
        )
    ).all()
    facts = device_facts(
        shown,
        stale_agents=rolled.stale_agents,
        offline=rolled.offline,
        enrolled_in={v for v, tid in aliases if tid == client_id},
        mapped_tools={v for v, _ in aliases},
    )

    now = datetime.now(UTC)
    since = now - timedelta(days=WINDOW_DAYS)
    async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
        users = (await db.execute(select(IdentityMfaUser).where(IdentityMfaUser.tenant_id == client_id))).scalars().all()
        score_row = (await db.execute(select(IdentitySecureScore).where(IdentitySecureScore.tenant_id == client_id))).scalars().first()
        vcio_row = (await db.execute(select(ClientVcioReview).where(ClientVcioReview.tenant_id == client_id))).scalars().first()
        m365_row = (await db.execute(m365_baseline_query(client_id))).scalars().first()
        sat_row = (
            (await db.execute(select(ClientM365Check).where(ClientM365Check.tenant_id == client_id, ClientM365Check.source == SAT_SOURCE)))
            .scalars()
            .first()
        )
        typed = list((await db.execute(select(ClientReviewAnswer).where(ClientReviewAnswer.tenant_id == client_id))).scalars().all())
        saas_rows = (
            (
                await db.execute(
                    select(ClientM365Check).where(ClientM365Check.tenant_id == client_id, ClientM365Check.source.in_(SAAS_SOURCES))
                )
            )
            .scalars()
            .all()
        )
        tool_rows = (
            (
                await db.execute(
                    select(ClientM365Check).where(
                        ClientM365Check.tenant_id == client_id, ClientM365Check.source.in_(list(TOOL_CHECK_SOURCES))
                    )
                )
            )
            .scalars()
            .all()
        )
        a = (
            await db.execute(
                select(
                    func.count().filter(Alert.status.notin_(FINISHED_STATUSES)),
                    func.count().filter(and_(Alert.status.notin_(FINISHED_STATUSES), Alert.severity == "critical")),
                    func.count().filter(and_(Alert.status.notin_(FINISHED_STATUSES), Alert.severity == "high")),
                    func.count().filter(Alert.created_at >= since),
                    func.count().filter(and_(Alert.status.in_(FINISHED_STATUSES), Alert.updated_at >= since)),
                ).where(Alert.tenant_id == client_id)
            )
        ).one()
        c = (
            await db.execute(
                text(
                    "SELECT count(*) FILTER (WHERE status NOT IN :done), count(*) FILTER (WHERE created_at >= :since), "
                    "count(*) FILTER (WHERE status IN :done AND updated_at >= :since) FROM cases WHERE tenant_id = :t"
                ).bindparams(bindparam("done", expanding=True)),
                {"t": client_id, "since": since, "done": list(_CASE_FINISHED)},
            )
        ).one()

    mfa = counts_for_mfa(list(users)) if users else None
    score = (
        ReviewScore(
            percent=round(100 * float(score_row.current_score) / float(score_row.max_score), 1) if float(score_row.max_score) > 0 else 0.0,
            current=float(score_row.current_score),
            max=float(score_row.max_score),
            average=float(score_row.average_score) if score_row.average_score is not None else None,
            taken_at=score_row.taken_at,
        )
        if score_row is not None
        else None
    )
    sat_checks = [c for c in (sat_row.checks if sat_row is not None else []) if isinstance(c, dict)]
    # Each cloud backup tool's checks, tagged with the tool that sent them so the answer can name it.
    saas_checks = [{**c, "source": row.source} for row in saas_rows for c in (row.checks or []) if isinstance(c, dict)]
    tool_checks = {c["key"]: c for row in tool_rows for c in (row.checks or []) if isinstance(c, dict) and isinstance(c.get("key"), str)}
    ready = readiness(
        facts,
        mfa,
        score.percent if score else None,
        sat=sat_checks,
        devices=shown,
        saas=saas_checks,
        enrolled_in={v for v, tid in aliases if tid == client_id},
        tool_checks=tool_checks,
    )
    tech_answers = tech_stack(
        shown,
        facts,
        has_microsoft_365=bool(users),
        sat=sat_checks,
        saas=saas_checks,
        enrolled_in={v for v, tid in aliases if tid == client_id},
        mapped_tools={v for v, _ in aliases},
    )
    m365_worked = m365_answers([c for c in (m365_row.checks if m365_row is not None else []) if isinstance(c, dict)], list(users))
    assess_worked = assessment_answers({**tool_checks, **{c["key"]: c for c in sat_checks if isinstance(c.get("key"), str)}})
    # What A.C.O.R.N worked out, before a person's typed answers are laid over it (the merge changes these objects): kept so each question has a history.
    readings = review_history.snapshot(ready.items, tech_answers, m365_worked, assess_worked)
    try:
        async with contextlib.nullcontext() if client_id == owner else acting_as_tenant(db, client_id):
            async with db.begin_nested():
                written = await review_history.record_automatic(db, client_id, readings, now)
            if written:
                await db.commit()
    except Exception:  # noqa: BLE001 - the history is a convenience; the review itself must still load
        logger.warning("client_review.history_not_recorded", exc_info=True)
    merge_readiness(ready.items, typed)
    counts = readiness_counts(ready.items)
    ready.met, ready.partly, ready.not_met, ready.unknown = counts["met"], counts["partly"], counts["not_met"], counts["unknown"]
    return ClientReview(
        client_id=client_id,
        client_name=clients.get(client_id),
        generated_at=now,
        window_days=WINDOW_DAYS,
        devices=facts,
        mfa=mfa,
        secure_score=score,
        alerts=ReviewAlerts(open=a[0], critical_open=a[1], high_open=a[2], opened_30d=a[3], closed_30d=a[4]),
        cases=ReviewCases(open=c[0], opened_30d=c[1], resolved_30d=c[2]),
        readiness=ready,
        tech_stack=merge_tech(tech_answers, typed),
        m365=merge_m365(m365_worked, typed),
        m365_refreshed_at=m365_row.refreshed_at if m365_row is not None else None,
        assess=merge_assess(assess_worked, typed),
        vcio=(
            ReviewVcio(
                recommendations=VcioRecommendations(**(vcio_row.recommendations or {})),
                risks=[VcioRisk(**r) for r in (vcio_row.risks or []) if isinstance(r, dict)],
                refreshed_at=vcio_row.refreshed_at,
            )
            if vcio_row is not None
            else None
        ),
    )


class CoreToolIn(BaseModel):
    tool_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,59}$")
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=300)
    connected: bool


class CoreToolsReport(BaseModel):
    tools: list[CoreToolIn] = Field(max_length=200)


class CoreToolsResponse(BaseModel):
    updated: int


async def apply_core_tools(db: Any, owner: uuid.UUID, report: CoreToolsReport, now: datetime | None = None) -> int:
    """Keep exactly the tools CORE listed (a tool CORE no longer lists is dropped). The caller owns the transaction."""
    now = now or datetime.now(UTC)
    seen: dict[str, CoreToolIn] = {t.tool_id: t for t in report.tools}
    await db.execute(
        delete(CoreTool).where(CoreTool.tenant_id == owner, CoreTool.tool_id.not_in(list(seen)))
        if seen
        else delete(CoreTool).where(CoreTool.tenant_id == owner)
    )
    for tool in seen.values():
        values = {"tenant_id": owner, "reported_at": now, **tool.model_dump()}
        stmt = pg_insert(CoreTool).values(values)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=["tenant_id", "tool_id"], set_={c: stmt.excluded[c] for c in values if c not in ("tenant_id", "tool_id")}
            )
        )
    return len(seen)


@ingest_router.post("/core-feed/{tenant_token}/tools", response_model=CoreToolsResponse)
async def report_core_feed_tools(tenant_token: str, body: CoreToolsReport, db: DBSession) -> CoreToolsResponse:
    """Record which of the owner's tools are connected in CORE, so the Connectors page can list them (only the name, one line about it and whether it is connected; never a credential)."""
    owner = await _verify_core_feed_token(db, tenant_token)
    await adopt_tenant(db, owner)
    updated = await apply_core_tools(db, owner, body)
    await db.commit()
    return CoreToolsResponse(updated=updated)

"""vCIO Risk Scoring: a client's Business Review, answered question by question and scored by risk (Live Oak's scoring workbook, kept here instead of in a spreadsheet per client).

- ``GET /vcio-risk-scoring/library``: the questions and the default settings.
- ``GET /vcio-risk-scoring/assessments``: the assessments of one client or of every client, newest first, each with its score.
- ``POST /vcio-risk-scoring/assessments``: start one for a client.
- ``GET /vcio-risk-scoring/assessments/{id}``: one assessment with its answers and its scorecard.
- ``PATCH /vcio-risk-scoring/assessments/{id}``: its date, platform, assessor, or a question's severity.
- ``PUT /vcio-risk-scoring/assessments/{id}/answers``: answer questions (or clear answers).
- ``POST /vcio-risk-scoring/assessments/{id}/autofill``: fill in what the integrations can answer, from the client's Client Review.
- ``DELETE /vcio-risk-scoring/assessments/{id}``.
- ``GET`` and ``PUT /vcio-risk-scoring/settings``: the organisation's scoring settings (points, credits, cap, rating bands, category weights). One set for every client, changed only by
  someone who may change settings; saving them scores every assessment again.

The scoring itself is in ``app.services.vcio_risk_scoring``. Every write stores the score, so the list never has to score again.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.db.rls_scope import acting_as_tenant, cross_tenant_reads
from app.models.tenant import Tenant
from app.models.vcio_risk_assessment import VcioRiskAssessment
from app.services import vcio_risk_scoring as rs
from app.services.audit import emit_audit

router = APIRouter(prefix="/vcio-risk-scoring", tags=["vcio"])

Reader = Annotated[AuthUser, Depends(require_permission("alerts:read"))]
Writer = Annotated[AuthUser, Depends(require_permission("mssp:manage"))]
Platform = Literal["m365", "google", "both"]
NOTE_MAX = 2000
VENDOR_MAX = 200


class LibraryOut(BaseModel):
    questions: list[dict[str, Any]]
    categories: list[str]
    csf_functions: list[str]
    severities: list[str]
    yesno_answers: list[str]
    vendor_answers: list[str]
    defaults: dict[str, Any]


class AssessmentSummary(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    client_name: str | None
    review_date: date
    platform: str
    assessor: str
    score: float | None
    rating: str
    answered: int
    updated_at: datetime
    updated_by: str | None


class AssessmentList(BaseModel):
    items: list[AssessmentSummary]


class AnswerOut(BaseModel):
    answer: str | None = None
    vendor: str | None = None
    note: str | None = None
    # "auto" when the answer was filled in from the integrations (through the client's Client Review) and nobody has changed it; ``evidence`` is what they saw.
    source: str | None = None
    evidence: str | None = None


class AssessmentOut(AssessmentSummary):
    answers: dict[str, AnswerOut]
    severity: dict[str, str]
    scorecard: dict[str, Any]


class AssessmentIn(BaseModel):
    client_id: uuid.UUID | None = Field(default=None, description="The client assessed; left out, the caller's own organisation.")
    review_date: date | None = None
    platform: Platform = "m365"
    assessor: str = Field(default="", max_length=200)


class AssessmentPatch(BaseModel):
    review_date: date | None = None
    platform: Platform | None = None
    assessor: str | None = Field(default=None, max_length=200)
    severity: dict[str, str | None] | None = Field(
        default=None, description="Question id -> the severity to use for it; null puts the library's back."
    )


class AnswerIn(BaseModel):
    id: str = Field(min_length=1, max_length=20)
    answer: str | None = Field(default=None, max_length=20, description="Null clears the answer.")
    vendor: str | None = Field(default=None, max_length=VENDOR_MAX)
    note: str | None = Field(default=None, max_length=NOTE_MAX)


class AnswersIn(BaseModel):
    items: list[AnswerIn] = Field(min_length=1, max_length=400)


class DeletedOut(BaseModel):
    deleted: bool


async def _clients(db: Any, owner: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == owner))).all()
    return {r.id: r.name for r in rows}


def _acting(db: Any, owner: uuid.UUID, tid: uuid.UUID) -> Any:
    return contextlib.nullcontext() if tid == owner else acting_as_tenant(db, tid)


def plain_answers(stored: dict[str, Any]) -> dict[str, str]:
    """Question id -> the answer alone, for the scoring (the vendor and the note do not score)."""
    out: dict[str, str] = {}
    for qid, entry in (stored or {}).items():
        value = entry.get("answer") if isinstance(entry, dict) else None
        if isinstance(value, str) and value:
            out[qid] = value
    return out


SETTINGS_KEY = "vcio_risk_scoring"


async def org_settings(db: Any, owner: uuid.UUID) -> dict[str, Any]:
    """The scoring settings of the organisation (one set for all its clients, changed under Settings), or nothing when it uses the defaults."""
    tenant = await db.get(Tenant, owner)
    found = (tenant.settings or {}).get(SETTINGS_KEY) if tenant is not None else None
    return found if isinstance(found, dict) else {}


def _card(row: VcioRiskAssessment, org: dict[str, Any]) -> dict[str, Any]:
    return rs.scorecard(
        plain_answers(row.answers), row.platform, {k: v for k, v in (row.severity or {}).items() if isinstance(v, str)}, org
    )


def _store_score(row: VcioRiskAssessment, user: AuthUser | None, org: dict[str, Any]) -> dict[str, Any]:
    card = _card(row, org)
    row.score = card["overall"]
    row.rating = card["rating"]
    row.answered = card["answered"]
    if user is not None:
        row.updated_at = datetime.now(UTC)
        row.updated_by = user.email
    return card


def _summary(row: VcioRiskAssessment, owner: uuid.UUID, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": row.id,
        "client_id": row.tenant_id,
        "client_name": names.get(row.tenant_id),
        "review_date": row.review_date,
        "platform": row.platform,
        "assessor": row.assessor,
        "score": row.score,
        "rating": row.rating,
        "answered": row.answered,
        "updated_at": row.updated_at,
        "updated_by": row.updated_by,
    }


def _full(row: VcioRiskAssessment, owner: uuid.UUID, names: dict[uuid.UUID, str], card: dict[str, Any]) -> AssessmentOut:
    answers = {
        qid: AnswerOut(**{k: v for k, v in entry.items() if k in ("answer", "vendor", "note", "source", "evidence")})
        for qid, entry in (row.answers or {}).items()
        if isinstance(entry, dict)
    }
    return AssessmentOut(
        **_summary(row, owner, names),
        answers=answers,
        severity={k: v for k, v in (row.severity or {}).items() if isinstance(v, str)},
        scorecard=card,
    )


async def _find(db: Any, user: AuthUser, assessment_id: uuid.UUID) -> tuple[VcioRiskAssessment, dict[uuid.UUID, str]]:
    names = await _clients(db, user.tenant_id)
    async with cross_tenant_reads(db):
        found = (
            await db.execute(
                select(VcioRiskAssessment).where(
                    VcioRiskAssessment.id == assessment_id, VcioRiskAssessment.tenant_id.in_([user.tenant_id, *names])
                )
            )
        ).scalar_one_or_none()
    if found is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    return found, names


SettingsReader = Annotated[AuthUser, Depends(require_permission("settings:read"))]
SettingsWriter = Annotated[AuthUser, Depends(require_permission("settings:write"))]


class SettingsOut(BaseModel):
    settings: dict[str, Any]
    defaults: dict[str, Any]
    # True when the organisation has changed nothing: the defaults are in use.
    using_defaults: bool
    rescored: int = 0


class SettingsIn(BaseModel):
    settings: dict[str, Any] = Field(
        description="The settings to use. Anything missing or not valid keeps its default; an empty object goes back to the defaults."
    )


@router.get("/settings", response_model=SettingsOut, summary="The organisation's vCIO Risk Scoring settings")
async def get_settings(current_user: SettingsReader, db: DBSession) -> SettingsOut:
    stored = await org_settings(db, current_user.tenant_id)
    return SettingsOut(settings=rs.merge_settings(stored), defaults=rs.merge_settings(None), using_defaults=not stored)


@router.put(
    "/settings", response_model=SettingsOut, summary="Change the organisation's vCIO Risk Scoring settings and score every assessment again"
)
async def put_settings(body: SettingsIn, current_user: SettingsWriter, db: DBSession) -> SettingsOut:
    owner = current_user.tenant_id
    tenant = await db.get(Tenant, owner)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Organisation not found")
    defaults = rs.merge_settings(None)
    merged = rs.merge_settings(body.settings)
    # Only what was really changed is kept, so a default that changes later still reaches an organisation that never touched it.
    kept = {k: v for k, v in merged.items() if v != defaults[k]} if body.settings else {}
    before = (tenant.settings or {}).get(SETTINGS_KEY) or {}
    settings = dict(tenant.settings or {})
    if kept:
        settings[SETTINGS_KEY] = kept
    else:
        settings.pop(SETTINGS_KEY, None)
    tenant.settings = settings
    await emit_audit(
        db=db,
        tenant_id=owner,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
        action="vcio:risk_settings_changed",
        resource="vcio_risk_settings",
        resource_id=str(owner),
        changes={"before": before, "after": kept},
    )
    # Sent now, in the organisation's own scope: left queued, it would go out inside the first client's scope below and be refused.
    await db.flush()
    # The stored scores (what the list of assessments shows) were worked out with the old settings.
    names = await _clients(db, owner)
    async with cross_tenant_reads(db):
        rows = (
            await db.execute(
                select(VcioRiskAssessment.id, VcioRiskAssessment.tenant_id).where(VcioRiskAssessment.tenant_id.in_([owner, *names]))
            )
        ).all()
    rescored = 0
    for assessment_id, tid in rows:
        async with _acting(db, owner, tid):
            row = (await db.execute(select(VcioRiskAssessment).where(VcioRiskAssessment.id == assessment_id))).scalar_one()
            _store_score(row, None, kept)
            rescored += 1
    await db.commit()
    return SettingsOut(settings=merged if kept else defaults, defaults=defaults, using_defaults=not kept, rescored=rescored)


@router.get("/library", response_model=LibraryOut, summary="The vCIO Risk Scoring questions and the default scoring settings")
async def get_library(current_user: Reader) -> LibraryOut:
    return LibraryOut(
        questions=list(rs.library()),
        categories=list(rs.CATEGORY_ORDER),
        csf_functions=list(rs.CSF_ORDER),
        severities=list(rs.SEVERITIES),
        yesno_answers=list(rs.YESNO_ANSWERS),
        vendor_answers=list(rs.VENDOR_ANSWERS),
        defaults=rs.merge_settings(None),
    )


@router.get(
    "/assessments", response_model=AssessmentList, summary="The risk-scored reviews of one client, or of every client, newest first"
)
async def list_assessments(
    current_user: Reader,
    db: DBSession,
    client_id: uuid.UUID | None = Query(default=None, description="One client (or the caller's own organisation); left out, every client."),
) -> AssessmentList:
    owner = current_user.tenant_id
    names = await _clients(db, owner)
    if client_id is not None and client_id != owner and client_id not in names:
        return AssessmentList(items=[])
    scope = [client_id] if client_id is not None else [owner, *names]
    async with cross_tenant_reads(db):
        rows = (
            (
                await db.execute(
                    select(VcioRiskAssessment)
                    .where(VcioRiskAssessment.tenant_id.in_(scope))
                    .order_by(VcioRiskAssessment.review_date.desc(), VcioRiskAssessment.created_at.desc())
                    .limit(500)
                )
            )
            .scalars()
            .all()
        )
    return AssessmentList(items=[AssessmentSummary(**_summary(r, owner, names)) for r in rows])


@router.post("/assessments", response_model=AssessmentOut, status_code=201, summary="Start a risk-scored review for a client")
async def create_assessment(body: AssessmentIn, current_user: Writer, db: DBSession) -> AssessmentOut:
    owner = current_user.tenant_id
    org = await org_settings(db, owner)
    names = await _clients(db, owner)
    target = body.client_id or owner
    if target != owner and target not in names:
        raise HTTPException(status_code=404, detail="Client not found")
    async with _acting(db, owner, target):
        row = VcioRiskAssessment(
            id=uuid.uuid4(),
            tenant_id=target,
            review_date=body.review_date or datetime.now(UTC).date(),
            platform=body.platform,
            assessor=body.assessor.strip(),
            answers={},
            severity={},
            settings={},
            created_by=current_user.email,
        )
        card = _store_score(row, current_user, org)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return _full(row, owner, names, card)


@router.get("/assessments/{assessment_id}", response_model=AssessmentOut, summary="One risk-scored review: its answers and its scorecard")
async def get_assessment(assessment_id: uuid.UUID, current_user: Reader, db: DBSession) -> AssessmentOut:
    row, names = await _find(db, current_user, assessment_id)
    return _full(row, current_user.tenant_id, names, _card(row, await org_settings(db, current_user.tenant_id)))


@router.patch(
    "/assessments/{assessment_id}",
    response_model=AssessmentOut,
    summary="Change a review's date, platform, assessor or a question's severity",
)
async def update_assessment(assessment_id: uuid.UUID, body: AssessmentPatch, current_user: Writer, db: DBSession) -> AssessmentOut:
    owner = current_user.tenant_id
    org = await org_settings(db, owner)
    seen, names = await _find(db, current_user, assessment_id)
    known = rs.questions_by_id()
    for qid, sev in (body.severity or {}).items():
        if qid not in known:
            raise HTTPException(status_code=422, detail=f"There is no question {qid}")
        if sev is not None and sev not in rs.SEVERITIES:
            raise HTTPException(status_code=422, detail=f"{sev} is not a severity: use Critical, High, Medium or Low")
    async with _acting(db, owner, seen.tenant_id):
        row = (await db.execute(select(VcioRiskAssessment).where(VcioRiskAssessment.id == seen.id))).scalar_one()
        if body.review_date is not None:
            row.review_date = body.review_date
        if body.platform is not None:
            row.platform = body.platform
        if body.assessor is not None:
            row.assessor = body.assessor.strip()
        if body.severity is not None:
            merged = dict(row.severity or {})
            for qid, sev in body.severity.items():
                if sev is None or sev == known[qid]["severity"]:
                    merged.pop(qid, None)
                else:
                    merged[qid] = sev
            row.severity = merged
        card = _store_score(row, current_user, org)
        await db.commit()
        await db.refresh(row)
    return _full(row, owner, names, card)


@router.put(
    "/assessments/{assessment_id}/answers", response_model=AssessmentOut, summary="Answer questions of a review, or clear their answers"
)
async def put_answers(assessment_id: uuid.UUID, body: AnswersIn, current_user: Writer, db: DBSession) -> AssessmentOut:
    owner = current_user.tenant_id
    org = await org_settings(db, owner)
    seen, names = await _find(db, current_user, assessment_id)
    known = rs.questions_by_id()
    for item in body.items:
        question = known.get(item.id)
        if question is None:
            raise HTTPException(status_code=422, detail=f"There is no question {item.id}")
        if item.answer is not None and item.answer not in rs.allowed_answers(question):
            raise HTTPException(
                status_code=422, detail=f"{item.answer} is not an answer to {item.id}: use one of {', '.join(rs.allowed_answers(question))}"
            )
    async with _acting(db, owner, seen.tenant_id):
        row = (await db.execute(select(VcioRiskAssessment).where(VcioRiskAssessment.id == seen.id))).scalar_one()
        merged = {k: dict(v) for k, v in (row.answers or {}).items() if isinstance(v, dict)}
        for item in body.items:
            entry = {
                "answer": item.answer or None,
                "vendor": (item.vendor or "").strip() or None,
                "note": (item.note or "").strip() or None,
            }
            entry = {k: v for k, v in entry.items() if v is not None}
            before = merged.get(item.id, {})
            # Adding a note to an answer the integrations filled in does not make it a hand answer: only changing the answer (or the vendor) does.
            if before.get("source") == "auto" and (before.get("answer"), before.get("vendor")) == (
                entry.get("answer"),
                entry.get("vendor"),
            ):
                entry = {**entry, "source": "auto", **({"evidence": before["evidence"]} if before.get("evidence") else {})}
            if entry:
                merged[item.id] = entry
            else:
                merged.pop(item.id, None)
        row.answers = merged
        card = _store_score(row, current_user, org)
        await db.commit()
        await db.refresh(row)
    return _full(row, owner, names, card)


class AutofillOut(BaseModel):
    assessment: AssessmentOut
    filled: int
    changed: int
    kept_by_hand: int
    cleared: int
    answered_by_integrations: int


async def review_answers(db: Any, user: AuthUser, client_id: uuid.UUID) -> dict[str, dict[str, str]]:
    """What the client's Client Review answers, as answers to the questions here (question id -> answer, evidence and vendor). The review is built exactly as its own page builds it, so
    the two never disagree: the same checks, the same typed answers."""
    from app.api.v1.endpoints.client_review import (
        client_review,  # noqa: PLC0415 - the review imports half the API; only this route needs it
    )

    review = await client_review(client_id, user, db)
    return rs.answers_from_review(list(review.assess), list(review.m365), list(review.tech_stack))


@router.post(
    "/assessments/{assessment_id}/autofill",
    response_model=AutofillOut,
    summary="Fill in the answers the integrations can give (through the client's Client Review), never replacing one set by hand",
)
async def autofill_assessment(assessment_id: uuid.UUID, current_user: Writer, db: DBSession) -> AutofillOut:
    owner = current_user.tenant_id
    org = await org_settings(db, owner)
    seen, names = await _find(db, current_user, assessment_id)
    # Kept now: building the review ends the transaction the assessment was read in, and reading its fields afterwards would need the database again.
    client_id, found_id = seen.tenant_id, seen.id
    found = await review_answers(db, current_user, client_id)
    async with _acting(db, owner, client_id):
        row = (await db.execute(select(VcioRiskAssessment).where(VcioRiskAssessment.id == found_id))).scalar_one()
        row.answers, counts = rs.apply_autofill(row.answers, found)
        card = _store_score(row, current_user, org)
        await db.commit()
        await db.refresh(row)
    return AutofillOut(assessment=_full(row, owner, names, card), **counts)


@router.delete("/assessments/{assessment_id}", response_model=DeletedOut, summary="Delete a risk-scored review for good")
async def delete_assessment(assessment_id: uuid.UUID, current_user: Writer, db: DBSession) -> DeletedOut:
    owner = current_user.tenant_id
    seen, names = await _find(db, current_user, assessment_id)
    what = {
        "client_id": str(seen.tenant_id),
        "client_name": names.get(seen.tenant_id),
        "review_date": seen.review_date.isoformat(),
        "score": seen.score,
        "answered": seen.answered,
    }
    found_id, client_id = seen.id, seen.tenant_id
    # The row is the client's, so it is removed in the client's scope. The audit line is the organisation's, so it is written after that scope ends: written inside it, row-level security
    # refuses the line (it belongs to another tenant than the one being acted as) and the whole deletion fails.
    async with _acting(db, owner, client_id):
        await db.execute(VcioRiskAssessment.__table__.delete().where(VcioRiskAssessment.id == found_id))
    await emit_audit(
        db=db,
        tenant_id=owner,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
        action="vcio:risk_assessment_deleted",
        resource="vcio_risk_assessment",
        resource_id=str(found_id),
        changes=what,
    )
    await db.commit()
    return DeletedOut(deleted=True)

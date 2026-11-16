"""Security questionnaires (Secureframe parity plan): an answer library, and customer questionnaires answered from it.

Paste a customer's questions (one to a line): each is matched to the library by shared words and, when at least half the words line up, drafted with that library answer. A draft is not an answer until a person
approves it; a question with no good match stays blank. An approved answer can be saved into the library for next time. A questionnaire is completed when every question is approved, and exported as CSV. Read with
``reports:read``, change with ``reports:write``; ``client_id`` reads or writes one of the caller's clients.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.compliance import ScopeTenant
from app.models.questionnaire import Questionnaire, QuestionnaireAnswer, QuestionnaireItem
from app.services import compliance_audit as audit
from app.services import questionnaires as rules

router = APIRouter(prefix="/compliance/questionnaires", tags=["compliance"])
library_router = APIRouter(prefix="/compliance/answer-library", tags=["compliance"])

CATEGORIES = (
    "General",
    "Access and identity",
    "Data protection",
    "Incident response",
    "Business continuity",
    "Vendors",
    "People",
    "Physical security",
    "Policies and compliance",
)


class LibraryIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    answer: str = Field(min_length=1, max_length=10_000)
    category: str = Field(default="General", max_length=80)


class LibraryPatch(BaseModel):
    question: str | None = Field(default=None, min_length=3, max_length=2000)
    answer: str | None = Field(default=None, min_length=1, max_length=10_000)
    category: str | None = Field(default=None, max_length=80)
    confirm: bool = False  # "still true": today becomes the date it was last reviewed


class LibraryOut(BaseModel):
    id: uuid.UUID
    question: str
    answer: str
    category: str
    last_reviewed: date | None
    updated_at: datetime


class QuestionnaireIn(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    customer: str | None = Field(default=None, max_length=200)
    due_date: date | None = None
    questions: str = Field(min_length=3, max_length=200_000)
    # "csv": the text is the contents of a CSV file with the questions in one column (see rules.questions_from_csv).
    format: Literal["lines", "csv"] = "lines"


class ItemPatch(BaseModel):
    answer: str | None = Field(default=None, max_length=10_000)
    approved: bool | None = None
    save_to_library: bool = False


class ItemOut(BaseModel):
    id: uuid.UUID
    position: int
    question: str
    answer: str
    source: str
    match_score: int
    approved: bool
    approved_by: str | None


class QuestionnaireOut(BaseModel):
    id: uuid.UUID
    name: str
    customer: str | None
    due_date: date | None
    status: str
    overdue: bool
    questions: int
    approved: int
    drafted: int  # answered from the library or typed, not approved yet
    blank: int
    created_at: datetime
    completed_at: datetime | None


class QuestionnaireDetail(QuestionnaireOut):
    items: list[ItemOut]


class QuestionnaireList(BaseModel):
    questionnaires: list[QuestionnaireOut]
    library_size: int
    categories: list[str]


def _actor(user: AuthUser) -> str | None:
    return getattr(user, "email", None)


def _library_out(a: QuestionnaireAnswer) -> LibraryOut:
    return LibraryOut(
        id=a.id, question=a.question, answer=a.answer, category=a.category, last_reviewed=a.last_reviewed, updated_at=a.updated_at
    )


def _summary(q: Questionnaire, items: list[QuestionnaireItem], today: date) -> QuestionnaireOut:
    approved = sum(1 for i in items if i.approved)
    blank = sum(1 for i in items if not i.answer.strip())
    return QuestionnaireOut(
        id=q.id,
        name=q.name,
        customer=q.customer,
        due_date=q.due_date,
        status=q.status,
        overdue=q.status == "open" and q.due_date is not None and q.due_date < today,
        questions=len(items),
        approved=approved,
        drafted=len(items) - approved - blank,
        blank=blank,
        created_at=q.created_at,
        completed_at=q.completed_at,
    )


async def _items(db: DBSession, tenant: uuid.UUID, qid: uuid.UUID) -> list[QuestionnaireItem]:
    rows = (
        (
            await db.execute(
                select(QuestionnaireItem).where(QuestionnaireItem.questionnaire_id == qid, QuestionnaireItem.tenant_id == tenant)
            )
        )
        .scalars()
        .all()
    )
    return sorted(rows, key=lambda i: i.position)


async def _questionnaire(db: DBSession, tenant: uuid.UUID, qid: uuid.UUID) -> Questionnaire:
    row = (await db.execute(select(Questionnaire).where(Questionnaire.id == qid, Questionnaire.tenant_id == tenant))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Questionnaire not found")
    return row


async def _detail(db: DBSession, tenant: uuid.UUID, q: Questionnaire) -> QuestionnaireDetail:
    items = await _items(db, tenant, q.id)
    base = _summary(q, items, datetime.now(UTC).date())
    return QuestionnaireDetail(
        **base.model_dump(),
        items=[
            ItemOut(
                id=i.id,
                position=i.position,
                question=i.question,
                answer=i.answer,
                source=i.source,
                match_score=i.match_score,
                approved=i.approved,
                approved_by=i.approved_by,
            )
            for i in items
        ],
    )


async def _library(db: DBSession, tenant: uuid.UUID) -> list[QuestionnaireAnswer]:
    return list(
        (
            await db.execute(
                select(QuestionnaireAnswer)
                .where(QuestionnaireAnswer.tenant_id == tenant, QuestionnaireAnswer.archived_at.is_(None))
                .order_by(QuestionnaireAnswer.created_at)
            )
        ).scalars()
    )


# ---- the answer library ------------------------------------------------------------------------------------------------------------------------------------


@library_router.get("", response_model=list[LibraryOut], summary="The answers kept for next time")
async def list_library(
    tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> list[LibraryOut]:
    return [_library_out(a) for a in await _library(db, tenant)]


@library_router.post("", response_model=LibraryOut, status_code=status.HTTP_201_CREATED, summary="Add an answer to the library")
async def add_library(
    body: LibraryIn, tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> LibraryOut:
    now = datetime.now(UTC)
    row = QuestionnaireAnswer(
        id=uuid.uuid4(),
        tenant_id=tenant,
        question=body.question.strip(),
        answer=body.answer.strip(),
        category=body.category if body.category in CATEGORIES else "General",
        last_reviewed=now.date(),
        created_by=_actor(user),
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    return _library_out(row)


async def _library_row(db: DBSession, tenant: uuid.UUID, aid: uuid.UUID) -> QuestionnaireAnswer:
    row = (
        await db.execute(
            select(QuestionnaireAnswer).where(
                QuestionnaireAnswer.id == aid, QuestionnaireAnswer.tenant_id == tenant, QuestionnaireAnswer.archived_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Answer not found")
    return row


@library_router.patch("/{answer_id}", response_model=LibraryOut, summary="Change an answer, or confirm it is still true")
async def patch_library(
    answer_id: uuid.UUID,
    body: LibraryPatch,
    tenant: ScopeTenant,
    db: DBSession,
    _user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> LibraryOut:
    row = await _library_row(db, tenant, answer_id)
    if body.question is not None:
        row.question = body.question.strip()
    if body.answer is not None:
        row.answer = body.answer.strip()
    if body.category is not None:
        row.category = body.category if body.category in CATEGORIES else "General"
    if body.confirm or body.answer is not None:
        row.last_reviewed = datetime.now(UTC).date()
    row.updated_at = datetime.now(UTC)
    await db.commit()
    return _library_out(row)


@library_router.delete(
    "/{answer_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an answer from the library (it is archived, not deleted)"
)
async def archive_library(
    answer_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> None:
    row = await _library_row(db, tenant, answer_id)
    row.archived_at = datetime.now(UTC)
    await db.commit()


# ---- questionnaires ------------------------------------------------------------------------------------------------------------------------------------------


@router.get("", response_model=QuestionnaireList, summary="The questionnaires, newest first")
async def list_questionnaires(
    tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> QuestionnaireList:
    qs = (
        (await db.execute(select(Questionnaire).where(Questionnaire.tenant_id == tenant).order_by(Questionnaire.created_at.desc())))
        .scalars()
        .all()
    )
    by_q: dict[uuid.UUID, list[QuestionnaireItem]] = {}
    for i in (await db.execute(select(QuestionnaireItem).where(QuestionnaireItem.tenant_id == tenant))).scalars():
        by_q.setdefault(i.questionnaire_id, []).append(i)
    today = datetime.now(UTC).date()
    return QuestionnaireList(
        questionnaires=[_summary(q, by_q.get(q.id, []), today) for q in qs],
        library_size=len(await _library(db, tenant)),
        categories=list(CATEGORIES),
    )


@router.post(
    "",
    response_model=QuestionnaireDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Start a questionnaire from pasted questions, drafting answers from the library",
)
async def start_questionnaire(
    body: QuestionnaireIn, tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> QuestionnaireDetail:
    questions = rules.questions_from_csv(body.questions) if body.format == "csv" else rules.split_questions(body.questions)
    if not questions:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No questions found. Paste them one to a line, or give a CSV file with a Question column.")
    library = await _library(db, tenant)
    q = Questionnaire(
        id=uuid.uuid4(), tenant_id=tenant, name=body.name.strip(), customer=body.customer, due_date=body.due_date, created_by=_actor(user)
    )
    db.add(q)
    await db.flush()
    for n, text_ in enumerate(questions, start=1):
        match, pct = rules.best_match(text_, library)
        db.add(
            QuestionnaireItem(
                id=uuid.uuid4(),
                tenant_id=tenant,
                questionnaire_id=q.id,
                position=n,
                question=text_,
                answer=match.answer if match else "",
                source="library" if match else "none",
                library_id=match.id if match else None,
                match_score=pct,
            )
        )
    await audit.note(db, tenant, user, "questionnaire:started", "questionnaire", q.id, name=q.name, questions=len(questions))
    await db.commit()
    return await _detail(db, tenant, q)


@router.get("/{questionnaire_id}", response_model=QuestionnaireDetail, summary="One questionnaire with every question and its answer")
async def get_questionnaire(
    questionnaire_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> QuestionnaireDetail:
    return await _detail(db, tenant, await _questionnaire(db, tenant, questionnaire_id))


@router.patch(
    "/{questionnaire_id}/items/{item_id}",
    response_model=QuestionnaireDetail,
    summary="Write or change an answer, approve it, and keep it in the library for next time",
)
async def patch_item(
    questionnaire_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ItemPatch,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> QuestionnaireDetail:
    q = await _questionnaire(db, tenant, questionnaire_id)
    if q.status == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That questionnaire is complete and cannot be changed.")
    item = (
        await db.execute(
            select(QuestionnaireItem).where(
                QuestionnaireItem.id == item_id,
                QuestionnaireItem.questionnaire_id == questionnaire_id,
                QuestionnaireItem.tenant_id == tenant,
            )
        )
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    if body.answer is not None and body.answer.strip() != item.answer.strip():
        item.answer = body.answer.strip()
        item.source = "manual" if item.answer else "none"
        item.library_id = None if item.answer else item.library_id
        item.approved, item.approved_by = False, None  # a changed answer needs approving again
    if body.approved is not None:
        if body.approved and not item.answer.strip():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="There is no answer to approve.")
        item.approved = body.approved
        item.approved_by = _actor(user) if body.approved else None
    if body.save_to_library:
        if not item.answer.strip():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="There is no answer to keep.")
        now = datetime.now(UTC)
        entry = QuestionnaireAnswer(
            id=uuid.uuid4(),
            tenant_id=tenant,
            question=item.question,
            answer=item.answer,
            last_reviewed=now.date(),
            created_by=_actor(user),
            created_at=now,
            updated_at=now,
        )
        db.add(entry)
        await db.flush()
        item.library_id = entry.id
    await db.commit()
    return await _detail(db, tenant, q)


@router.post(
    "/{questionnaire_id}/approve-drafts",
    response_model=QuestionnaireDetail,
    summary="Approve every drafted answer that came from the library with a close match",
)
async def approve_drafts(
    questionnaire_id: uuid.UUID,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
    min_score: Annotated[int, Query(ge=0, le=100)] = 80,
) -> QuestionnaireDetail:
    q = await _questionnaire(db, tenant, questionnaire_id)
    if q.status == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That questionnaire is complete and cannot be changed.")
    for i in await _items(db, tenant, questionnaire_id):
        if not i.approved and i.source == "library" and i.match_score >= min_score and i.answer.strip():
            i.approved, i.approved_by = True, _actor(user)
    await audit.note(db, tenant, user, "questionnaire:drafts_approved", "questionnaire", questionnaire_id, min_score=min_score)
    await db.commit()
    return await _detail(db, tenant, q)


@router.post(
    "/{questionnaire_id}/complete", response_model=QuestionnaireDetail, summary="Complete the questionnaire once every question is approved"
)
async def complete_questionnaire(
    questionnaire_id: uuid.UUID,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> QuestionnaireDetail:
    q = await _questionnaire(db, tenant, questionnaire_id)
    if q.status == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That questionnaire is already complete.")
    waiting = sum(1 for i in await _items(db, tenant, questionnaire_id) if not i.approved)
    if waiting:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"{waiting} question{' is' if waiting == 1 else 's are'} not approved yet."
        )
    q.status, q.completed_at = "complete", datetime.now(UTC)
    await audit.note(db, tenant, user, "questionnaire:completed", "questionnaire", questionnaire_id)
    await db.commit()
    return await _detail(db, tenant, q)


@router.delete(
    "/{questionnaire_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a questionnaire and its questions (answers kept in the library stay)",
)
async def delete_questionnaire(
    questionnaire_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, user: Annotated[AuthUser, Depends(require_permission("reports:write"))]
) -> None:
    q = await _questionnaire(db, tenant, questionnaire_id)
    await audit.note(db, tenant, user, "questionnaire:deleted", "questionnaire", questionnaire_id)
    await db.delete(q)
    await db.commit()


@router.get("/{questionnaire_id}/export.csv", summary="The questions and answers as a CSV file for the customer")
async def export_questionnaire(
    questionnaire_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> Response:
    await _questionnaire(db, tenant, questionnaire_id)
    rows = [
        (i.position, i.question, i.answer, "approved" if i.approved else ("draft" if i.answer.strip() else "blank"))
        for i in await _items(db, tenant, questionnaire_id)
    ]
    return Response(
        content=rules.csv_text(rows), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="questionnaire.csv"'}
    )

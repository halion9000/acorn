"""Security questionnaires: splitting and matching questions, then the whole flow on a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database)."""

import csv
import io
import os
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import questionnaires as ep
from app.db.rls import set_rls_context
from app.services import questionnaires as rules
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def lib(question, answer="Yes.", reviewed=None):
    return SimpleNamespace(question=question, answer=answer, last_reviewed=reviewed, id=uuid.uuid4())


def test_pasted_questions_lose_their_numbering_blank_lines_and_repeats():
    pasted = (
        "1. Do you encrypt data at rest?\n\n  2) Do you encrypt data at rest?\n- How often are backups tested?\n(a) Is MFA required?\nok\n"
    )
    assert rules.split_questions(pasted) == ["Do you encrypt data at rest?", "How often are backups tested?", "Is MFA required?"]
    assert len(rules.split_questions("\n".join(f"Question number {i} about security?" for i in range(900)))) == rules.MAX_QUESTIONS


def test_a_question_is_matched_by_shared_meaningful_words_and_a_poor_match_is_not_offered():
    library = [
        lib("Is data encrypted at rest and in transit?", "Yes, AES-256 and TLS 1.2."),
        lib("How often do you test backups?", "Quarterly."),
        lib("Do you have a SOC 2 report?", "Yes, Type II."),
    ]
    match, pct = rules.best_match("Do you encrypt data at rest and in transit?", library)
    assert (
        match is library[0] and pct >= 50
    ), "same words: data, rest, transit (and the stem 'encrypted' vs 'encrypt' differ, the rest line up)"
    assert rules.best_match("What is your office address?", library) == (None, 0)
    assert rules.best_match("anything", []) == (None, 0)
    assert rules.score(frozenset(), frozenset({"a"})) == 0


def test_a_tie_goes_to_the_answer_reviewed_most_recently_then_the_first_listed():
    old, new = (
        lib("How often do you test backups?", "Old.", date(2024, 1, 1)),
        lib("How often do you test backups?", "New.", date(2026, 1, 1)),
    )
    assert rules.best_match("How often are backups tested?", [old, new])[0] is new
    first, second = lib("Is MFA required for staff?"), lib("Is MFA required for staff?")
    assert rules.best_match("Is MFA required for staff?", [first, second])[0] is first


def test_the_csv_has_a_status_per_question_and_a_cell_that_would_run_as_a_formula_is_made_text():
    out = list(csv.reader(io.StringIO(rules.csv_text([(1, "Q one?", "=HYPERLINK(1)", "approved"), (2, "Q two?", "", "blank")]))))
    assert out[0] == ["No.", "Question", "Answer", "Status"]
    assert out[1] == ["1", "Q one?", "'=HYPERLINK(1)", "approved"] and out[2][3] == "blank"


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
needs_pg = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)


@pytest.fixture
async def world():
    acme, birch = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, n in ((acme, "acme"), (birch, "birch")):
            await conn.execute(
                text("insert into tenants (id, name, slug) values (:i, :n, :s)"), {"i": tid, "n": f"qs-{n}", "s": f"qs-{n}-{tid.hex[:8]}"}
            )
    yield SimpleNamespace(
        acme=acme, birch=birch, engine=engine, user=SimpleNamespace(tenant_id=acme, user_id=None, email="hal@goliveoak.com")
    )
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for t in (acme, birch):
            for table in ("questionnaire_items", "questionnaires", "questionnaire_answers"):
                await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": t})
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": [acme, birch]})
    await engine.dispose()


async def run(tenant, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tenant)
            return await work(db)
    finally:
        await engine.dispose()


@needs_pg
@pytest.mark.asyncio
async def test_answers_are_drafted_from_the_library_nothing_is_approved_by_itself_and_completion_needs_every_approval(world):
    w = world
    await run(
        w.acme,
        lambda db: ep.add_library(
            ep.LibraryIn(
                question="Is data encrypted at rest and in transit?",
                answer="Yes: AES-256 at rest, TLS 1.2 in transit.",
                category="Data protection",
            ),
            w.acme,
            db,
            w.user,
        ),
    )
    q = await run(
        w.acme,
        lambda db: ep.start_questionnaire(
            ep.QuestionnaireIn(
                name="Acme Dental vendor review",
                customer="Acme Dental",
                questions="1. Do you encrypt data at rest and in transit?\n2. What is your office address?",
            ),
            w.acme,
            db,
            w.user,
        ),
    )
    assert (q.questions, q.drafted, q.blank, q.approved) == (2, 1, 1, 0)
    first, second = q.items
    assert first.source == "library" and first.answer.startswith("Yes: AES-256") and not first.approved and first.match_score >= 50
    assert second.source == "none" and second.answer == ""
    with pytest.raises(HTTPException) as nothing:
        await run(w.acme, lambda db: ep.patch_item(q.id, second.id, ep.ItemPatch(approved=True), w.acme, db, w.user))
    assert nothing.value.status_code == 422, "a blank answer cannot be approved"
    with pytest.raises(HTTPException) as early:
        await run(w.acme, lambda db: ep.complete_questionnaire(q.id, w.acme, db, w.user))
    assert early.value.status_code == 409 and "2 questions are not approved" in early.value.detail
    bulk = await run(w.acme, lambda db: ep.approve_drafts(q.id, w.acme, db, w.user, 50))
    assert bulk.approved == 1 and bulk.blank == 1
    typed = await run(
        w.acme,
        lambda db: ep.patch_item(
            q.id, second.id, ep.ItemPatch(answer="1 Main St, Austin.", approved=True, save_to_library=True), w.acme, db, w.user
        ),
    )
    item = typed.items[1]
    assert item.source == "manual" and item.approved and item.approved_by == "hal@goliveoak.com"
    assert len(await run(w.acme, lambda db: ep.list_library(w.acme, db, w.user))) == 2, "the typed answer was kept for next time"
    edited = await run(
        w.acme, lambda db: ep.patch_item(q.id, first.id, ep.ItemPatch(answer="Yes, AES-256 and TLS 1.3."), w.acme, db, w.user)
    )
    assert not edited.items[0].approved, "a changed answer has to be approved again"
    await run(w.acme, lambda db: ep.patch_item(q.id, first.id, ep.ItemPatch(approved=True), w.acme, db, w.user))
    done = await run(w.acme, lambda db: ep.complete_questionnaire(q.id, w.acme, db, w.user))
    assert done.status == "complete" and done.approved == 2
    with pytest.raises(HTTPException) as locked:
        await run(w.acme, lambda db: ep.patch_item(q.id, first.id, ep.ItemPatch(answer="x"), w.acme, db, w.user))
    assert locked.value.status_code == 409
    exported = await run(w.acme, lambda db: ep.export_questionnaire(q.id, w.acme, db, w.user))
    rows = list(csv.reader(io.StringIO(exported.body.decode())))
    assert [r[3] for r in rows[1:]] == ["approved", "approved"] and exported.headers["content-disposition"].endswith('"questionnaire.csv"')


@needs_pg
@pytest.mark.asyncio
async def test_the_library_keeps_answers_confirms_them_and_archives_without_deleting_and_another_client_sees_none(world):
    w = world
    made = await run(
        w.acme,
        lambda db: ep.add_library(ep.LibraryIn(question="Do you have an incident response plan?", answer="Yes."), w.acme, db, w.user),
    )
    confirmed = await run(w.acme, lambda db: ep.patch_library(made.id, ep.LibraryPatch(confirm=True), w.acme, db, w.user))
    assert confirmed.last_reviewed == datetime.now(UTC).date() and confirmed.category == "General"
    assert await run(w.birch, lambda db: ep.list_library(w.birch, db, SimpleNamespace(tenant_id=w.birch, user_id=None))) == []
    with pytest.raises(HTTPException) as foreign:
        await run(w.birch, lambda db: ep.patch_library(made.id, ep.LibraryPatch(answer="hijack"), w.birch, db, w.user))
    assert foreign.value.status_code == 404
    await run(w.acme, lambda db: ep.archive_library(made.id, w.acme, db, w.user))
    assert await run(w.acme, lambda db: ep.list_library(w.acme, db, w.user)) == []
    async with w.engine.begin() as conn:
        assert (
            await conn.execute(text("select count(*) from questionnaire_answers where id = :i and archived_at is not null"), {"i": made.id})
        ).scalar_one() == 1
    with pytest.raises(HTTPException) as empty:
        await run(w.acme, lambda db: ep.start_questionnaire(ep.QuestionnaireIn(name="Empty one", questions="ok\n\n--"), w.acme, db, w.user))
    assert empty.value.status_code == 422


@needs_pg
@pytest.mark.asyncio
async def test_a_questionnaire_can_be_deleted_with_its_questions_but_the_library_and_other_clients_stay(world):
    w = world
    make = lambda tenant, name: run(  # noqa: E731
        tenant,
        lambda db: ep.start_questionnaire(
            ep.QuestionnaireIn(name=name, questions="1. What is your EDR?\n2. What is your DNS filter?"),
            tenant,
            db,
            SimpleNamespace(tenant_id=tenant, user_id=None, email="hal@goliveoak.com"),
        ),
    )
    mine, theirs = await make(w.acme, "mine"), await make(w.birch, "theirs")
    await run(w.acme, lambda db: ep.delete_questionnaire(mine.id, w.acme, db, w.user))
    assert [x.name for x in (await run(w.acme, lambda db: ep.list_questionnaires(w.acme, db, w.user))).questionnaires] == []
    with pytest.raises(HTTPException) as gone:
        await run(w.acme, lambda db: ep.get_questionnaire(mine.id, w.acme, db, w.user))
    assert gone.value.status_code == 404
    async with w.engine.begin() as conn:
        left = (await conn.execute(text("select count(*) from questionnaire_items where questionnaire_id = :q"), {"q": mine.id})).scalar()
    assert left == 0, "its questions went with it"
    with pytest.raises(HTTPException) as other:
        await run(w.acme, lambda db: ep.delete_questionnaire(theirs.id, w.acme, db, w.user))
    assert other.value.status_code == 404, "another client's questionnaire cannot be deleted from here"
    assert (
        await run(
            w.birch, lambda db: ep.get_questionnaire(theirs.id, w.birch, db, SimpleNamespace(tenant_id=w.birch, user_id=None, email="x"))
        )
    ).name == "theirs"

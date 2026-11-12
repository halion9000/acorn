"""vCIO Risk Scoring against a REAL Postgres (opt in with AISOC_TEST_PG_URL; the database needs migration 172): an assessment is stored under its client, scored on every write, and
never seen or changed by another organisation."""

import os
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import vcio_risk_scoring as ep
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database (with migration 172)"),
]


async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    owner, acme, birch, stranger, theirs = (uuid.uuid4() for _ in range(5))
    tag = uuid.uuid4().hex[:8]
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, name, parent in (
            (owner, "Live Oak", None),
            (acme, "Acme Dental", owner),
            (birch, "Birch Law", owner),
            (stranger, "Other MSP", None),
            (theirs, "Their Client", stranger),
        ):
            await conn.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, :n, :s, :p)"),
                {"t": tid, "n": name, "s": f"vrs-{tag}-{str(tid)[:6]}", "p": parent},
            )
    user = SimpleNamespace(tenant_id=owner, user_id=None, email="hal@goliveoak.com")
    other = SimpleNamespace(tenant_id=stranger, user_id=None, email="x@other.example")
    return engine, user, other, SimpleNamespace(owner=owner, acme=acme, birch=birch, stranger=stranger, theirs=theirs)


async def cleanup(engine, w):
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": [w.owner, w.acme, w.birch, w.stranger, w.theirs]})
    await engine.dispose()


def answers(*items):
    return ep.AnswersIn(items=[ep.AnswerIn(id=i, answer=a, **extra) for i, a, extra in items])


async def test_an_assessment_is_started_for_a_client_answered_and_scored_on_every_write():
    engine, user, _other, w = await world()
    try:
        async with AsyncSession(engine) as db:
            made = await ep.create_assessment(ep.AssessmentIn(client_id=w.acme, review_date=date(2026, 11, 12), assessor=" Hal "), user, db)
            assert (made.client_id, made.client_name, made.assessor, made.platform, made.score, made.rating, made.answered) == (
                w.acme,
                "Acme Dental",
                "Hal",
                "m365",
                None,
                "na",
                0,
            )
            assert made.scorecard["total"] == 330 - 76 and made.updated_by == "hal@goliveoak.com"
            out = await ep.put_answers(
                made.id,
                answers(
                    ("ADM-001", "Yes", {"note": " plan is in IT Glue "}),
                    ("ADM-002", "No", {}),
                    ("TS-001", "Alternative", {"vendor": "Fortinet"}),
                ),
                user,
                db,
            )
            assert out.answers["ADM-001"].note == "plan is in IT Glue" and out.answers["TS-001"].vendor == "Fortinet"
            assert out.answered == 3 and out.rating == "amber", "88%: amber is from 85% to under 95%"
            adm = next(c for c in out.scorecard["categories"] if c["name"] == "Administrative")
            assert adm["score"] == pytest.approx(6 / 9)
            # Administrative 6/9 at weight 8, Tech Stack 100% at weight 15.
            assert out.score == pytest.approx((6 / 9 * 8 + 15) / 23)
            again = await ep.get_assessment(made.id, user, db)
            assert (
                again.score == pytest.approx(out.score) and again.answers.keys() == out.answers.keys()
            ), "what was stored is what is read back"
            cleared = await ep.put_answers(made.id, answers(("ADM-002", None, {})), user, db)
            assert (
                "ADM-002" not in cleared.answers and cleared.answered == 2 and cleared.score == 1.0
            ), "clearing an answer takes it out of the score"
    finally:
        await cleanup(engine, w)


async def test_an_answer_that_is_not_one_or_a_question_that_does_not_exist_is_refused_and_nothing_is_stored():
    engine, user, _other, w = await world()
    try:
        async with AsyncSession(engine) as db:
            made = await ep.create_assessment(ep.AssessmentIn(client_id=w.acme), user, db)
            for bad in (
                answers(("ADM-001", "Maybe", {})),
                answers(("ADM-001", "Preferred", {})),
                answers(("TS-001", "Yes", {})),
                answers(("ADM-001", "Yes", {}), ("NOPE-1", "Yes", {})),
            ):
                with pytest.raises(HTTPException) as refused:
                    await ep.put_answers(made.id, bad, user, db)
                assert refused.value.status_code == 422
            assert (await ep.get_assessment(made.id, user, db)).answers == {}
    finally:
        await cleanup(engine, w)


async def test_the_date_platform_settings_and_a_questions_severity_can_be_changed_and_each_changes_the_score():
    engine, user, _other, w = await world()
    try:
        async with AsyncSession(engine) as db:
            made = await ep.create_assessment(ep.AssessmentIn(client_id=w.acme), user, db)
            await ep.put_answers(made.id, answers(("ADM-001", "No", {}), ("ADM-002", "Yes", {})), user, db)
            lighter = await ep.update_assessment(
                made.id,
                ep.AssessmentPatch(severity={"ADM-001": "Low"}, review_date=date(2026, 10, 1), platform="both", assessor="Dana"),
                user,
                db,
            )
            assert lighter.severity == {"ADM-001": "Low"} and lighter.score == pytest.approx(3 / 4)
            assert (lighter.review_date, lighter.platform, lighter.assessor, lighter.scorecard["total"]) == (
                date(2026, 10, 1),
                "both",
                "Dana",
                330,
            )
            back = await ep.update_assessment(made.id, ep.AssessmentPatch(severity={"ADM-001": None}), user, db)
            assert back.severity == {} and back.score == pytest.approx(3 / 9)
            custom = await ep.update_assessment(made.id, ep.AssessmentPatch(settings={"points": {"High": 3}}), user, db)
            assert custom.score == pytest.approx(3 / 6) and custom.scorecard["settings"]["points"]["High"] == 3
            assert (await ep.update_assessment(made.id, ep.AssessmentPatch(settings={}), user, db)).score == pytest.approx(3 / 9)
            for bad in ({"ADM-001": "Huge"}, {"NOPE-1": "Low"}):
                with pytest.raises(HTTPException) as refused:
                    await ep.update_assessment(made.id, ep.AssessmentPatch(severity=bad), user, db)
                assert refused.value.status_code == 422
    finally:
        await cleanup(engine, w)


async def test_the_list_is_newest_first_per_client_or_for_all_and_a_deleted_assessment_is_gone_and_logged():
    engine, user, _other, w = await world()
    try:
        async with AsyncSession(engine) as db:
            old = await ep.create_assessment(ep.AssessmentIn(client_id=w.acme, review_date=date(2026, 5, 1)), user, db)
            new = await ep.create_assessment(ep.AssessmentIn(client_id=w.acme, review_date=date(2026, 11, 1)), user, db)
            birch = await ep.create_assessment(
                ep.AssessmentIn(client_id=w.birch, review_date=date(2026, 8, 1), platform="google"), user, db
            )
            own = await ep.create_assessment(ep.AssessmentIn(review_date=date(2026, 1, 1)), user, db)
            everything = await ep.list_assessments(user, db, client_id=None)
            assert [i.id for i in everything.items] == [new.id, birch.id, old.id, own.id]
            assert [i.client_name for i in everything.items] == ["Acme Dental", "Birch Law", "Acme Dental", None]
            assert [i.id for i in (await ep.list_assessments(user, db, client_id=w.acme)).items] == [new.id, old.id]
            assert (await ep.delete_assessment(old.id, user, db)).deleted is True
            assert [i.id for i in (await ep.list_assessments(user, db, client_id=w.acme)).items] == [new.id]
            with pytest.raises(HTTPException) as gone:
                await ep.get_assessment(old.id, user, db)
            assert gone.value.status_code == 404
            logged = (
                await db.execute(
                    text("select count(*) from audit_log where tenant_id = :t and action = 'vcio:risk_assessment_deleted'"), {"t": w.owner}
                )
            ).scalar_one()
            assert logged == 1
    finally:
        await cleanup(engine, w)


async def test_another_organisation_never_sees_changes_or_deletes_an_assessment_and_cannot_start_one_for_a_client_that_is_not_its_own():
    engine, user, other, w = await world()
    try:
        async with AsyncSession(engine) as db:
            made = await ep.create_assessment(ep.AssessmentIn(client_id=w.acme), user, db)
            assert (await ep.list_assessments(other, db, client_id=None)).items == []
            assert (await ep.list_assessments(other, db, client_id=w.acme)).items == []
            for attempt in (
                lambda: ep.get_assessment(made.id, other, db),
                lambda: ep.put_answers(made.id, answers(("ADM-001", "Yes", {})), other, db),
                lambda: ep.update_assessment(made.id, ep.AssessmentPatch(assessor="x"), other, db),
                lambda: ep.delete_assessment(made.id, other, db),
                lambda: ep.create_assessment(ep.AssessmentIn(client_id=w.acme), other, db),
            ):
                with pytest.raises(HTTPException) as refused:
                    await attempt()
                assert refused.value.status_code == 404
            assert (await ep.get_assessment(made.id, user, db)).answers == {}
    finally:
        await cleanup(engine, w)


async def test_the_library_gives_the_questions_and_the_defaults():
    out = await ep.get_library(SimpleNamespace(tenant_id=uuid.uuid4()))
    assert len(out.questions) == 330 and out.categories[0] == "Administrative" and out.defaults["cap"] == 0.84
    assert out.yesno_answers == ["Yes", "No", "Partial", "Unknown", "N/A"] and out.vendor_answers == [
        "Preferred",
        "Alternative",
        "None",
        "Unknown",
        "N/A",
    ]

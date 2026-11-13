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


async def test_the_date_platform_and_a_questions_severity_can_be_changed_and_each_changes_the_score():
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


async def test_the_scoring_settings_belong_to_the_organisation_and_saving_them_scores_every_assessment_again():
    engine, user, other, w = await world()
    try:
        async with AsyncSession(engine) as db:
            acme = await ep.create_assessment(ep.AssessmentIn(client_id=w.acme), user, db)
            birch = await ep.create_assessment(ep.AssessmentIn(client_id=w.birch), user, db)
            for made in (acme, birch):
                await ep.put_answers(made.id, answers(("ADM-001", "No", {}), ("ADM-002", "Yes", {})), user, db)
            start = await ep.get_settings(user, db)
            assert start.using_defaults is True and start.settings == start.defaults and start.settings["points"]["High"] == 6
            saved = await ep.put_settings(ep.SettingsIn(settings={"points": {"High": 3, "Low": "x"}, "cap": 0.84, "junk": 1}), user, db)
            assert (saved.using_defaults, saved.rescored, saved.settings["points"]) == (
                False,
                2,
                {"Critical": 10, "High": 3, "Medium": 3, "Low": 1},
            )
            stored = (
                await db.execute(text("select settings -> 'vcio_risk_scoring' from tenants where id = :t"), {"t": w.owner})
            ).scalar_one()
            assert stored == {"points": {"Critical": 10, "High": 3, "Medium": 3, "Low": 1}}, "only what differs from the defaults is kept"
            # ADM-001 High wrong (0 of 3 now), ADM-002 Medium right (3 of 3): 3/6 instead of 3/9, for every client, in the list too.
            assert {i.client_name: i.score for i in (await ep.list_assessments(user, db, client_id=None)).items} == {
                "Acme Dental": pytest.approx(0.5),
                "Birch Law": pytest.approx(0.5),
            }
            opened = await ep.get_assessment(acme.id, user, db)
            assert opened.score == pytest.approx(0.5) and opened.scorecard["settings"]["points"]["High"] == 3
            assert opened.updated_by == "hal@goliveoak.com", "scoring again does not claim someone edited the assessment"
            fresh = await ep.create_assessment(ep.AssessmentIn(client_id=w.acme), user, db)
            assert fresh.scorecard["settings"]["points"]["High"] == 3, "a new assessment uses the organisation's settings"
            # Another organisation has its own: nothing of this one's reaches it.
            assert (await ep.get_settings(other, db)).using_defaults is True
            reset = await ep.put_settings(ep.SettingsIn(settings={}), user, db)
            assert reset.using_defaults is True and reset.rescored == 3
            assert (await ep.get_assessment(acme.id, user, db)).score == pytest.approx(3 / 9)
            logged = (
                await db.execute(
                    text("select count(*) from audit_log where tenant_id = :t and action = 'vcio:risk_settings_changed'"), {"t": w.owner}
                )
            ).scalar_one()
            assert logged == 2
    finally:
        await cleanup(engine, w)


async def test_the_integrations_answers_are_filled_in_scored_and_marked_and_a_hand_answer_or_a_note_is_never_lost(monkeypatch):
    engine, user, _other, w = await world()
    found = {
        "ADM-001": {"answer": "Yes", "evidence": "From a check."},
        "NET-002": {"answer": "No", "evidence": "Clean scan."},
        "TS-001": {"answer": "Alternative", "vendor": "Fortinet", "evidence": "1 firewall."},
    }
    asked = []

    async def fake_review(_db, _user, client_id):
        asked.append(client_id)
        return dict(found)

    monkeypatch.setattr(ep, "review_answers", fake_review)
    try:
        async with AsyncSession(engine) as db:
            made = await ep.create_assessment(ep.AssessmentIn(client_id=w.acme), user, db)
            await ep.put_answers(made.id, answers(("ADM-001", "No", {"note": "they told us"})), user, db)
            out = await ep.autofill_assessment(made.id, user, db)
            assert asked == [w.acme], "the review asked for is the assessed client's"
            assert (out.filled, out.changed, out.kept_by_hand, out.cleared, out.answered_by_integrations) == (2, 0, 1, 0, 3)
            got = out.assessment.answers
            assert (got["ADM-001"].answer, got["ADM-001"].source, got["ADM-001"].note) == ("No", None, "they told us")
            assert (got["NET-002"].answer, got["NET-002"].source, got["NET-002"].evidence) == ("No", "auto", "Clean scan.")
            assert (got["TS-001"].answer, got["TS-001"].vendor, got["TS-001"].source) == ("Alternative", "Fortinet", "auto")
            assert out.assessment.answered == 3 and out.assessment.score is not None
            # A note on an auto answer keeps it auto; changing the answer makes it the person's.
            noted = await ep.put_answers(made.id, answers(("NET-002", "No", {"note": "confirmed with the ISP"})), user, db)
            assert (noted.answers["NET-002"].source, noted.answers["NET-002"].evidence, noted.answers["NET-002"].note) == (
                "auto",
                "Clean scan.",
                "confirmed with the ISP",
            )
            changed = await ep.put_answers(made.id, answers(("TS-001", "Preferred", {"vendor": "Fortinet"})), user, db)
            assert changed.answers["TS-001"].source is None and changed.answers["TS-001"].evidence is None
            del found["NET-002"]
            again = await ep.autofill_assessment(made.id, user, db)
            assert (again.filled, again.kept_by_hand, again.cleared) == (0, 2, 1)
            assert (
                again.assessment.answers["NET-002"].answer is None and again.assessment.answers["NET-002"].note == "confirmed with the ISP"
            )
            assert again.assessment.answers["TS-001"].answer == "Preferred"
    finally:
        await cleanup(engine, w)


async def test_filling_in_from_the_real_client_review_works_for_a_client_no_tool_reports_on_and_fills_nothing_it_cannot_know():
    engine, user, _other, w = await world()
    try:
        async with AsyncSession(engine) as db:
            made = await ep.create_assessment(ep.AssessmentIn(client_id=w.acme), user, db)
            out = await ep.autofill_assessment(made.id, user, db)
            assert out.filled == out.answered_by_integrations and out.kept_by_hand == 0 and out.cleared == 0
            assert all(a.source == "auto" and a.evidence for a in out.assessment.answers.values())
            by_id = ep.rs.questions_by_id()
            assert all(
                a.answer in ep.rs.allowed_answers(by_id[qid]) for qid, a in out.assessment.answers.items()
            ), "every filled answer is one the question accepts"
    finally:
        await cleanup(engine, w)

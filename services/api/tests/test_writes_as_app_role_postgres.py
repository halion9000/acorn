"""The routes that write into a CLIENT's rows and into the organisation's audit log, run the way production runs them: as the restricted ``aisoc_app`` role, which row-level security applies
to. Run as the database owner (which bypasses it) they all passed while the live site answered 500: the audit line for the organisation was written while the session was acting as the
client, and the policy refused it.

Opt in with AISOC_TEST_PG_URL (owner, to build and clean the world) and AISOC_TEST_PG_APP_URL (aisoc_app); the database must be disposable and fully migrated.
"""

import os
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import inventory as inv
from app.api.v1.endpoints import vcio_risk_scoring as vrs
from app.db.rls import set_rls_context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
    ),
]


@pytest.fixture
async def world():
    owner, acme, birch = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, name, parent in ((owner, "Live Oak", None), (acme, "Acme Dental", owner), (birch, "Birch Law", owner)):
            await conn.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, :n, :s, :p)"),
                {"t": tid, "n": name, "s": f"app-{tag}-{str(tid)[:6]}", "p": parent},
            )
    yield SimpleNamespace(
        owner=owner, acme=acme, birch=birch, user=SimpleNamespace(tenant_id=owner, user_id=None, email="hal@goliveoak.com")
    )
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": [owner, acme, birch]})
    await engine.dispose()


async def as_app(w, work):
    """Run ``work(db)`` in a fresh session of the restricted role, scoped to the organisation as a signed-in request is."""
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, w.owner)
            return await work(db)
    finally:
        await engine.dispose()


async def audit_count(w, action):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return (
                await conn.execute(text("select count(*) from audit_log where tenant_id = :t and action = :a"), {"t": w.owner, "a": action})
            ).scalar_one()
    finally:
        await engine.dispose()


async def test_a_clients_risk_assessment_can_be_started_answered_filled_and_deleted_and_the_deletion_is_in_the_organisations_audit_log(
    world,
):
    w = world
    made = await as_app(w, lambda db: vrs.create_assessment(vrs.AssessmentIn(client_id=w.acme, review_date=date(2026, 11, 12)), w.user, db))
    answered = await as_app(
        w, lambda db: vrs.put_answers(made.id, vrs.AnswersIn(items=[vrs.AnswerIn(id="ADM-001", answer="Yes")]), w.user, db)
    )
    assert answered.answered == 1
    patched = await as_app(
        w, lambda db: vrs.update_assessment(made.id, vrs.AssessmentPatch(severity={"ADM-001": "Low"}, assessor="Hal"), w.user, db)
    )
    assert patched.severity == {"ADM-001": "Low"}
    filled = await as_app(w, lambda db: vrs.autofill_assessment(made.id, w.user, db))
    assert filled.kept_by_hand == 0 or filled.assessment.answers["ADM-001"].answer == "Yes"
    assert [i.id for i in (await as_app(w, lambda db: vrs.list_assessments(w.user, db, client_id=None))).items] == [made.id]
    out = await as_app(w, lambda db: vrs.delete_assessment(made.id, w.user, db))
    assert out.deleted is True
    assert (await as_app(w, lambda db: vrs.list_assessments(w.user, db, client_id=w.acme))).items == []
    assert await audit_count(w, "vcio:risk_assessment_deleted") == 1


async def test_the_organisations_own_assessment_can_be_deleted_too(world):
    w = world
    made = await as_app(w, lambda db: vrs.create_assessment(vrs.AssessmentIn(), w.user, db))
    assert (await as_app(w, lambda db: vrs.delete_assessment(made.id, w.user, db))).deleted is True
    assert await audit_count(w, "vcio:risk_assessment_deleted") == 1


async def test_saving_the_scoring_settings_scores_the_clients_assessments_again_and_is_logged(world):
    w = world
    for client in (w.acme, w.birch):
        made = await as_app(w, lambda db, c=client: vrs.create_assessment(vrs.AssessmentIn(client_id=c), w.user, db))
        await as_app(
            w,
            lambda db, m=made: vrs.put_answers(
                m.id, vrs.AnswersIn(items=[vrs.AnswerIn(id="ADM-001", answer="No"), vrs.AnswerIn(id="ADM-002", answer="Yes")]), w.user, db
            ),
        )
    saved = await as_app(w, lambda db: vrs.put_settings(vrs.SettingsIn(settings={"points": {"High": 3}}), w.user, db))
    assert saved.rescored == 2 and saved.using_defaults is False
    scores = [i.score for i in (await as_app(w, lambda db: vrs.list_assessments(w.user, db, client_id=None))).items]
    assert scores == [pytest.approx(0.5), pytest.approx(0.5)]
    assert (await as_app(w, lambda db: vrs.get_settings(w.user, db))).settings["points"]["High"] == 3
    assert await audit_count(w, "vcio:risk_settings_changed") == 1


async def test_a_clients_inventory_item_can_be_deleted_alone_or_with_others_and_each_deletion_is_logged(world):
    w = world
    item = lambda name, **over: inv.ItemIn.model_validate({"name": name, "serial": f"S-{name}", "category": "Computers", **over})  # noqa: E731
    a = await as_app(w, lambda db: inv.create_item(item("A1", client_id=w.acme), w.user, db))
    b = await as_app(w, lambda db: inv.create_item(item("B1", client_id=w.birch), w.user, db))
    c = await as_app(w, lambda db: inv.create_item(item("C1"), w.user, db))
    d = await as_app(w, lambda db: inv.create_item(item("D1", client_id=w.acme), w.user, db))
    assert (await as_app(w, lambda db: inv.delete_item(a.id, w.user, db))).deleted is True
    moved = await as_app(w, lambda db: inv.bulk_move(inv.BulkMoveIn(ids=[b.id, c.id, d.id], to="checked_out", person="Pat"), w.user, db))
    assert moved.moved == 3
    back = await as_app(w, lambda db: inv.bulk_move(inv.BulkMoveIn(ids=[b.id, c.id], to="checked_in"), w.user, db))
    assert back.moved == 2
    out = await as_app(w, lambda db: inv.bulk_delete(inv.BulkDeleteIn(ids=[b.id, c.id, d.id], confirm=True), w.user, db))
    assert (out.deleted, [r.name for r in out.refused]) == (2, ["D1"])
    assert await audit_count(w, "inventory:item_deleted") == 3

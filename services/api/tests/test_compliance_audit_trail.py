"""Changes made in the compliance pages, the roadmap and detected applications leave a line in the hash-chained audit log, with who did it, on a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import access_reviews as ar
from app.api.v1.endpoints import audits as au
from app.api.v1.endpoints import questionnaires as qn
from app.api.v1.endpoints import roadmap as rm
from app.api.v1.endpoints import trust_center as tc
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
    acme = uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'trail', :s)"), {"i": acme, "s": f"trail-{acme.hex[:8]}"})
    yield SimpleNamespace(acme=acme, engine=engine, user=SimpleNamespace(tenant_id=acme, user_id=None, email="hal@goliveoak.com"))
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for table in (
            "roadmap_items",
            "audit_requests",
            "audits",
            "questionnaire_items",
            "questionnaires",
            "access_review_entries",
            "access_reviews",
            "trust_center_settings",
        ):
            await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": acme})
        await conn.execute(text("delete from tenants where id = :t"), {"t": acme})
    await engine.dispose()


async def run(tenant, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tenant)
            return await work(db)
    finally:
        await engine.dispose()


async def audited(w):
    async with w.engine.begin() as conn:
        return [
            (r.action, r.actor_email)
            for r in (
                await conn.execute(
                    text("select action, actor_email, created_at from audit_log where tenant_id = :t order by created_at, id"),
                    {"t": w.acme},
                )
            ).all()
        ]


async def test_each_kind_of_change_leaves_its_own_line_in_the_audit_log(world):
    w = world
    review = await run(
        w.acme, lambda db: ar.start_review(ar.ReviewIn(name="Door badges", system="Door badges", people=["Dana"]), w.acme, db, w.user)
    )
    await run(w.acme, lambda db: ar.decide_all(review.id, ar.BulkIn(decision="keep"), w.acme, db, w.user))
    await run(w.acme, lambda db: ar.complete(review.id, w.acme, db, w.user))
    q = await run(
        w.acme,
        lambda db: qn.start_questionnaire(qn.QuestionnaireIn(name="Acme review", questions="Do you encrypt data?"), w.acme, db, w.user),
    )
    await run(w.acme, lambda db: qn.approve_drafts(q.id, w.acme, db, w.user, 80))
    audit = await run(w.acme, lambda db: au.start_audit(au.AuditIn(name="SOC 2 2026", framework="SOC2"), w.acme, db, w.user))
    await run(w.acme, lambda db: au.patch_audit(audit.id, au.AuditPatch(status="fieldwork"), w.acme, db, w.user))
    await run(w.acme, lambda db: tc.put_trust_center(tc.SettingsIn(enabled=True, headline="Security"), w.acme, db, w.user))
    item = await run(w.acme, lambda db: rm.add_item(rm.ItemIn(title="Something to build"), db, w.user))
    await run(w.acme, lambda db: rm.update_item(item.id, rm.ItemPatch(priority="high"), db, w.user))
    await run(w.acme, lambda db: rm.remove_item(item.id, db, w.user))
    actions = [a for a, _ in await audited(w)]
    for expected in (
        "access_review:started",
        "access_review:decided_all",
        "access_review:completed",
        "questionnaire:started",
        "questionnaire:drafts_approved",
        "audit:started",
        "audit:changed",
        "trust_center:changed",
        "roadmap:added",
        "roadmap:changed",
        "roadmap:removed",
    ):
        assert expected in actions, f"{expected} left no line in the audit log; saw {actions}"
    assert len(actions) == len(set(actions)) == 11, "one line each, none doubled"
    assert {e for _a, e in await audited(w)} == {"hal@goliveoak.com"}, "each line says who did it"

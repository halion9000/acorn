"""The vendor register, against a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import vendor_management as ep
from app.db.rls import set_rls_context
from fastapi import HTTPException
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
    acme, birch = uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, name in ((acme, "Acme Dental"), (birch, "Birch Law")):
            await conn.execute(
                text("insert into tenants (id, name, slug) values (:t, :n, :s)"), {"t": tid, "n": name, "s": f"vm-{tag}-{str(tid)[:6]}"}
            )
    w = SimpleNamespace(
        acme=acme,
        birch=birch,
        user=SimpleNamespace(tenant_id=acme, user_id=None, email="hal@goliveoak.com"),
        request=SimpleNamespace(client=None, headers={}),
    )
    yield w
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
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


async def add(w, tenant=None, **over):
    t = tenant or w.acme
    body = ep.VendorIn(**{"name": "Microsoft", "category": "Cloud and hosting", **over})
    return await run(t, lambda db: ep.create_vendor(body, w.request, t, db, w.user))


async def listing(w, tenant=None, archived=False):
    t = tenant or w.acme
    return await run(t, lambda db: ep.list_vendors(t, db, w.user, archived))


async def test_one_client_never_sees_another_clients_vendors(world):
    w = world
    mine = await add(w, name="Acme only vendor")
    await add(w, tenant=w.birch, name="Birch only vendor")
    assert [v.name for v in (await listing(w)).vendors] == ["Acme only vendor"]
    with pytest.raises(HTTPException) as e:
        await run(w.birch, lambda db: ep.get_vendor(mine.id, w.birch, db, w.user))
    assert e.value.status_code == 404


async def test_the_same_name_twice_is_refused_but_an_archived_one_can_be_added_again(world):
    w = world
    v = await add(w)
    with pytest.raises(HTTPException) as e:
        await add(w, name="microsoft")
    assert e.value.status_code == 409
    await run(w.acme, lambda db: ep.archive_vendor(v.id, w.request, w.acme, db, w.user))
    assert (await add(w)).id != v.id


async def test_changes_are_kept_in_the_history_and_summary_counts_risk_levels(world):
    w = world
    v = await add(w)
    await add(w, name="Zoom", risk_level="low")
    changed = await run(
        w.acme, lambda db: ep.update_vendor(v.id, ep.VendorPatch(risk_level="high", owner="Hal", mfa=True), w.request, w.acme, db, w.user)
    )
    assert changed.risk_level == "high"
    line = [h.detail for h in changed.history if h.action == "changed"][0]
    assert "Risk level unassessed to high" in line and "Owner none to Hal" in line and "Two-factor sign-in none to yes" in line
    s = (await listing(w)).summary
    assert s.total == 2 and s.by_risk["high"] == 1 and s.by_risk["low"] == 1 and s.unassessed == 0


async def test_archive_hides_blocks_edits_and_restore_brings_it_back(world):
    w = world
    v = await add(w)
    a = await run(w.acme, lambda db: ep.archive_vendor(v.id, w.request, w.acme, db, w.user))
    assert a.status == "archived" and a.archived_at is not None
    assert (await listing(w)).vendors == [] and [x.id for x in (await listing(w, archived=True)).vendors] == [v.id]
    with pytest.raises(HTTPException) as e:
        await run(w.acme, lambda db: ep.update_vendor(v.id, ep.VendorPatch(owner="x"), w.request, w.acme, db, w.user))
    assert e.value.status_code == 409
    back = await run(w.acme, lambda db: ep.restore_vendor(v.id, w.request, w.acme, db, w.user))
    assert back.status == "active"


async def test_a_review_runs_to_completion_one_at_a_time_and_a_schedule_restarts_the_clock(world):
    w = world
    v = await add(w, review_interval_months=12)
    assert v.review_state == "due"
    started = await run(w.acme, lambda db: ep.start_review(v.id, ep.ReviewIn(kind="recurring"), w.acme, db, w.user))
    assert started.review_state == "in_progress" and started.reviews[0].status == "in_progress"
    with pytest.raises(HTTPException) as e:
        await run(w.acme, lambda db: ep.start_review(v.id, ep.ReviewIn(), w.acme, db, w.user))
    assert e.value.status_code == 409
    rid = started.reviews[0].id
    done = await run(w.acme, lambda db: ep.complete_review(v.id, rid, ep.ReviewDone(outcome="no_concerns"), w.acme, db, w.user))
    assert done.review_state == "current" and done.last_reviewed == datetime.now(UTC).date()
    with pytest.raises(HTTPException) as e2:
        await run(w.acme, lambda db: ep.complete_review(v.id, rid, ep.ReviewDone(outcome="no_concerns"), w.acme, db, w.user))
    assert e2.value.status_code == 409
    assert (await listing(w)).summary.reviews_overdue == 0


async def test_an_open_review_past_its_due_date_is_overdue_in_the_summary(world):
    w = world
    v = await add(w)
    past = datetime.now(UTC).date() - timedelta(days=10)
    await run(
        w.acme, lambda db: ep.start_review(v.id, ep.ReviewIn(start_date=past - timedelta(days=30), due_date=past), w.acme, db, w.user)
    )
    assert (await listing(w)).summary.reviews_overdue == 1


async def test_documents_are_added_with_a_checked_link_and_removed(world):
    w = world
    v = await add(w)
    doc = ep.DocumentIn(name="SOC 2 2026", doc_type="SOC 2 report", url="https://x.example/soc2.pdf")
    d = await run(w.acme, lambda db: ep.add_document(v.id, doc, w.acme, db, w.user))
    assert d.document_count == 1 and d.documents[0].doc_type == "SOC 2 report"
    with pytest.raises(HTTPException) as e:
        await run(w.acme, lambda db: ep.add_document(v.id, ep.DocumentIn(name="Bad link", url="javascript:alert(1)"), w.acme, db, w.user))
    assert e.value.status_code == 422
    gone = await run(w.acme, lambda db: ep.remove_document(v.id, d.documents[0].id, w.acme, db, w.user))
    assert gone.documents == []

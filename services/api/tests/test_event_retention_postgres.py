"""Retention of the stored events: set per client, previewed, and purged only for the number confirmed (real Postgres: AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL)."""

import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import event_retention as ep
from app.db.rls import set_rls_context
from app.services import event_store as es
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def test_only_the_five_choices_or_infinite_are_accepted_and_a_bad_client_id_is_refused():
    c = str(uuid.uuid4())
    assert ep.clean(ep.RetentionIn(default=7, clients={c: "infinite"})) == {"default": 7, "clients": {c: "infinite"}}
    assert ep.clean(ep.RetentionIn()) == {"default": "infinite", "clients": {}}
    for bad in (ep.RetentionIn(default=4), ep.RetentionIn(default="forever"), ep.RetentionIn(clients={c: 2}), ep.RetentionIn(clients={"not-an-id": 3})):
        with pytest.raises(HTTPException) as e:
            ep.clean(bad)
        assert e.value.status_code == 422


PG_URL, APP_URL = os.environ.get("AISOC_TEST_PG_URL"), os.environ.get("AISOC_TEST_PG_APP_URL")
needs_pg = pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    a, client = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'rt', :s)"), {"i": a, "s": f"rt-{a.hex[:8]}"})
    yield SimpleNamespace(a=a, client=client, user=SimpleNamespace(tenant_id=a, user_id=None))
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("delete from audit_log where tenant_id = :t"), {"t": a})
        await conn.execute(text("delete from tenants where id = :t"), {"t": a})
    await engine.dispose()


async def with_db(tid, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            out = await work(db)
            await db.commit()
            return out
    finally:
        await engine.dispose()


def ev(i, client, year):
    return {"source": "halopsa", "kind": "ticket.created", "event_time": f"{year}-06-01T10:00:00Z", "external_id": f"t{i}", "payload": {"summary": "x"}, "client_id": str(client)}


@needs_pg
@pytest.mark.asyncio
async def test_setting_a_retention_deletes_nothing_the_preview_counts_and_the_purge_needs_the_same_number(world, monkeypatch):
    await with_db(world.a, lambda db: es.append_events(db, world.a, [ev(1, world.client, 2015), ev(2, world.client, 2016), ev(3, world.client, 2026)], NOW))
    default = await with_db(world.a, lambda db: ep.get_retention(world.user, db))
    assert default == {"default": "infinite", "clients": {}, "choices": [1, 3, 5, 7, 10]}
    saved = await with_db(world.a, lambda db: ep.put_retention(ep.RetentionIn(clients={str(world.client): 5}), None, world.user, db))
    assert saved["clients"] == {str(world.client): 5}
    count = lambda: with_db(world.a, lambda db: db.execute(text("select count(*) from stored_events")))  # noqa: E731
    assert (await count()).scalar_one() == 3, "setting a retention deleted nothing"
    p = await with_db(world.a, lambda db: ep.preview(world.user, db))
    assert p == {"by_client": {str(world.client): 2}, "total": 2}

    with pytest.raises(HTTPException) as e:
        await with_db(world.a, lambda db: ep.purge(ep.PurgeIn(confirm=1), None, world.user, db))
    assert e.value.status_code == 409 and (await count()).scalar_one() == 3, "a number that does not match deletes nothing"
    done = await with_db(world.a, lambda db: ep.purge(ep.PurgeIn(confirm=2), None, world.user, db))
    assert done == {"deleted": 2} and (await count()).scalar_one() == 1
    audited = (await with_db(world.a, lambda db: db.execute(text("select action from audit_log where tenant_id = :t and action like 'events:%' order by created_at"), {"t": world.a}))).scalars().all()
    assert audited == ["events:retention_changed", "events:purged"]


@needs_pg
@pytest.mark.asyncio
async def test_with_every_client_infinite_the_preview_is_empty_and_a_purge_of_zero_deletes_nothing(world):
    await with_db(world.a, lambda db: es.append_events(db, world.a, [ev(1, world.client, 2001)], NOW))
    assert (await with_db(world.a, lambda db: ep.preview(world.user, db))) == {"by_client": {}, "total": 0}
    assert (await with_db(world.a, lambda db: ep.purge(ep.PurgeIn(confirm=0), None, world.user, db))) == {"deleted": 0}
    left = (await with_db(world.a, lambda db: db.execute(text("select count(*) from stored_events")))).scalar_one()
    assert left == 1

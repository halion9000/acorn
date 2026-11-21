"""The event store against a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database), plus its pure rules.

Events are appended once, never changed, isolated by organization, and removed only by the retention purge (or when the whole organization is deleted).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.db.rls import set_rls_context
from app.services import event_store as es
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def ev(external_id="e1", **over):
    base = {"source": "halopsa", "kind": "ticket", "event_time": "2026-11-01T10:00:00Z", "external_id": external_id, "payload": {"id": 1}}
    return {**base, **over}


def test_an_event_needs_a_source_kind_id_time_and_a_small_object_payload():
    ok = es.parse_event(ev(client_id=str(uuid.uuid4())))
    assert ok is not None and ok.source == "halopsa" and ok.event_time == datetime(2026, 11, 1, 10, tzinfo=UTC) and ok.client_id is not None
    assert es.parse_event(ev(source="")) is None and es.parse_event(ev(kind=" ")) is None and es.parse_event(ev(external_id="")) is None
    assert es.parse_event(ev(payload=[1])) is None and es.parse_event(ev(event_time="yesterday")) is None
    assert es.parse_event(ev(client_id="nope")) is None
    assert es.parse_event(ev(payload={"x": "y" * 70000})) is None, "too large"
    assert es.parse_event("text") is None
    naive = es.parse_event(ev(event_time="2026-11-01T10:00:00"))
    assert naive is not None and naive.event_time.tzinfo is not None, "a time with no zone is taken as UTC"


def test_retention_is_infinite_unless_a_client_or_the_default_names_one_of_the_choices():
    s = {"retention": {"default": 7, "clients": {"c1": 3, "c2": "infinite", "c3": 4}}}
    assert es.retention_years(s, "c1") == 3
    assert es.retention_years(s, "c2") is None, "a client set to infinite"
    assert es.retention_years(s, "c3") is None, "4 is not a choice, so nothing is ever deleted on a guess"
    assert es.retention_years(s, "other") == 7 and es.retention_years(s, None) == 7
    assert es.retention_years({}, "c1") is None and es.retention_years(None, None) is None
    assert es.cutoff(None, NOW) is None
    assert es.cutoff(1, NOW) == NOW - timedelta(days=365)
    assert es.cutoff(10, NOW) == NOW - timedelta(days=3652)


PG_URL, APP_URL = os.environ.get("AISOC_TEST_PG_URL"), os.environ.get("AISOC_TEST_PG_APP_URL")
needs_pg = pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    a, b = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        for tid in (a, b):
            await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'es', :s)"), {"i": tid, "s": f"es-{tid.hex[:8]}"})
    yield SimpleNamespace(a=a, b=b)
    async with engine.begin() as conn:
        for tid in (a, b):
            await conn.execute(text("delete from tenants where id = :t"), {"t": tid})
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


@needs_pg
@pytest.mark.asyncio
async def test_an_event_is_stored_once_and_a_second_copy_is_a_duplicate(world):
    first = await with_db(world.a, lambda db: es.append_events(db, world.a, [ev("e1"), ev("e2"), ev("e1"), {"source": ""}], NOW))
    assert first == {"stored": 2, "duplicates": 1, "refused": 1}
    again = await with_db(world.a, lambda db: es.append_events(db, world.a, [ev("e1"), ev("e3")], NOW))
    assert again == {"stored": 1, "duplicates": 1, "refused": 0}
    count = await with_db(world.a, lambda db: db.execute(text("select count(*) from stored_events where tenant_id = :t"), {"t": world.a}))
    assert count.scalar_one() == 3


@needs_pg
@pytest.mark.asyncio
async def test_each_organization_sees_only_its_own_events_and_the_same_id_may_exist_in_both(world):
    await with_db(world.a, lambda db: es.append_events(db, world.a, [ev("same")], NOW))
    await with_db(world.b, lambda db: es.append_events(db, world.b, [ev("same"), ev("only-b")], NOW))
    seen_a = (await with_db(world.a, lambda db: db.execute(text("select external_id from stored_events order by 1")))).scalars().all()
    seen_b = (await with_db(world.b, lambda db: db.execute(text("select external_id from stored_events order by 1")))).scalars().all()
    assert seen_a == ["same"] and seen_b == ["only-b", "same"]


@needs_pg
@pytest.mark.asyncio
async def test_a_stored_event_cannot_be_updated_or_deleted_even_by_its_own_organization(world):
    await with_db(world.a, lambda db: es.append_events(db, world.a, [ev("keep")], NOW))
    for sql in ("update stored_events set payload = '{}'::jsonb", "delete from stored_events"):
        with pytest.raises(DBAPIError, match="never changed"):
            await with_db(world.a, lambda db, q=sql: db.execute(text(q)))
    kept = (await with_db(world.a, lambda db: db.execute(text("select payload from stored_events")))).scalars().all()
    assert kept == [{"id": 1}], "the event is still there, unchanged"


@needs_pg
@pytest.mark.asyncio
async def test_the_purge_removes_only_what_a_clients_retention_has_passed_and_nothing_when_it_is_infinite(world):
    old_client, young_client, forever = (uuid.uuid4() for _ in range(3))
    rows = [
        ev("o1", client_id=str(old_client), event_time="2020-01-01T00:00:00Z"),
        ev("o2", client_id=str(old_client), event_time="2026-10-01T00:00:00Z"),
        ev("y1", client_id=str(young_client), event_time="2020-01-01T00:00:00Z"),
        ev("f1", client_id=str(forever), event_time="2001-01-01T00:00:00Z"),
        ev("n1", event_time="2001-01-01T00:00:00Z"),
    ]
    await with_db(world.a, lambda db: es.append_events(db, world.a, rows, NOW))
    settings = {"retention": {"default": None, "clients": {str(old_client): 3, str(young_client): 10, str(forever): "infinite"}}}
    deleted = await with_db(world.a, lambda db: es.purge_expired(db, world.a, settings, NOW))
    left = (await with_db(world.a, lambda db: db.execute(text("select external_id from stored_events order by 1")))).scalars().all()
    assert deleted == 1 and left == ["f1", "n1", "o2", "y1"], "only the 2020 event of the 3-year client was past its retention"
    nothing = await with_db(world.a, lambda db: es.purge_expired(db, world.a, {}, NOW))
    assert nothing == 0, "with no retention chosen (infinite) nothing is ever deleted"


@needs_pg
@pytest.mark.asyncio
async def test_deleting_an_organization_takes_its_events_with_it(world):
    await with_db(world.b, lambda db: es.append_events(db, world.b, [ev("gone")], NOW))
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("delete from tenants where id = :t"), {"t": world.b})
        left = (await conn.execute(text("select count(*) from stored_events where tenant_id = :t"), {"t": world.b})).scalar_one()
    await engine.dispose()
    assert left == 0


@needs_pg
@pytest.mark.asyncio
async def test_the_core_feed_route_resolves_a_client_reference_to_the_mapped_client_and_keeps_each_event_once(world):
    from app.api.v1.endpoints import inbox_core_feed as feed

    mapped = uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'child', :s)"), {"i": mapped, "s": f"es-{mapped.hex[:8]}"})
        await conn.execute(
            text(
                "insert into client_aliases (id, tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id) values (gen_random_uuid(), :o, 'halopsa', '57', 'Acme', 'acme', :c)"
            ),
            {"o": world.a, "c": mapped},
        )

    async def verified(db, token):
        return world.a

    feed_verify, feed._verify_core_feed_token = feed._verify_core_feed_token, verified
    try:
        body = feed.EventsIn(events=[ev("t1:created", client_ref={"vendor": "halopsa", "id": "57"}), ev("t2:created", client_ref={"vendor": "halopsa", "id": "999"}), ev("t1:created", client_ref={"vendor": "halopsa", "id": "57"})])
        out = await with_db(world.a, lambda db: feed.report_core_feed_events("tok", body, db))
        assert (out.stored, out.duplicates, out.refused) == (2, 1, 0)
        rows = (await with_db(world.a, lambda db: db.execute(text("select external_id, client_id from stored_events order by 1")))).all()
        assert rows == [("t1:created", mapped), ("t2:created", None)], "a mapped client is resolved; an unmapped one leaves the event with no client"
    finally:
        feed._verify_core_feed_token = feed_verify
        async with engine.begin() as conn:
            await conn.execute(text("delete from client_aliases where tenant_id = :o"), {"o": world.a})
            await conn.execute(text("delete from tenants where id = :t"), {"t": mapped})
        await engine.dispose()

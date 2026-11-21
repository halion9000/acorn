"""Searching the event store: by client, source, kind, time and text, paged newest first, and opening one raw event (real Postgres: AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL)."""

import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import event_search as ep
from app.db.rls import set_rls_context
from app.services import event_store as es
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def test_a_search_text_is_matched_literally_and_a_preview_prefers_what_the_event_says():
    assert ep.like_pattern("50%_off!") == "%50!%!_off!!%"
    assert ep.preview_of({"summary": " Printer is down ", "x": 1}) == "Printer is down"
    assert ep.preview_of({"x": 1}) == '{"x": 1}'
    assert len(ep.preview_of({"summary": "y" * 1000})) == ep.PREVIEW


def test_the_query_has_a_condition_for_each_filter_given_and_none_for_the_rest():
    c = str(uuid.uuid4())
    where, values = ep.build_query(c, "halopsa", "ticket.created", datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC), "printer", 50)
    for part in ("client_id = :client", "source = :source", "kind = :kind", "event_time >= :since", "event_time < :until", "ILIKE :q", "id < :before"):
        assert part in where
    assert values["client"] == uuid.UUID(c) and values["q"] == "%printer%" and values["before"] == 50
    assert ep.build_query(None, None, None, None, None, "  ", None) == ("true", {})
    assert "client_id IS NULL" in ep.build_query("none", None, None, None, None, "", None)[0]


PG_URL, APP_URL = os.environ.get("AISOC_TEST_PG_URL"), os.environ.get("AISOC_TEST_PG_APP_URL")
needs_pg = pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    a, b, client = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        for tid in (a, b):
            await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'se', :s)"), {"i": tid, "s": f"se-{tid.hex[:8]}"})
    yield SimpleNamespace(a=a, b=b, client=client, user=SimpleNamespace(tenant_id=a), other=SimpleNamespace(tenant_id=b))
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


def ev(i, **over):
    return {"source": "halopsa", "kind": "ticket.created", "event_time": f"2026-11-{i:02d}T10:00:00Z", "external_id": f"t{i}", "payload": {"summary": f"Ticket number {i}", "tag": "50%_off" if i == 3 else "plain"}, **over}


@pytest.fixture
async def stored(world):
    rows = [ev(i, client_id=str(world.client) if i % 2 else None) for i in range(1, 8)] + [ev(9, source="dialpad", kind="call.missed", external_id="c9", client_id=str(world.client))]
    await with_db(world.a, lambda db: es.append_events(db, world.a, rows, NOW))
    await with_db(world.b, lambda db: es.append_events(db, world.b, [ev(1, external_id="theirs")], NOW))
    return world


async def search(world, **kw):
    args = {"client_id": None, "source": None, "kind": None, "since": None, "until": None, "q": "", "before": None, **kw}
    return await with_db(world.a, lambda db: ep.search_events(world.user, db, **args))


@needs_pg
@pytest.mark.asyncio
async def test_a_search_finds_events_by_client_source_kind_time_and_text_newest_first_and_only_the_callers(stored):
    everything = await search(stored)
    assert [r.external_id for r in everything.rows] == ["c9", "t7", "t6", "t5", "t4", "t3", "t2", "t1"], "newest first, and not the other organization's"
    assert everything.sources == ["dialpad", "halopsa"]
    assert [r.external_id for r in (await search(stored, client_id=str(stored.client))).rows] == ["c9", "t7", "t5", "t3", "t1"]
    assert [r.external_id for r in (await search(stored, client_id="none")).rows] == ["t6", "t4", "t2"]
    assert [r.external_id for r in (await search(stored, source="dialpad")).rows] == ["c9"]
    assert [r.external_id for r in (await search(stored, kind="call.missed")).rows] == ["c9"]
    assert [r.external_id for r in (await search(stored, since=datetime(2026, 11, 3, tzinfo=UTC), until=datetime(2026, 11, 6, tzinfo=UTC))).rows] == ["t5", "t4", "t3"]
    assert [r.external_id for r in (await search(stored, q="ticket number 4")).rows] == ["t4"], "the text is found anywhere in the event, whatever its case"
    assert [r.external_id for r in (await search(stored, q="50%_off")).rows] == ["t3"], "% and _ in the text mean themselves"
    assert (await search(stored, q="t5")).rows[0].external_id == "t5", "the external id is searched too"


@needs_pg
@pytest.mark.asyncio
async def test_results_come_a_page_at_a_time_with_the_id_of_the_next(stored, monkeypatch):
    monkeypatch.setattr(ep, "PAGE", 3)
    first = await search(stored)
    assert [r.external_id for r in first.rows] == ["c9", "t7", "t6"] and first.next_before is not None
    second = await search(stored, before=first.next_before)
    assert [r.external_id for r in second.rows] == ["t5", "t4", "t3"] and second.next_before is not None
    last = await search(stored, before=second.next_before)
    assert [r.external_id for r in last.rows] == ["t2", "t1"] and last.next_before is None


@needs_pg
@pytest.mark.asyncio
async def test_one_event_opens_whole_and_another_organizations_event_is_not_found(stored):
    row = (await search(stored, q="t4")).rows[0]
    full = await with_db(stored.a, lambda db: ep.get_event(row.id, stored.user, db))
    assert full.payload == {"summary": "Ticket number 4", "tag": "plain"} and full.external_id == "t4"
    with pytest.raises(HTTPException) as e:
        await with_db(stored.b, lambda db: ep.get_event(row.id, stored.other, db))
    assert e.value.status_code == 404

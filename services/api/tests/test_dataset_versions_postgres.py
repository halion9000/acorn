"""Versions of the datasets CORE sends: kept when they changed and the last one is old enough, never changed afterwards (real Postgres: AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.db.rls import set_rls_context
from app.services import dataset_versions as dv
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def test_the_digest_is_the_same_whatever_the_order_of_the_keys_and_changes_with_the_content():
    assert dv.digest({"a": 1, "b": [1, 2]}) == dv.digest({"b": [1, 2], "a": 1})
    assert dv.digest({"a": 1}) != dv.digest({"a": 2})
    assert len(dv.digest({})) == 64


PG_URL, APP_URL = os.environ.get("AISOC_TEST_PG_URL"), os.environ.get("AISOC_TEST_PG_APP_URL")
needs_pg = pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    a = uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'dv', :s)"), {"i": a, "s": f"dv-{a.hex[:8]}"})
    yield SimpleNamespace(a=a)
    async with engine.begin() as conn:
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


@needs_pg
@pytest.mark.asyncio
async def test_a_changed_dataset_is_kept_as_a_version_only_when_the_last_version_is_old_enough_and_never_twice(world):
    keep = lambda payload, at: with_db(world.a, lambda db: dv.keep_version(db, world.a, "staff-weekly", payload, at))  # noqa: E731
    assert await keep({"rows": [1]}, T0) is True, "the first state is kept"
    assert await keep({"rows": [1, 2]}, T0 + timedelta(hours=1)) is False, "changed, but the last version is under six hours old"
    assert await keep({"rows": [1, 2]}, T0 + timedelta(hours=7)) is True, "changed and old enough"
    assert await keep({"rows": [1, 2]}, T0 + timedelta(hours=14)) is False, "the same content is never stored twice"
    assert await keep({"rows": [1]}, T0 + timedelta(hours=21)) is False, "an earlier state coming back is already held"
    other = await with_db(world.a, lambda db: dv.keep_version(db, world.a, "ticket-detail", {"rows": [1]}, T0))
    assert other is True, "each dataset has its own versions"
    kept = (await with_db(world.a, lambda db: db.execute(text("select key, payload from dataset_versions order by id")))).all()
    assert [(k, p) for k, p in kept] == [("staff-weekly", {"rows": [1]}), ("staff-weekly", {"rows": [1, 2]}), ("ticket-detail", {"rows": [1]})]


@needs_pg
@pytest.mark.asyncio
async def test_a_version_cannot_be_changed_or_deleted(world):
    await with_db(world.a, lambda db: dv.keep_version(db, world.a, "staff-weekly", {"rows": [1]}, T0))
    for sql in ("update dataset_versions set payload = '{}'::jsonb", "delete from dataset_versions"):
        with pytest.raises(DBAPIError, match="never changed"):
            await with_db(world.a, lambda db, q=sql: db.execute(text(q)))


@needs_pg
@pytest.mark.asyncio
async def test_sending_a_dataset_through_the_feed_keeps_a_version(world):
    from app.api.v1.endpoints import inbox_core_feed as feed

    async def verified(db, token):
        return world.a

    original, feed._verify_core_feed_token = feed._verify_core_feed_token, verified
    try:
        body = feed.MetricDatasetIn(data={"weeks": ["2026-11-16"], "rows": [{"week": "2026-11-16", "agent_id": "40", "engineer": "Dan"}]})
        await with_db(world.a, lambda db: feed.report_core_feed_metric_staff_weekly("tok", body, db))
        kept = (await with_db(world.a, lambda db: db.execute(text("select key, payload->'weeks' from dataset_versions")))).all()
        assert kept == [("staff-weekly", ["2026-11-16"])]
    finally:
        feed._verify_core_feed_token = original

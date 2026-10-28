"""Pipeline Health's alert stages against a REAL Postgres, as the application's own (row-level-security) role.

An MSSP's alerts live in its client organizations. The stages used to read the parent alone and said "no alerts in the last hour" with 65 alerts in the hour. Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated
database) and AISOC_TEST_PG_APP_URL (the application role on that database).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.api.v1.endpoints.health import _alert_stage, _correlate_stage, _fuse_stage, _normalize_stage
from app.db.rls_scope import cross_tenant_reads
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    parent, client = uuid.uuid4(), uuid.uuid4()
    tag = parent.hex[:8]
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    app = create_async_engine(APP_URL, poolclass=NullPool)
    now = datetime.now(UTC)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :n, 'parent')"), {"i": parent, "n": f"ph-p-{tag}"})
            await conn.execute(
                text("insert into tenants (id, name, slug, mssp_role, parent_tenant_id) values (:i, :n, :n, 'child', :p)"),
                {"i": client, "n": f"ph-c-{tag}", "p": parent},
            )
            for i in range(3):  # three alerts in the CLIENT, none in the parent: one event, two events, one event
                events = '["a","b"]' if i == 1 else '["a"]'
                await conn.execute(
                    text(
                        "insert into alerts (tenant_id, title, severity, status, event_time, first_seen, last_seen, source_event_ids, created_at) "
                        "values (:t, :ti, 'low', 'new', :e, :f, :l, cast(:s as jsonb), :c)"
                    ),
                    {"t": client, "ti": f"a{i}", "e": now - timedelta(minutes=5, seconds=5), "f": now - timedelta(minutes=5, seconds=4), "l": now - timedelta(minutes=5, seconds=1), "s": events, "c": now - timedelta(minutes=5)},
                )
        yield app, parent, client, now
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from alerts where tenant_id in (:a, :b)"), {"a": parent, "b": client})
            await conn.execute(text("delete from tenants where id in (:a, :b)"), {"a": client, "b": parent})
        await owner.dispose()
        await app.dispose()


async def stages(app, scope, now):
    window = {"window_start": now - timedelta(hours=1), "window_end": now + timedelta(minutes=1)}
    latency = {"warn_seconds": 600, "down_seconds": 1800}
    async with AsyncSession(app) as db, cross_tenant_reads(db):
        return {
            "normalize": await _normalize_stage(db, scope, **latency, **window),
            "fuse": await _fuse_stage(db, scope, **latency, **window),
            "correlate": await _correlate_stage(db, scope, **window),
            "alert": await _alert_stage(db, scope, **latency, **window),
        }


@pytest.mark.asyncio
async def test_the_parent_alone_sees_nothing_and_with_its_clients_it_sees_their_alerts(world):
    app, parent, client, now = world

    alone = await stages(app, [parent], now)
    assert {s.status for s in alone.values()} == {"unknown"}, "the old reading: the parent holds no alerts"

    together = await stages(app, [parent, client], now)
    assert together["normalize"].status == "green" and together["normalize"].p95_latency_ms > 0
    assert together["fuse"].status == "green"
    assert together["correlate"].status == "green", "one alert carries two source events"
    assert together["correlate"].backlog == 2, "the other two carry one event each"
    assert together["alert"].backlog == 3, "three alerts nobody has opened yet"

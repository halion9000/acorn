"""Stale alerts on a REAL Postgres: the sweep moves only the right alerts aside, keeps the old status and the old touch time, and restore and close act only on stale ones.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.services.alert_stale import close_stale, restore_stale, sweep_stale
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]

NOW = datetime.now(UTC)


@pytest.fixture
async def db():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    tenant, case = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine) as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await s.execute(
            text("insert into tenants (id, name, slug) values (:t, 'stale-test', :s)"), {"t": tenant, "s": f"stale-{tenant.hex[:10]}"}
        )
        ids = {}
        for key, status, severity, days, with_case in (
            ("old_low_new", "new", "low", 40, False),
            ("old_low_triaging", "triaging", "medium", 35, False),
            ("old_high", "new", "high", 90, False),
            ("old_critical", "new", "critical", 90, False),
            ("old_in_case", "new", "low", 90, True),
            ("old_claimed", "in_progress", "low", 90, False),
            ("old_resolved", "resolved", "low", 90, False),
            ("recent", "new", "low", 3, False),
        ):
            ids[key] = uuid.uuid4()
            await s.execute(
                text(
                    "insert into alerts (id, tenant_id, title, severity, status, priority, case_id, created_at, updated_at) "
                    "values (:i, :t, :title, :sev, :st, 50, :c, :at, :at)"
                ),
                {
                    "i": ids[key],
                    "t": tenant,
                    "title": key,
                    "sev": severity,
                    "st": status,
                    "c": case if with_case else None,
                    "at": NOW - timedelta(days=days),
                },
            )
        await s.commit()
        s.info["tenant"], s.info["ids"] = tenant, ids
        yield s
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await s.execute(text("delete from alerts where tenant_id = :t"), {"t": tenant})
        await s.execute(text("delete from tenants where id = :t"), {"t": tenant})
        await s.commit()
    await engine.dispose()


async def status_of(db):
    await db.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
    rows = (
        await db.execute(
            text("select title, status, status_before_stale, updated_at from alerts where tenant_id = :t"), {"t": db.info["tenant"]}
        )
    ).all()
    return {r[0]: r for r in rows}


async def test_the_sweep_sets_aside_only_quiet_low_alerts_in_no_case_nobody_started_on(db):
    await db.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
    before = await status_of(db)
    moved = await sweep_stale(db, 30, ("critical", "high"), NOW)
    await db.commit()
    assert moved >= 2
    after = await status_of(db)
    assert {k for k, v in after.items() if v[1] == "stale"} == {"old_low_new", "old_low_triaging"}
    assert after["old_low_new"][2] == "new" and after["old_low_triaging"][2] == "triaging", "the old status is kept"
    assert after["old_low_new"][3] == before["old_low_new"][3], "the last-touched time is kept: quiet since then, not since the sweep"
    for untouched in ("old_high", "old_critical", "old_in_case", "old_claimed", "old_resolved", "recent"):
        assert after[untouched][1] == before[untouched][1], untouched


async def test_restore_puts_each_back_as_it_was_touched_now_and_close_finishes_only_stale_ones(db):
    await sweep_stale(db, 30, ("critical", "high"), NOW)
    await db.commit()
    tenant = db.info["tenant"]
    restored = await restore_stale(db, [tenant], [db.info["ids"]["old_low_triaging"]], NOW)
    await db.commit()
    after = await status_of(db)
    assert restored == 1 and after["old_low_triaging"][1] == "triaging" and after["old_low_triaging"][2] is None
    assert after["old_low_triaging"][3] >= NOW - timedelta(seconds=5), "touched now, so it is not set aside again at once"
    closed = await close_stale(db, [tenant], None, NOW)
    await db.commit()
    final = await status_of(db)
    assert closed >= 1 and final["old_low_new"][1] == "closed"
    assert final["old_high"][1] == "new" and final["recent"][1] == "new", "close touches stale alerts only"

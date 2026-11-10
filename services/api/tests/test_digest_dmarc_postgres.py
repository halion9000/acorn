"""The digest reads DMARC reports from a REAL Postgres: only this client's matched reports whose period ended inside the window.

Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.services.executive_digest import _fetch_dmarc
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")]


async def test_only_this_clients_matched_reports_inside_the_window_are_read():
    tag = uuid.uuid4().hex[:8]
    mine, other = uuid.uuid4(), uuid.uuid4()
    end = datetime(2026, 11, 9, tzinfo=UTC)
    start = end - timedelta(days=7)
    engine = create_async_engine(PG_URL, poolclass=NullPool)

    async def add(conn, tenant, domain, ended, matched=True, total=10, passed=9):
        await conn.execute(
            text(
                "insert into dmarc_reports (id, tenant_id, matched, domain, reporter, report_id, begin_at, end_at, policy, total, passed, failed, rows, received_at) "
                "values (:i, :t, :m, :d, 'r', :r, :b, :e, 'none', :tot, :p, :f, '[]'::jsonb, now())"
            ),
            {"i": uuid.uuid4(), "t": tenant, "m": matched, "d": domain, "r": f"{tag}-{uuid.uuid4().hex[:6]}", "b": ended - timedelta(days=1), "e": ended, "tot": total, "p": passed, "f": total - passed},
        )

    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for t in (mine, other):
                await conn.execute(text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"), {"i": t, "n": f"d-{tag}-{str(t)[:4]}", "s": f"d-{tag}-{str(t)[:4]}"})
            await add(conn, mine, "in-window.example", end - timedelta(days=2))
            await add(conn, mine, "too-old.example", start - timedelta(days=1))
            await add(conn, mine, "too-new.example", end + timedelta(hours=1))
            await add(conn, mine, "unmatched.example", end - timedelta(days=2), matched=False)
            await add(conn, other, "someone-elses.example", end - timedelta(days=2))
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await db.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            rows = await _fetch_dmarc(db, mine, start, end)
        assert [(r.domain, r.total, r.passed, r.failed) for r in rows] == [("in-window.example", 10, 9, 1)]
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from tenants where id in (:a, :b)"), {"a": mine, "b": other})
        await engine.dispose()

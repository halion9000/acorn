"""MTTR over real rows: the median of what a person resolved, a stale sweep left out, an unresolved alert left out, other tenants left out (services/mttr.py)."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.services import mttr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")]


async def test_window_takes_the_median_of_responses_and_leaves_out_stale_unresolved_and_other_tenants():
    tag = uuid.uuid4().hex[:8]
    mine, other = uuid.uuid4(), uuid.uuid4()
    t0 = datetime.now(UTC) - timedelta(days=2)
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for tid in (mine, other):
                await conn.execute(text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"), {"i": tid, "n": f"m-{tag}-{str(tid)[:4]}", "s": f"m-{tag}-{str(tid)[:4]}"})

            async def alert(tenant, hours, stale=False, resolved=True, severity="high"):
                await conn.execute(
                    text(
                        "insert into alerts (id, tenant_id, title, severity, status, created_at, updated_at, resolved_at, stale_at) "
                        "values (:i, :t, 'x', :sev, 'resolved', :c, :c, :r, :s)"
                    ),
                    {"i": uuid.uuid4(), "t": tenant, "sev": severity, "c": t0, "r": t0 + timedelta(hours=hours) if resolved else None, "s": t0 if stale else None},
                )

            for h in (1, 2, 3, 500):
                await alert(mine, h)
            await alert(mine, 700, stale=True)
            await alert(mine, 0, resolved=False)
            await alert(mine, 9, severity="low")
            await alert(other, 50)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await db.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            got = await mttr.window(db, [mine], t0 - timedelta(hours=1), severity="high")
            assert (got.median_hours, got.n) == (2.5, 4), "median of 1, 2, 3 and 500 hours; the stale, the unresolved, the low and the other tenant's are not counted"
            assert got.p90_hours > 100
            both = await mttr.window(db, [mine], t0 - timedelta(hours=1))
            assert both.n == 5
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from alerts where tenant_id = any(cast(:t as uuid[]))"), {"t": [str(mine), str(other)]})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [str(mine), str(other)]})
        await engine.dispose()

"""Which tenants already have the weekly digest, read against a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).

The worker's catch-up asks this across every client at once. report_artefacts is row-level secured, so a plain read as the restricted role sees nothing; the answer must still be every client that has the digest.
"""

import os
import uuid
from datetime import UTC, datetime

import pytest
from app.workers import weekly_digest_task as wdt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
    ),
]
START = datetime(2026, 11, 2, tzinfo=UTC)


async def test_every_tenant_with_the_digest_for_the_week_is_found_and_no_other(monkeypatch):
    has, lacks, other_week = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    # Fail closed, as production is: a read with no client chosen sees nothing unless it asks for the cross-client reads.
    app = create_async_engine(APP_URL, poolclass=NullPool, connect_args={"server_settings": {"app.rls_fail_closed": "on"}})
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for tid in (has, lacks, other_week):
                await conn.execute(
                    text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :n, 'parent')"),
                    {"i": tid, "n": f"wd-{tid.hex[:8]}"},
                )
            for tid, start in ((has, START), (other_week, datetime(2026, 10, 26, tzinfo=UTC))):
                await conn.execute(
                    text(
                        "insert into report_artefacts (tenant_id, report_type, title, period_start, period_end, status) "
                        "values (:t, 'weekly_digest', 'x', :s, :s, 'completed')"
                    ),
                    {"t": tid, "s": start},
                )
        monkeypatch.setattr(wdt, "AsyncSessionLocal", sessionmaker(app, class_=AsyncSession, expire_on_commit=False))
        found = await wdt._tenants_with_digest(START)
        assert has in found
        assert lacks not in found
        assert other_week not in found
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(
                text("delete from report_artefacts where tenant_id in (:a, :b, :c)"), {"a": has, "b": lacks, "c": other_week}
            )
            await conn.execute(text("delete from tenants where id in (:a, :b, :c)"), {"a": has, "b": lacks, "c": other_week})
        await owner.dispose()
        await app.dispose()

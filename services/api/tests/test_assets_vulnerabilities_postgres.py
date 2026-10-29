"""An asset's vulnerabilities come back worst first and are limited, on a REAL Postgres.

The list sorted the severity as text, so "low" came before "medium" and the page showed the mild ones above the serious ones, and it had no limit at all.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database).
"""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.assets import list_asset_vulnerabilities
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def asset():
    tenant, asset_id = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(
                text("insert into tenants (id, name, slug) values (:t, :n, :n)"), {"t": tenant, "n": f"vuln-{tenant.hex[:10]}"}
            )
            await conn.execute(text("insert into assets (id, tenant_id, name) values (:a, :t, 'FS-01')"), {"a": asset_id, "t": tenant})
            for i, severity in enumerate(["low", "critical", "info", "medium", "high", "critical", "low"]):
                await conn.execute(
                    text(
                        "insert into asset_vulnerabilities (id, tenant_id, asset_id, title, severity, source, last_found) "
                        "values (:i, :t, :a, :title, :s, 'scanner', now() - make_interval(mins => :age))"
                    ),
                    {"i": uuid.uuid4(), "t": tenant, "a": asset_id, "title": f"v{i}-{severity}", "s": severity, "age": i},
                )
        yield engine, tenant, asset_id
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from asset_vulnerabilities where tenant_id = :t"), {"t": tenant})
            await conn.execute(text("delete from assets where tenant_id = :t"), {"t": tenant})
            await conn.execute(text("delete from tenants where id = :t"), {"t": tenant})
        await engine.dispose()


async def read(engine, tenant, asset_id, **kw):
    async with AsyncSession(engine) as db:
        await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
        return await list_asset_vulnerabilities(asset_id, db=db, current_user=SimpleNamespace(tenant_id=tenant), **kw)


@pytest.mark.asyncio
async def test_the_worst_come_first_and_newest_first_within_a_severity(asset):
    engine, tenant, asset_id = asset
    rows = await read(engine, tenant, asset_id, limit=200)
    assert [r.severity for r in rows] == ["critical", "critical", "high", "medium", "low", "low", "info"]
    assert [r.title for r in rows][:2] == ["v1-critical", "v5-critical"], "newer first within the same severity"


@pytest.mark.asyncio
async def test_the_list_is_limited_after_it_is_sorted(asset):
    engine, tenant, asset_id = asset
    rows = await read(engine, tenant, asset_id, limit=3)
    assert [r.severity for r in rows] == ["critical", "critical", "high"], "a short page is the worst, not an arbitrary few"

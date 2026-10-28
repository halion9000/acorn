"""Saving what a scan found, against a REAL Postgres: a discovered domain and address are stored, and a second scan of the same things records no new change.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database). This failed in a person's running system with `invalid input value for enum external_asset_type: "DOMAIN"`
until the model sent the enum's values.
"""

import os
import uuid

import pytest
from app.models.easm import ExternalAssetType
from app.services.easm_discovery import DiscoveredAsset
from app.services.easm_drift import detect_drift
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    tid = uuid.uuid4()
    tag = uuid.uuid4().hex[:10]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(
                text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"),
                {"i": tid, "n": f"easm-{tag}", "s": f"easm-{tag}"},
            )
        yield tid, engine
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from external_asset_drift where tenant_id = :t"), {"t": tid})
            await conn.execute(text("delete from external_assets where tenant_id = :t"), {"t": tid})
            await conn.execute(text("delete from tenants where id = :t"), {"t": tid})
        await engine.dispose()


async def session(engine):
    db = async_sessionmaker(engine, expire_on_commit=False)()
    await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
    return db


@pytest.mark.asyncio
async def test_a_found_domain_and_address_are_saved_and_a_repeat_scan_finds_nothing_new(world):
    tid, engine = world
    found = [
        DiscoveredAsset(ExternalAssetType.DOMAIN, "acme.com", {}),
        DiscoveredAsset(ExternalAssetType.IP, "203.0.113.10", {"ports": [443]}),
    ]
    db = await session(engine)
    first = await detect_drift(db, tid, found)
    await db.commit()
    again = await detect_drift(db, tid, found)
    await db.commit()
    await db.close()
    assert len(first) == 2 and {d.drift_type for d in first} == {"new_asset"}
    assert again == [], "the same scan again changes nothing"
    check = await session(engine)
    stored = (
        await check.execute(text("select asset_type::text, value from external_assets where tenant_id = :t order by value"), {"t": tid})
    ).all()
    await check.close()
    assert sorted(tuple(r) for r in stored) == [("domain", "acme.com"), ("ip", "203.0.113.10")]

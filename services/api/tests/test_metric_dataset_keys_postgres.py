"""Every Metrics dataset key the API accepts can be stored by the database (a check on the key column once refused two of them with a 422). Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid

import pytest
from app.models.metric_dataset import DATASET_KEYS
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")]


async def test_the_database_stores_every_dataset_key_the_api_accepts_and_refuses_an_unknown_one():
    tid = uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'mdk', :s)"), {"i": tid, "s": f"mdk-{tid.hex[:8]}"})
            for key in DATASET_KEYS:
                await conn.execute(text("insert into metric_datasets (tenant_id, key, payload) values (:t, :k, '{}'::jsonb)"), {"t": tid, "k": key})
            n = (await conn.execute(text("select count(*) from metric_datasets where tenant_id = :t"), {"t": tid})).scalar()
            assert n == len(DATASET_KEYS)
            await conn.execute(text("delete from metric_datasets where tenant_id = :t"), {"t": tid})
            await conn.execute(text("delete from tenants where id = :t"), {"t": tid})
    finally:
        await engine.dispose()
    engine2 = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        with pytest.raises(Exception, match="metric_datasets_key"):
            async with engine2.begin() as conn:
                await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
                t2 = uuid.uuid4()
                await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'mdk2', :s)"), {"i": t2, "s": f"mdk-{t2.hex[:8]}"})
                await conn.execute(text("insert into metric_datasets (tenant_id, key, payload) values (:t, 'not-a-dataset', '{}'::jsonb)"), {"t": t2})
    finally:
        await engine2.dispose()

"""Migration 200: a role that hid the old "Automation" menu section also hides its new name, "Response & Defense", and nothing else changes (a REAL Postgres: AISOC_TEST_PG_URL, a disposable fully migrated database)."""

import json
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")]

SQL = (Path(__file__).resolve().parents[1] / "migrations" / "200_role_hidden_response_defense.sql").read_text(encoding="utf-8")


async def test_only_roles_that_hid_automation_gain_response_and_defense_once_and_other_roles_are_untouched():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    tenant = uuid.uuid4()
    roles = {
        "hid old": ["section:Automation", "/settings"],
        "hid both already": ["section:Automation", "section:Response & Defense"],
        "hid something else": ["section:vCIO"],
        "hid nothing": [],
    }
    try:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(text("insert into tenants (id, name, slug) values (:t, 'mig200', :s)"), {"t": tenant, "s": f"m200-{tenant.hex[:8]}"})
            for name, hidden in roles.items():
                await conn.execute(
                    text("insert into roles (id, tenant_id, name, is_system, hidden_nav, created_at, updated_at) values (:i, :t, :n, false, cast(:h as jsonb), now(), now())"),
                    {"i": uuid.uuid4(), "t": tenant, "n": name, "h": json.dumps(hidden)},
                )

        async def hidden():
            async with engine.begin() as conn:
                rows = (await conn.execute(text("select name, hidden_nav from roles where tenant_id = :t"), {"t": tenant})).all()
            return {n: h for n, h in rows}

        async def run_migration():
            async with engine.connect() as conn:
                raw = await conn.get_raw_connection()
                await raw.driver_connection.execute(SQL)

        await run_migration()
        after = await hidden()
        assert after["hid old"] == ["section:Automation", "/settings", "section:Response & Defense"]
        assert after["hid both already"] == ["section:Automation", "section:Response & Defense"], "not added twice"
        assert after["hid something else"] == ["section:vCIO"]
        assert after["hid nothing"] == []
        await run_migration()
        assert await hidden() == after, "running it again changes nothing"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(text("delete from roles where tenant_id = :t"), {"t": tenant})
            await conn.execute(text("delete from tenants where id = :t"), {"t": tenant})
        await engine.dispose()

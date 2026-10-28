"""Migration 121 against a REAL Postgres: devices that carry an unfilled-template serial are removed (with their sources), real ones are left alone, and running it again changes nothing.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database).
"""

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "121_clear_placeholder_serials.sql"


@pytest.fixture
async def world():
    tid = uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(
                text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'child')"), {"i": tid, "n": f"ser-{tag}", "s": f"ser-{tag}"}
            )
        yield engine, tid
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from device_sources where tenant_id = :t"), {"t": tid})
            await conn.execute(text("delete from devices where tenant_id = :t"), {"t": tid})
            await conn.execute(text("delete from tenants where id = :t"), {"t": tid})
        await engine.dispose()


async def add_device(conn, tid, hostname, serial, sources):
    device_id = uuid.uuid4()
    await conn.execute(
        text("insert into devices (id, tenant_id, hostname, serial_number) values (:i, :t, :h, :s)"),
        {"i": device_id, "t": tid, "h": hostname, "s": serial},
    )
    for vendor, ext in sources:
        await conn.execute(
            text("insert into device_sources (tenant_id, device_id, vendor, external_id, name) values (:t, :d, :v, :e, :n)"),
            {"t": tid, "d": device_id, "v": vendor, "e": f"{ext}-{uuid.uuid4().hex[:4]}", "n": hostname},
        )


@pytest.mark.asyncio
async def test_a_device_holding_an_unfilled_template_serial_is_removed_with_its_sources_and_real_serials_stay(world):
    engine, tid = world
    sql = MIGRATION.read_text(encoding="utf-8")
    async with engine.begin() as conn:
        await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await add_device(conn, tid, "NUC-A", "$(DEFAULT_STRING)", [("ninjaone", "1"), ("auvik", "2"), ("huntress", "3")])
        await add_device(conn, tid, "PC-REAL", "MXL51931WM", [("ninjaone", "4")])
        await add_device(conn, tid, "PC-NONE", None, [("auvik", "5")])
        await conn.execute(text(sql))
        await conn.execute(text(sql))  # running it again changes nothing
        devices = (await conn.execute(text("select hostname from devices where tenant_id = :t order by hostname"), {"t": tid})).scalars().all()
        sources = (await conn.execute(text("select count(*) from device_sources where tenant_id = :t"), {"t": tid})).scalar_one()
    assert devices == ["PC-NONE", "PC-REAL"]
    assert sources == 2, "the removed device's three source records went with it"

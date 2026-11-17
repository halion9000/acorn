"""Migration 209 on a REAL Postgres: a ThreatMate line still on the old default (Internal assets) moves to Billable assets; a line a person pointed elsewhere, and a line of another tool, are left alone; running it twice
changes nothing more. Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import pathlib
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]
SQL = (pathlib.Path(__file__).resolve().parents[1] / "migrations" / "209_threatmate_billable_mapping.sql").read_text(encoding="utf8")
OLD = '[{"source": "threatmate", "item": "Internal assets"}]'


async def test_only_the_old_default_is_moved_and_a_second_run_changes_nothing():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    t = uuid.uuid4()
    async with factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"tm-{t.hex[:10]}"})
        rows = {
            "ThreatMate (Included)": OLD,
            "ThreatMate Extra": '[{"source": "threatmate", "item": "Users"}]',
            "ThreatMate Both": '[{"source": "threatmate", "item": "Internal assets"}, {"source": "threatmate", "item": "Users"}]',
            "Huntress for Workstations": '[{"source": "huntress", "item": "Agents"}]',
        }
        for item, counted in rows.items():
            await s.execute(text("insert into billing_item_map (tenant_id, invoice_item, counted) values (:t, :i, cast(:c as jsonb))"), {"t": t, "i": item, "c": counted})
        await s.commit()
    try:
        for _ in range(2):
            async with factory() as s:
                await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
                await s.execute(text(SQL.replace("BEGIN;", "").replace("COMMIT;", "")))
                await s.commit()
        async with factory() as s:
            await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            got = dict((await s.execute(text("select invoice_item, counted::text from billing_item_map where tenant_id = :t"), {"t": t})).all())
        assert '"Billable assets"' in got["ThreatMate (Included)"] and "Internal assets" not in got["ThreatMate (Included)"]
        assert "Users" in got["ThreatMate Extra"] and "Billable" not in got["ThreatMate Extra"], "a line a person pointed elsewhere is left alone"
        assert "Internal assets" in got["ThreatMate Both"], "a line with two counts is not the default"
        assert "Agents" in got["Huntress for Workstations"]
    finally:
        async with factory() as s:
            await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await s.execute(text("delete from billing_item_map where tenant_id = :t"), {"t": t})
            await s.execute(text("delete from tenants where id = :t"), {"t": t})
            await s.commit()
        await engine.dispose()

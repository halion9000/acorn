"""Search-everything finds vendors and compliance controls, on a REAL Postgres (AISOC_TEST_PG_URL): vendors only inside the caller's own organization, archived ones never, controls by id or title."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_global_search_postgres import PG_URL, cleanup, run, world

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


async def add_vendor(engine, tenant_id, name, service=None, category="Other", archived=False):
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(
            text(
                "insert into vendors (id, tenant_id, name, service, category, risk_level, data_access, notes, status, archived_at, created_at, updated_at) "
                "values (:i, :t, :n, :s, :c, 'unassessed', 'unknown', '', 'active', :a, :now, :now)"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "n": name, "s": service, "c": category, "a": now if archived else None, "now": now},
        )


async def drop_vendors(engine, ids):
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("delete from vendors where tenant_id = any(:t)"), {"t": [ids.owner, ids.acme, ids.birch, ids.stranger, ids.theirs]})


async def test_a_vendor_is_found_by_name_service_or_category_for_the_owner_and_its_clients_and_never_for_a_stranger_or_when_archived():
    engine, user, w = await world()
    try:
        await add_vendor(engine, w.owner, "Zorbex Cloud", service="Backups", category="Infrastructure")
        await add_vendor(engine, w.acme, "Zorbex for Acme")
        await add_vendor(engine, w.theirs, "Zorbex Strangers")
        await add_vendor(engine, w.owner, "Zorbex Old", archived=True)
        async with AsyncSession(engine) as db:
            out = await run(user, db, "zorbex")
            vendors = [h for h in out.hits if h.kind == "vendor"]
            assert sorted(h.title for h in vendors) == ["Zorbex Cloud", "Zorbex for Acme"]
            assert {h.client for h in vendors} == {None, "Waterloo Sparkling Water Corp."}
            by_service = await run(user, db, "backups")
            assert [h.title for h in by_service.hits if h.kind == "vendor"] == ["Zorbex Cloud"]
            assert [h.detail for h in by_service.hits if h.kind == "vendor"] == ["Backups · Infrastructure"]
            as_client = await run(SimpleNamespace(tenant_id=w.acme, email="x@acme.example"), db, "zorbex")
            assert [h.title for h in as_client.hits if h.kind == "vendor"] == ["Zorbex for Acme"]
    finally:
        await drop_vendors(engine, w)
        await cleanup(engine, w)


async def test_a_control_is_found_by_its_id_or_title_with_its_framework_and_no_client_and_respects_the_limit():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            by_id = await run(user, db, "CC6.1")
            controls = [h for h in by_id.hits if h.kind == "control"]
            assert controls and controls[0].id == "SOC2:CC6.1"
            assert controls[0].detail == "SOC2" and controls[0].client is None
            assert "Logical access" in controls[0].title
            by_title = await run(user, db, "least privilege")
            assert any(h.kind == "control" and h.id == "SOC2:CC6.3" for h in by_title.hits)
            many = await run(user, db, "access", limit=2)
            assert len([h for h in many.hits if h.kind == "control"]) == 2
            assert [h for h in (await run(user, db, "zzzzqqqq")).hits if h.kind == "control"] == []
    finally:
        await cleanup(engine, w)

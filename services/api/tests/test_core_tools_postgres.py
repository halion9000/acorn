"""The tools CORE says are connected are kept and listed, against a REAL Postgres (opt in with AISOC_TEST_PG_URL, a DISPOSABLE, fully migrated database)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.client_review import CoreToolIn, CoreToolsReport, apply_core_tools
from app.api.v1.endpoints.connectors import list_core_tools
from app.db.rls import set_rls_context
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


def tool(tool_id, title, connected, description=""):
    return CoreToolIn(tool_id=tool_id, title=title, connected=connected, description=description)


@pytest.fixture
async def tenants():
    tag = uuid.uuid4().hex[:10]
    ids = {"a": uuid.uuid4(), "b": uuid.uuid4()}
    engine = create_async_engine(PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, tid in ids.items():
                await conn.execute(text("insert into tenants (id, name, slug) values (:i, :n, :s)"), {"i": tid, "n": f"ct-{key}-{tag}", "s": f"ct-{key}-{tag}"})
        yield ids
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in ids.values()]})
        await engine.dispose()


async def run(tid, work):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            out = await work(db)
            await db.commit()
            return out
    finally:
        await engine.dispose()


async def listed(tid):
    return await run(tid, lambda db: list_core_tools(current_user=SimpleNamespace(tenant_id=tid), db=db))


async def test_each_report_replaces_the_last_and_drops_a_tool_core_no_longer_lists(tenants):
    a = tenants["a"]
    assert await run(a, lambda db: apply_core_tools(db, a, CoreToolsReport(tools=[tool("huntress", "Huntress", True, "EDR"), tool("petra-mdr", "Petra MDR", True), tool("hudu", "Hudu", False)]))) == 3
    assert [(t.tool_id, t.connected) for t in await listed(a)] == [("huntress", True), ("petra-mdr", True), ("hudu", False)], "connected ones first, then by name"
    await run(a, lambda db: apply_core_tools(db, a, CoreToolsReport(tools=[tool("huntress", "Huntress EDR", False), tool("hudu", "Hudu", True)])))
    now = {t.tool_id: t for t in await listed(a)}
    assert set(now) == {"huntress", "hudu"}, "petra-mdr was not listed, so it is gone"
    assert now["huntress"].title == "Huntress EDR" and now["huntress"].connected is False and now["hudu"].connected is True


async def test_an_empty_report_clears_the_list(tenants):
    a = tenants["a"]
    await run(a, lambda db: apply_core_tools(db, a, CoreToolsReport(tools=[tool("huntress", "Huntress", True)])))
    await run(a, lambda db: apply_core_tools(db, a, CoreToolsReport(tools=[])))
    assert await listed(a) == []


async def test_one_tenant_never_sees_or_changes_another_tenants_tools(tenants):
    a, b = tenants["a"], tenants["b"]
    await run(a, lambda db: apply_core_tools(db, a, CoreToolsReport(tools=[tool("huntress", "Huntress", True)])))
    await run(b, lambda db: apply_core_tools(db, b, CoreToolsReport(tools=[tool("hudu", "Hudu", True)])))
    await run(b, lambda db: apply_core_tools(db, b, CoreToolsReport(tools=[])))
    assert [t.tool_id for t in await listed(a)] == ["huntress"]
    assert await listed(b) == []


def test_a_tool_id_or_text_that_does_not_fit_is_refused():
    for bad in ({"tool_id": "Has Space", "title": "x", "connected": True}, {"tool_id": "ok", "title": "", "connected": True}, {"tool_id": "ok", "title": "x" * 121, "connected": True}, {"tool_id": "ok", "title": "x", "connected": "yes please"}):
        with pytest.raises(ValidationError):
            CoreToolIn(**bad)

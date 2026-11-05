"""Remote-tool alerts close themselves when the finding is gone, and reopen when it is back, against a REAL Postgres (opt in with AISOC_TEST_PG_URL, a DISPOSABLE, fully migrated database)."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.api.v1.endpoints.remote_tools import FoundIn, RemoteToolsReport, apply_report, back_note, gone_note
from app.db.rls import set_rls_context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")

MINE = "aaaaaaaaaaaaaaaa"
OTHER = "d031906d9b70af1e"
T0 = datetime.now(UTC) - timedelta(hours=3)


@pytest.fixture
async def owner():
    tid = uuid.uuid4()
    engine = create_async_engine(PG_URL)
    async with engine.begin() as c:
        await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await c.execute(
            text("insert into tenants (id, name, slug, mssp_role, settings) values (:i, :n, :s, 'parent', cast(:st as jsonb))"),
            {"i": tid, "n": f"rt-{tid.hex[:8]}", "s": f"rt-{tid.hex[:8]}", "st": json.dumps({"remote_tool_instances": {"screenconnect": [MINE]}})},
        )
    yield tid
    async with engine.begin() as c:
        await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await c.execute(text("set local session_replication_role = replica"))
        await c.execute(text("delete from vendor_actions where tenant_id = :t"), {"t": tid})
        await c.execute(text("delete from alerts where tenant_id = :t"), {"t": tid})
        await c.execute(text("delete from device_remote_tools where tenant_id = :t"), {"t": tid})
        await c.execute(text("delete from remote_tool_scans where tenant_id = :t"), {"t": tid})
        await c.execute(text("delete from tenants where id = :t"), {"t": tid})
    await engine.dispose()


def found(host: str, instance: str) -> FoundIn:
    return FoundIn(hostname=host, tool_key="screenconnect", program=f"ScreenConnect Client ({instance})")


async def scan(owner: uuid.UUID, items: list[FoundIn], devices: int, at: datetime):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, owner)
            out = await apply_report(db, owner, RemoteToolsReport(vendor="ninjaone", devices_scanned=devices, items=items), now=at)
            await db.commit()
            return out
    finally:
        await engine.dispose()


async def sql(owner: uuid.UUID, query: str, **params):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as c:
            await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            result = await c.execute(text(query), {"t": owner, **params})
            return result.fetchall() if result.returns_rows else []
    finally:
        await engine.dispose()


async def alerts(owner):
    return await sql(owner, "select title, status, enrichment_data from alerts where tenant_id = :t order by title")


async def notes(owner):
    return await sql(owner, "select params from vendor_actions where tenant_id = :t and action = 'ticket_note' order by created_at")


async def link_ticket(owner, ticket="555"):
    await sql(owner, "update alerts set enrichment_data = cast(:e as jsonb) where tenant_id = :t", e=json.dumps({"tickets": [{"system": "halopsa", "id": ticket}]}))


async def test_an_alert_closes_when_a_scan_no_longer_finds_the_install_and_the_ticket_is_told(owner):
    first = await scan(owner, [found("PC-1", OTHER)], 5, T0)
    assert first.alerts_raised == 1 and first.alerts_closed == 0
    await link_ticket(owner)
    out = await scan(owner, [], 5, T0 + timedelta(hours=1))
    assert (out.alerts_closed, out.alerts_reopened) == (1, 0)
    ((title, status, enrichment),) = await alerts(owner)
    assert status == "resolved" and "remote_tool_gone" in enrichment
    ((params,),) = await notes(owner)
    assert params["ticket_ids"] == ["555"] and params["note"] == gone_note(title, T0 + timedelta(hours=1))


async def test_a_scan_that_looked_at_no_devices_closes_nothing(owner):
    await scan(owner, [found("PC-1", OTHER)], 5, T0)
    out = await scan(owner, [], 0, T0 + timedelta(hours=1))
    assert out.alerts_closed == 0
    assert [a[1] for a in await alerts(owner)] == ["new"]


async def test_an_alert_for_a_server_that_is_still_there_stays_open_and_only_the_missing_one_closes(owner):
    await scan(owner, [found("PC-1", OTHER), found("PC-2", OTHER)], 5, T0)
    out = await scan(owner, [found("PC-1", OTHER)], 5, T0 + timedelta(hours=1))
    assert out.alerts_closed == 1
    by_title = {a[0]: a[1] for a in await alerts(owner)}
    assert sorted(by_title.values()) == ["new", "resolved"]
    assert [s for t, s in by_title.items() if "PC-1" in t] == ["new"]


async def test_an_alert_somebody_has_started_on_is_left_alone(owner):
    await scan(owner, [found("PC-1", OTHER)], 5, T0)
    await sql(owner, "update alerts set status = 'investigating' where tenant_id = :t")
    out = await scan(owner, [], 5, T0 + timedelta(hours=1))
    assert out.alerts_closed == 0
    assert [a[1] for a in await alerts(owner)] == ["investigating"]


async def test_the_install_coming_back_reopens_the_alert_this_closed_and_says_so_on_the_ticket(owner):
    await scan(owner, [found("PC-1", OTHER)], 5, T0)
    await link_ticket(owner)
    await scan(owner, [], 5, T0 + timedelta(hours=1))
    back = await scan(owner, [found("PC-1", OTHER)], 5, T0 + timedelta(hours=2))
    assert (back.alerts_closed, back.alerts_reopened, back.alerts_raised) == (0, 1, 0)
    ((title, status, enrichment),) = await alerts(owner)
    assert status == "new" and "remote_tool_gone" not in enrichment
    texts = [p[0]["note"] for p in await notes(owner)]
    assert texts == [gone_note(title, T0 + timedelta(hours=1)), back_note(title, T0 + timedelta(hours=2))]


async def test_an_alert_a_person_closed_stays_closed_when_the_install_is_still_there(owner):
    await scan(owner, [found("PC-1", OTHER)], 5, T0)
    await sql(owner, "update alerts set status = 'false_positive' where tenant_id = :t")
    out = await scan(owner, [found("PC-1", OTHER)], 5, T0 + timedelta(hours=1))
    assert (out.alerts_closed, out.alerts_reopened) == (0, 0)
    assert [a[1] for a in await alerts(owner)] == ["false_positive"]


async def test_an_install_that_is_now_yours_closes_its_alert(owner):
    await scan(owner, [found("PC-1", OTHER)], 5, T0)
    await sql(owner, "update tenants set settings = cast(:s as jsonb) where id = :t", s=json.dumps({"remote_tool_instances": {"screenconnect": [MINE, OTHER]}}))
    out = await scan(owner, [found("PC-1", OTHER)], 5, T0 + timedelta(hours=1))
    assert out.alerts_closed == 1


async def test_an_alert_a_person_marked_resolved_is_not_reopened_by_a_scan_that_still_sees_the_install(owner):
    """Only an alert this tidy-up closed (it carries the mark) may be reopened: a person's 'resolved' is their decision."""
    await scan(owner, [found("PC-1", OTHER)], 5, T0)
    await sql(owner, "update alerts set status = 'resolved' where tenant_id = :t")
    out = await scan(owner, [found("PC-1", OTHER)], 5, T0 + timedelta(hours=1))
    assert (out.alerts_closed, out.alerts_reopened) == (0, 0)
    assert [a[1] for a in await alerts(owner)] == ["resolved"]

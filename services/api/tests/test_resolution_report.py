"""The Ticket Resolution page from the statistics CORE reads through the HaloPSA report call (counted the way the Rewst dashboard counts)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import inbox_core_feed as feed
from app.api.v1.endpoints import metrics_pages as mp
from app.db.rls import set_rls_context
from app.models.ticket_stats import TicketStatsSnapshot
from app.services import metrics_tickets as mt
from app.services import month_window as mw
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

RES = {
    "agents": [
        {"month": "2026-08", "agent_name": "Dan Kemp", "n": 5},
        {"month": "2026-09", "agent_name": "Dan Kemp", "n": 7},
        {"month": "2026-09", "agent_name": "Eve Lee", "n": 20},
        {"month": "2026-10", "agent_name": "Dan Kemp", "n": 4},
        {"month": "2026-10", "agent_name": "Nobody", "n": 0},
        {"month": "2024-01", "agent_name": "Old Hand", "n": 99},
    ],
    "clients": [
        {"month": "2026-09", "client": "Acme", "hours": 10.25, "n": 3},
        {"month": "2026-10", "client": "Acme", "hours": 5.0, "n": 2},
        {"month": "2026-10", "client": "Birch Law", "hours": 100.0, "n": 4},
    ],
}


def test_nothing_sent_means_the_older_weekly_facts_are_used():
    assert mt.resolution_from_report(None, 12) is None
    assert mt.resolution_from_report({}, 12) is None


def test_the_newest_months_are_totalled_per_person_and_per_client_biggest_first_and_people_with_nothing_are_left_out():
    out = mt.resolution_from_report(RES, 2)
    assert out["source"] == "report" and out["months"] == ["2026-09", "2026-10"] and out["available_months"] == 4
    assert [(m["engineer"], m["total"]) for m in out["members"]] == [("Eve Lee", 20), ("Dan Kemp", 11)]
    assert out["members"][1]["by_month"] == {"2026-09": 7, "2026-10": 4}
    assert [(c["client"], c["total"]) for c in out["clients"]] == [("Birch Law", 100.0), ("Acme", 15.2)]
    assert out["clients"][1]["by_month"] == {"2026-09": 10.2, "2026-10": 5.0}


def test_a_custom_range_covers_exactly_its_months():
    token = mw._window.set(("2024-01", "2026-08"))
    try:
        out = mt.resolution_from_report(RES, 3)
    finally:
        mw._window.reset(token)
    assert out["months"] == ["2024-01", "2026-08"]
    assert [(m["engineer"], m["total"]) for m in out["members"]] == [("Old Hand", 99), ("Dan Kemp", 5)]
    assert out["clients"] == []


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
needs_pg = pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database")

STATS = {"months": ["2026-10"], "rows": [], "open_now": []}


@pytest.fixture
async def tenant(monkeypatch):
    tid = uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'rr-test', :s)"), {"i": tid, "s": f"rr-{tid.hex[:8]}"})

    async def verify(db, token):
        return tid

    monkeypatch.setattr(feed, "_verify_core_feed_token", verify)
    yield SimpleNamespace(id=tid, user=SimpleNamespace(tenant_id=tid, user_id=None, email="hal@goliveoak.com"))
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("delete from ticket_stats_snapshots where tenant_id = :t"), {"t": tid})
        await conn.execute(text("delete from tenants where id = :t"), {"t": tid})
    await engine.dispose()


async def with_db(tid, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            return await work(db)
    finally:
        await engine.dispose()


@needs_pg
@pytest.mark.asyncio
async def test_the_page_uses_the_report_data_once_sent_and_a_later_pass_without_it_keeps_the_last_one(tenant):
    async def send(body):
        async with async_sessionmaker(create_async_engine(APP_URL, poolclass=NullPool), expire_on_commit=False)() as db:
            await set_rls_context(db, tenant.id)
            return await feed.report_core_feed_ticket_stats("tok", feed.TicketStatsIn.model_validate(body), db)

    before = await with_db(tenant.id, lambda db: mp.ticket_resolution(tenant.user, db, 12))
    assert before["source"] == "weekly", "until CORE sends the new data the older weekly facts answer"
    await send({**STATS, "resolution": RES})
    got = await with_db(tenant.id, lambda db: mp.ticket_resolution(tenant.user, db, 12))
    assert got["source"] == "report" and got["months"][0] == "2024-01" and got["received_at"] is not None
    await send(STATS)  # a pass that could not read the resolution part
    again = await with_db(tenant.id, lambda db: mp.ticket_resolution(tenant.user, db, 12))
    assert again["source"] == "report" and [m["engineer"] for m in again["members"]][:2] == ["Old Hand", "Eve Lee"], "the last resolution was kept"

    async def stored(db):
        return (await db.execute(select(TicketStatsSnapshot).where(TicketStatsSnapshot.tenant_id == tenant.id))).scalar_one().payload["resolution"]["agents"]

    assert len(await with_db(tenant.id, stored)) == 6

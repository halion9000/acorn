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


# --- Ticket Volume from the same monthly statistics --------------------------------------------------------------------------------------------------------------------------------------------------------
VOL_STATS = {
    "months": ["2026-09", "2026-10"],
    "rows": [
        {"client_id": "1", "client_name": "Acme", "month": "2026-09", "created": 6, "resolved": 0, "responded": 0, "response_minutes": 0, "created_by_type": {}, "resolved_by_agent": {}, "critical": 0, "high": 0},
        {"client_id": "1", "client_name": "Acme", "month": "2026-10", "created": 4, "resolved": 0, "responded": 0, "response_minutes": 0, "created_by_type": {}, "resolved_by_agent": {}, "critical": 0, "high": 0},
        {"client_id": "2", "client_name": "Birch", "month": "2026-10", "created": 5, "resolved": 0, "responded": 0, "response_minutes": 0, "created_by_type": {}, "resolved_by_agent": {}, "critical": 0, "high": 0},
    ],
    "open_now": [],
    "volume": {
        "types": [{"month": "2026-09", "type": "Incident", "n": 6}, {"month": "2026-10", "type": "Incident", "n": 3}, {"month": "2026-10", "type": "Request", "n": 6}],
        "categories": [{"month": "2026-09", "category": "Email", "n": 6}, {"month": "2026-10", "category": "(none)", "n": 9}],
    },
}


def test_volume_counts_come_from_the_monthly_statistics_and_follow_the_months_asked_for():
    out = mt.volume_from_stats(VOL_STATS, 1)
    assert out["months"] == ["2026-10"] and out["total_created"] == 9 and out["available_months"] == 2
    assert out["per_month"] == [{"month": "2026-10", "created": 9}]
    assert [(x["name"], x["total"]) for x in out["by_type"]] == [("Request", 6), ("Incident", 3)]
    assert [(x["name"], x["by_month"]) for x in out["by_category"]] == [("(none)", {"2026-10": 9})]
    assert out["by_client"] == [{"client": "Birch", "created": 5}, {"client": "Acme", "created": 4}]
    both = mt.volume_from_stats(VOL_STATS, 12)
    assert both["months"] == ["2026-09", "2026-10"] and both["total_created"] == 15
    assert both["total_created"] == sum(p["created"] for p in both["per_month"]), "the monthly totals are the Ticket Summary's created counts"


def test_volume_is_none_until_core_sends_it():
    assert mt.volume_from_stats(None, 3) is None
    assert mt.volume_from_stats({**VOL_STATS, "volume": None}, 3) is None
    assert mt.volume_from_stats({**VOL_STATS, "rows": []}, 3) is None


@needs_pg
@pytest.mark.asyncio
async def test_the_volume_page_uses_the_monthly_counts_once_sent_and_a_later_pass_without_them_keeps_the_last(tenant):
    async def send(body):
        async with async_sessionmaker(create_async_engine(APP_URL, poolclass=NullPool), expire_on_commit=False)() as db:
            await set_rls_context(db, tenant.id)
            return await feed.report_core_feed_ticket_stats("tok", feed.TicketStatsIn.model_validate(body), db)

    await send(VOL_STATS)
    got = await with_db(tenant.id, lambda db: mp.ticket_volume(tenant.user, db, 12))
    assert got["source"] == "report" and got["total_created"] == 15
    await send({"months": ["2026-10"], "rows": VOL_STATS["rows"], "open_now": []})  # a pass that could not read the volume part
    again = await with_db(tenant.id, lambda db: mp.ticket_volume(tenant.user, db, 12))
    assert again["source"] == "report" and again["total_created"] == 15, "the last volume counts were kept"


# --- A smaller pass does not cut the months held ---------------------------------------------------------------------------------------------------------------------------------------------------------------
def _month_row(month, client="1", created=1):
    return {"client_id": client, "client_name": "Acme", "month": month, "created": created, "resolved": 0, "responded": 0, "response_minutes": 0, "created_by_type": {}, "resolved_by_agent": {}, "critical": 0, "high": 0}


def test_a_pass_that_read_fewer_months_replaces_those_months_and_keeps_the_others():
    from app.services.ticket_stats_merge import merge_ticket_stats

    old = {"months": ["2026-08", "2026-09", "2026-10"], "rows": [_month_row("2026-08", created=5), _month_row("2026-09", created=6), _month_row("2026-10", created=7), _month_row("2026-10", client="2", created=2)], "open_now": [{"client_id": "1"}]}
    new = {"months": ["2026-10", "2026-11"], "rows": [_month_row("2026-10", created=9), _month_row("2026-11", created=3)], "open_now": [{"client_id": "9"}]}
    out = merge_ticket_stats(old, new)
    assert out["months"] == ["2026-08", "2026-09", "2026-10", "2026-11"]
    assert sorted((r["month"], r["client_id"], r["created"]) for r in out["rows"]) == [("2026-08", "1", 5), ("2026-09", "1", 6), ("2026-10", "1", 9), ("2026-11", "1", 3)], "October is replaced whole: the second client's old row is gone with it"
    assert out["open_now"] == [{"client_id": "9"}]
    assert merge_ticket_stats(None, new) == new
    assert merge_ticket_stats(old, new, limit=2)["months"] == ["2026-10", "2026-11"] and all(r["month"] >= "2026-10" for r in merge_ticket_stats(old, new, limit=2)["rows"])


@needs_pg
@pytest.mark.asyncio
async def test_the_ticket_summary_keeps_its_months_when_a_later_pass_carries_fewer(tenant):
    async def send(body):
        async with async_sessionmaker(create_async_engine(APP_URL, poolclass=NullPool), expire_on_commit=False)() as db:
            await set_rls_context(db, tenant.id)
            return await feed.report_core_feed_ticket_stats("tok", feed.TicketStatsIn.model_validate(body), db)

    await send({"months": ["2026-09", "2026-10"], "rows": [_month_row("2026-09"), _month_row("2026-10")], "open_now": []})
    await send({"months": ["2026-10"], "rows": [_month_row("2026-10", created=8)], "open_now": []})

    async def stored(db):
        return (await db.execute(select(TicketStatsSnapshot).where(TicketStatsSnapshot.tenant_id == tenant.id))).scalar_one().payload

    held = await with_db(tenant.id, stored)
    assert held["months"] == ["2026-09", "2026-10"] and sorted((r["month"], r["created"]) for r in held["rows"]) == [("2026-09", 1), ("2026-10", 8)]

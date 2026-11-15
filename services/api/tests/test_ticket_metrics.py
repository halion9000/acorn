"""Ticket metrics and customer satisfaction from the summaries CORE sends from HaloPSA and SimpleSat.

The arithmetic first (pure), then the stored rows and endpoints against a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).
"""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import inbox_core_feed as feed
from app.api.v1.endpoints import ticket_metrics as ep
from app.db.rls import set_rls_context
from app.models.finance_profit import FinanceProfitSnapshot
from app.models.ticket_stats import CsatSnapshot, TicketStatsSnapshot
from app.services import ticket_metrics as tm
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def month(client, name, m, created, resolved, **over):
    base = {
        "client_id": client,
        "client_name": name,
        "month": m,
        "created": created,
        "resolved": resolved,
        "responded": created,
        "response_minutes": created * 20.0,
        "created_by_type": {"Incident": created},
        "resolved_by_agent": {"40": resolved},
        "critical": 0,
        "high": 0,
    }
    base.update(over)
    return base


STATS = {
    "months": ["2026-08", "2026-09", "2026-10", "2026-11"],
    "rows": [
        month("5", "Acme", "2026-08", 10, 9),
        month("5", "Acme", "2026-09", 20, 18, critical=2),
        month("5", "Acme", "2026-10", 30, 33, high=3, created_by_type={"Incident": 20, "Alert": 10}, resolved_by_agent={"40": 30, "41": 3}),
        month("6", "Birch", "2026-10", 4, 4),
        month("5", "Acme", "2026-11", 5, 1),
    ],
    "open_now": [
        {"client_id": "5", "client_name": "Acme", "total": 7, "critical": 1, "high": 2},
        {"client_id": "6", "client_name": "Birch", "total": 1, "critical": 0, "high": 0},
    ],
}


def test_the_newest_months_of_the_data_are_summed_for_one_client_or_all():
    one = tm.summarize(STATS, 3, "5", {"40": "Dan Kemp"})
    assert one["months"] == ["2026-09", "2026-10", "2026-11"]
    assert (one["created"], one["resolved"]) == (55, 52)
    assert (one["created_per_month"], one["resolved_per_month"]) == (18.3, 17.3)
    assert [s["created"] for s in one["series"]] == [20, 30, 5]
    assert one["first_response_minutes"] == 20.0 and one["responded"] == 55
    assert (one["critical_created"], one["high_created"]) == (2, 3)
    assert one["by_type"] == [{"type": "Incident", "tickets": 45}, {"type": "Alert", "tickets": 10}]
    assert one["resolved_by_agent"][0] == {"agent_id": "40", "name": "Dan Kemp", "tickets": 49}
    assert one["resolved_by_agent"][1]["name"] == "Agent 41", "an agent with no known name is still listed"
    assert one["open_now"] == {"total": 7, "critical": 1, "high": 2}
    everyone = tm.summarize(STATS, 1)
    assert everyone["months"] == ["2026-11"] and everyone["created"] == 5 and everyone["open_now"]["total"] == 8


def test_asking_for_more_months_than_the_data_has_gives_what_there_is():
    assert tm.summarize(STATS, 12)["months"] == ["2026-08", "2026-09", "2026-10", "2026-11"]
    empty = tm.summarize({"months": [], "rows": [], "open_now": []}, 3)
    assert empty["created"] == 0 and empty["created_per_month"] is None and empty["first_response_minutes"] is None


def test_the_clients_in_the_data_are_listed_by_name():
    assert tm.clients_in(STATS) == [{"client_id": "5", "client_name": "Acme"}, {"client_id": "6", "client_name": "Birch"}]


CSAT = {
    "months": ["2026-09", "2026-10"],
    "rows": [
        {"company": "Acme Dental, Inc.", "month": "2026-09", "positive": 8, "neutral": 1, "negative": 1, "total": 10},
        {"company": "Acme Dental, Inc.", "month": "2026-10", "positive": 9, "neutral": 0, "negative": 1, "total": 10},
        {"company": "Birch Law", "month": "2026-10", "positive": 1, "neutral": 0, "negative": 0, "total": 2},
    ],
    "recent": [
        {
            "company": "Acme Dental, Inc.",
            "date": "2026-10-20T10:00:00Z",
            "contact": "Amy",
            "sentiment": "negative",
            "rating": "Not good",
            "comment": "Slow",
            "ticket_id": "5001",
        },
        {
            "company": "Birch Law",
            "date": "2026-10-21T10:00:00Z",
            "contact": "Bo",
            "sentiment": "positive",
            "rating": "Great",
            "comment": "",
            "ticket_id": "",
        },
        {
            "company": "Acme Dental, Inc.",
            "date": "2026-01-02T10:00:00Z",
            "contact": "Old",
            "sentiment": "positive",
            "rating": "Great",
            "comment": "old",
            "ticket_id": "",
        },
    ],
}


def test_satisfaction_is_the_positive_share_with_a_trend_and_the_newest_comments_of_the_months_asked_for():
    a = tm.csat_for(CSAT, 2, "acme dental inc")
    assert (a["responses"], a["positive"], a["neutral"], a["negative"]) == (20, 17, 1, 2)
    assert a["satisfied_percent"] == 85.0
    assert [(t["month"], t["satisfied_percent"]) for t in a["trend"]] == [("2026-09", 80.0), ("2026-10", 90.0)]
    assert [r["contact"] for r in a["recent"]] == ["Amy"], "another company's and an older month's comments are not shown"
    allc = tm.csat_for(CSAT, 1)
    assert allc["months"] == ["2026-10"] and allc["responses"] == 12 and [r["contact"] for r in allc["recent"]] == ["Bo", "Amy"]
    assert tm.csat_for({"months": [], "rows": [], "recent": []}, 3)["satisfied_percent"] is None


PG_URL, APP_URL = os.environ.get("AISOC_TEST_PG_URL"), os.environ.get("AISOC_TEST_PG_APP_URL")
needs_pg = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)


@pytest.fixture
async def tenant():
    tid = uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'tm-test', :s)"), {"i": tid, "s": f"tm-{tid.hex[:8]}"})
    yield SimpleNamespace(id=tid, user=SimpleNamespace(tenant_id=tid, user_id=None, email="hal@goliveoak.com"))
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for table in ("ticket_stats_snapshots", "csat_snapshots", "finance_profit_snapshots"):
            await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": tid})
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
async def test_the_endpoints_are_empty_until_core_sends_then_answer_from_what_was_stored(tenant):
    assert (await with_db(tenant.id, lambda db: ep.ticket_metrics(tenant.user, db, 3, None)))["received_at"] is None
    assert (await with_db(tenant.id, lambda db: ep.csat(tenant.user, db, 3, None)))["summary"] is None

    stats = feed.TicketStatsIn.model_validate(STATS).model_dump()
    csat = feed.CsatIn.model_validate(CSAT).model_dump()

    async def store(db):
        db.add(TicketStatsSnapshot(tenant_id=tenant.id, payload=stats))
        db.add(CsatSnapshot(tenant_id=tenant.id, payload=csat))
        db.add(FinanceProfitSnapshot(tenant_id=tenant.id, payload={"agents": [{"id": "40", "name": "Dan Kemp", "team": "Support"}]}))
        await db.commit()

    await with_db(tenant.id, store)
    out = await with_db(tenant.id, lambda db: ep.ticket_metrics(tenant.user, db, 3, "5"))
    assert out["available_months"] == 4 and out["summary"]["created"] == 55
    assert out["summary"]["resolved_by_agent"][0]["name"] == "Dan Kemp", "agent names come from the profitability summary"
    assert [c["client_name"] for c in out["clients"]] == ["Acme", "Birch"]
    sat = await with_db(tenant.id, lambda db: ep.csat(tenant.user, db, 2, "Birch Law"))
    assert sat["companies"] == ["Acme Dental, Inc.", "Birch Law"] and sat["summary"]["responses"] == 2

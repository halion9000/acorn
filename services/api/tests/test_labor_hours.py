"""Labor hours (Metrics): hours worked on tickets by month, engineer, client and ticket type, from the HaloPSA summary CORE sends; hours only, readable with metrics:view."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import ticket_metrics as ep
from app.db.rls import set_rls_context
from app.models.finance_profit import FinanceProfitSnapshot
from app.services import ticket_metrics as tm
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

SNAP = {
    "months": ["2026-09", "2026-10"],
    "invoices": [],
    "hours": [
        {"client": "Acme Dental, Inc.", "month": "2026-10", "agent_id": "40", "charge_type": "Remote Support", "hours": 4},
        {"client": "Acme Dental, Inc.", "month": "2026-10", "agent_id": "41", "charge_type": "vCIO", "hours": 2.5},
        {"client": "Birch Law", "month": "2026-10", "agent_id": "40", "charge_type": "Remote Support", "hours": 1},
        {"client": "Nobody Invoiced LLC", "month": "2026-10", "agent_id": "40", "charge_type": "No Charge", "hours": 3},
        {"client": "Acme Dental, Inc.", "month": "2026-09", "agent_id": "40", "charge_type": "Remote Support", "hours": 10},
    ],
    "agents": [{"id": "40", "name": "Dan Kemp", "team": "Support"}, {"id": "41", "name": "Vic Cio", "team": "vCIO"}],
}


def test_the_newest_month_is_split_by_engineer_client_and_type_largest_first():
    r = tm.labor_hours(SNAP, 1)
    assert r["months"] == ["2026-10"] and r["total_hours"] == 10.5 and r["hours_per_month"] == 10.5
    assert [(a["name"], a["hours"]) for a in r["by_agent"]] == [("Dan Kemp", 8.0), ("Vic Cio", 2.5)]
    assert [(c["client"], c["hours"]) for c in r["by_client"]] == [
        ("Acme Dental, Inc.", 6.5),
        ("Nobody Invoiced LLC", 3.0),
        ("Birch Law", 1.0),
    ]
    assert [(t["type"], t["hours"]) for t in r["by_type"]] == [("Remote Support", 5.0), ("No Charge", 3.0), ("vCIO", 2.5)]


def test_two_months_add_up_and_average_and_one_client_can_be_chosen_by_name_whatever_the_punctuation():
    r = tm.labor_hours(SNAP, 2)
    assert (r["total_hours"], r["hours_per_month"]) == (20.5, 10.25)
    assert [(m["month"], m["hours"]) for m in r["by_month"]] == [("2026-09", 10.0), ("2026-10", 10.5)]
    acme = tm.labor_hours(SNAP, 2, "acme dental inc")
    assert acme["total_hours"] == 16.5 and [c["client"] for c in acme["by_client"]] == ["Acme Dental, Inc."]
    assert acme["clients"] == ["Acme Dental, Inc.", "Birch Law", "Nobody Invoiced LLC"], "the choices stay whole when one is chosen"


def test_more_months_than_the_data_has_gives_what_there_is_and_an_unknown_agent_is_named_by_id():
    r = tm.labor_hours({**SNAP, "agents": []}, 12)
    assert len(r["months"]) == 2 and r["by_agent"][0]["name"] == "Agent 40"
    empty = tm.labor_hours({"months": [], "hours": []}, 3)
    assert (empty["total_hours"], empty["hours_per_month"], empty["by_agent"]) == (0.0, None, [])


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
        await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'labor-test', :s)"), {"i": tid, "s": f"lh-{tid.hex[:8]}"})
    yield SimpleNamespace(id=tid, user=SimpleNamespace(tenant_id=tid, user_id=None))
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("delete from finance_profit_snapshots where tenant_id = :t"), {"t": tid})
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
async def test_the_endpoint_is_empty_until_core_sends_then_answers_from_what_was_stored(tenant):
    first = await with_db(tenant.id, lambda db: ep.labor_hours(tenant.user, db, 3, None))
    assert first == {"received_at": None, "summary": None}

    async def ingest(db):
        db.add(FinanceProfitSnapshot(tenant_id=tenant.id, payload=SNAP))
        await db.commit()

    await with_db(tenant.id, ingest)
    out = await with_db(tenant.id, lambda db: ep.labor_hours(tenant.user, db, 1, "Birch Law"))
    assert out["received_at"] is not None and out["summary"]["total_hours"] == 1.0

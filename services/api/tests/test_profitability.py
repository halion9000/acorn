"""Client profitability: revenue from the Halo summary, labor from hours times what an hour of that agent costs, what is left after labor.

The arithmetic first (pure), then the endpoints against a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).
"""

import os
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import finance as ep
from app.api.v1.endpoints import inbox_core_feed as feed
from app.db.rls import set_rls_context
from app.services import profitability as p
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

SNAP = {
    "months": ["2026-09", "2026-10"],
    "invoices": [
        {"client_id": "5", "client_name": "Acme Dental, Inc.", "month": "2026-10", "revenue": 1000, "invoices": 2},
        {"client_id": "6", "client_name": "Birch Law", "month": "2026-10", "revenue": 400.5, "invoices": 1},
        {"client_id": "5", "client_name": "Acme Dental, Inc.", "month": "2026-09", "revenue": 900, "invoices": 1},
    ],
    "hours": [
        {"client": "acme dental inc", "month": "2026-10", "agent_id": "40", "charge_type": "Remote Support", "hours": 4},
        {"client": "Acme Dental, Inc.", "month": "2026-10", "agent_id": "41", "charge_type": "vCIO", "hours": 2.5},
        {"client": "Birch Law", "month": "2026-10", "agent_id": "40", "charge_type": "Remote Support", "hours": 1},
        {"client": "Nobody Invoiced LLC", "month": "2026-10", "agent_id": "40", "charge_type": "No Charge", "hours": 3},
        {"client": "Acme Dental, Inc.", "month": "2026-09", "agent_id": "40", "charge_type": "Remote Support", "hours": 10},
    ],
    "agents": [{"id": "40", "name": "Dan Kemp", "team": "Support"}, {"id": "41", "name": "Vic Cio", "team": "vCIO"}],
}


def test_a_name_matches_whatever_the_punctuation_and_case():
    assert p.name_key("Acme Dental, Inc.") == p.name_key("acme dental inc") == "acmedentalinc"


def test_the_most_specific_rate_wins_and_the_default_is_sixty_five():
    table = p.resolve_rates([])
    agents = {"40": {"team": "Support"}}
    assert p.rate_for("40", agents, table) == (Decimal("65.00"), "default")
    table = p.resolve_rates(
        [
            {"scope": "default", "key": "", "hourly_rate": "70"},
            {"scope": "team", "key": "Support", "hourly_rate": "80"},
            {"scope": "agent", "key": "40", "hourly_rate": "95.5"},
        ]
    )
    assert p.rate_for("40", agents, table) == (Decimal("95.50"), "agent")
    assert p.rate_for("41", {"41": {"team": "Support"}}, table) == (Decimal("80.00"), "team")
    assert p.rate_for("99", {}, table) == (Decimal("70.00"), "default")


def test_revenue_hours_labor_and_what_is_left_per_client_for_a_month():
    rates = [{"scope": "team", "key": "Support", "hourly_rate": "100"}, {"scope": "agent", "key": "41", "hourly_rate": "200"}]
    r = p.profit_for_month(SNAP, rates, "2026-10", {"acmedentalinc": Decimal("123.45")})
    acme, birch = r["rows"]
    assert (acme["client_name"], acme["revenue"], acme["hours"], acme["labor"], acme["after_labor"]) == (
        "Acme Dental, Inc.",
        Decimal("1000.00"),
        Decimal("6.50"),
        Decimal("900.00"),
        Decimal("100.00"),
    )
    assert acme["margin_percent"] == 10.0 and acme["software_per_run"] == Decimal("123.45") and acme["invoices"] == 2
    assert (birch["revenue"], birch["labor"], birch["after_labor"], birch["margin_percent"]) == (
        Decimal("400.50"),
        Decimal("100.00"),
        Decimal("300.50"),
        75.0,
    )
    assert birch["software_per_run"] is None
    assert (
        r["totals"]["revenue"] == Decimal("1400.50")
        and r["totals"]["labor"] == Decimal("1000.00")
        and r["totals"]["hours"] == Decimal("7.50")
    )


def test_hours_for_a_client_nobody_invoiced_are_listed_not_dropped_and_agents_on_the_default_rate_are_named():
    r = p.profit_for_month(SNAP, [], "2026-10")
    assert r["unmatched_hours"] == [{"client": "Nobody Invoiced LLC", "hours": Decimal("3.00"), "labor": Decimal("195.00")}]
    assert [(a["name"], a["hours"]) for a in r["agents_on_default_rate"]] == [("Dan Kemp", Decimal("8.00")), ("Vic Cio", Decimal("2.50"))]
    assert r["default_rate"] == Decimal("65.00")
    assert p.profit_for_month(SNAP, [], "2026-09")["rows"][0]["labor"] == Decimal("650.00"), "another month does not leak in"


def test_a_client_with_no_revenue_has_no_margin_instead_of_a_division():
    snap = {**SNAP, "invoices": [{"client_id": "5", "client_name": "Acme", "month": "2026-10", "revenue": 0, "invoices": 0}], "hours": []}
    assert p.profit_for_month(snap, [], "2026-10")["rows"][0]["margin_percent"] is None


def test_software_per_run_is_quantity_times_unit_cost_summed_per_client():
    halo = {
        "recurring": [
            {"client_name": "Acme Dental, Inc.", "lines": [{"qty": 10, "unit_cost": 2.5}, {"qty": 1, "unit_cost": 0}]},
            {"client_name": "acme dental inc", "lines": [{"qty": 2, "unit_cost": 10}]},
        ]
    }
    assert p.software_per_run(halo) == {"acmedentalinc": Decimal("45.00")}
    assert p.software_per_run(None) == {}


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
        await conn.execute(
            text("insert into tenants (id, name, slug) values (:i, 'profit-test', :s)"), {"i": tid, "s": f"pf-{tid.hex[:8]}"}
        )
    yield SimpleNamespace(id=tid, user=SimpleNamespace(tenant_id=tid, user_id=None, email="hal@goliveoak.com"))
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for table in ("finance_labor_rates", "finance_profit_snapshots", "finance_halo_snapshots"):
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
async def test_the_page_is_empty_until_core_sends_then_prices_hours_with_the_rates_the_owner_set(tenant):
    first = await with_db(tenant.id, lambda db: ep.profitability(tenant.user, db, None))
    assert first["received_at"] is None and first["report"] is None

    body = feed.ProfitSnapshotIn.model_validate(SNAP)

    async def ingest(db):
        # the route itself needs a CORE feed token; the stored row is what it writes
        from app.models.finance_profit import FinanceProfitSnapshot

        db.add(FinanceProfitSnapshot(tenant_id=tenant.id, payload=body.model_dump()))
        await db.commit()

    await with_db(tenant.id, ingest)
    req = SimpleNamespace(client=None, headers={})
    await with_db(
        tenant.id, lambda db: ep.save_labor_rate(ep.RateIn(scope="team", key="Support", hourly_rate=Decimal("100")), req, tenant.user, db)
    )
    await with_db(
        tenant.id, lambda db: ep.save_labor_rate(ep.RateIn(scope="agent", key="41", hourly_rate=Decimal("200")), req, tenant.user, db)
    )
    out = await with_db(tenant.id, lambda db: ep.profitability(tenant.user, db, "2026-10"))
    assert out["months"] == ["2026-09", "2026-10"] and out["report"]["month"] == "2026-10"
    assert out["report"]["rows"][0]["labor"] == Decimal("900.00")
    assert {(r["scope"], r["key"]) for r in out["rates"]} == {("team", "Support"), ("agent", "41")}

    await with_db(
        tenant.id, lambda db: ep.save_labor_rate(ep.RateIn(scope="team", key="Support", hourly_rate=Decimal("110")), req, tenant.user, db)
    )
    again = await with_db(tenant.id, lambda db: ep.profitability(tenant.user, db, "2026-10"))
    assert again["report"]["rows"][0]["labor"] == Decimal("940.00"), "saving the same team again replaced the rate"

    await with_db(tenant.id, lambda db: ep.delete_labor_rate(req, tenant.user, db, "team", "Support"))
    with pytest.raises(HTTPException) as gone:
        await with_db(tenant.id, lambda db: ep.delete_labor_rate(req, tenant.user, db, "team", "Support"))
    assert gone.value.status_code == 404
    with pytest.raises(HTTPException) as bad:
        await with_db(
            tenant.id, lambda db: ep.save_labor_rate(ep.RateIn(scope="agent", key=" ", hourly_rate=Decimal("5")), req, tenant.user, db)
        )
    assert bad.value.status_code == 422

    csv = await with_db(tenant.id, lambda db: ep.profitability_csv(tenant.user, db, "2026-10"))
    lines = csv.body.decode().splitlines()
    assert lines[0].startswith("Client,Revenue,Invoices,Hours,Labor cost") and lines[1].startswith(
        chr(34) + "Acme Dental, Inc." + chr(34) + ",1000.00,2,6.50,760.00,240.00"
    )
    with pytest.raises(HTTPException) as nothing:
        await with_db(tenant.id, lambda db: ep.profitability_csv(tenant.user, db, "2026-01"))
    assert nothing.value.status_code == 404

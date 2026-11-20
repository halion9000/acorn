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


LINES = {
    "rows": [
        {"month": "2026-10", "client_id": "5", "client_name": "Acme Dental, Inc.", "item": "Managed Services", "category": "Services", "quantity": 1, "amount": 800},
        {"month": "2026-10", "client_id": "5", "client_name": "Acme Dental, Inc.", "item": "ThreatMate (Included)", "category": "Software", "quantity": 25, "amount": 0},
        {"month": "2026-10", "client_id": "5", "client_name": "Acme Dental, Inc.", "item": "Microsoft 365", "category": "Software", "quantity": 20, "amount": 200},
        {"month": "2026-09", "client_id": "5", "client_name": "Acme Dental, Inc.", "item": "Last month only", "category": "Services", "quantity": 1, "amount": 900},
        {"month": "2026-10", "client_id": "6", "client_name": "Birch Law", "item": "Someone else's line", "category": "Services", "quantity": 1, "amount": 400.5},
    ]
}
HALO = {
    "recurring": [
        {"client_name": "Acme Dental Inc", "lines": [{"item": "ThreatMate (Included)", "qty": 25, "unit_price": 0, "unit_cost": 1.5}, {"item": "Microsoft 365", "qty": 20, "unit_price": 10, "unit_cost": 8}]},
        {"client_name": "Birch Law", "lines": [{"item": "Other", "qty": 1, "unit_price": 5, "unit_cost": 1}]},
    ]
}


def test_a_clients_breakdown_adds_up_to_its_row_and_names_the_billed_and_free_lines_the_hours_by_agent_and_the_rate_used():
    rates = [{"scope": "agent", "key": "40", "hourly_rate": "70.00"}]
    b = p.client_breakdown(SNAP, LINES, HALO, rates, "5", "2026-10")
    assert b is not None
    row = next(r for r in p.profit_for_month(SNAP, rates, "2026-10")["rows"] if r["client_id"] == "5")
    assert (b["revenue"], b["invoices"], b["hours"], b["labor"], b["after_labor"]) == (row["revenue"], row["invoices"], row["hours"], row["labor"], row["after_labor"]), "the same numbers as the row"
    assert [(ln["item"], ln["amount"], ln["free"]) for ln in b["invoice_lines"]] == [("Managed Services", 800, False), ("Microsoft 365", 200, False), ("ThreatMate (Included)", 0, True)]
    assert b["invoice_lines_total"] == 1000 and b["free_lines"] == 1, "the lines of this month and this client only"
    assert [(a["name"], a["hours"], a["rate"], a["rate_source"], a["cost"]) for a in b["by_agent"]] == [
        ("Dan Kemp", Decimal("4.00"), Decimal("70.00"), "agent", Decimal("280.00")),
        ("Vic Cio", Decimal("2.50"), Decimal("65.00"), "default", Decimal("162.50")),
    ]
    assert [(c["charge_type"], c["hours"]) for c in b["by_charge_type"]] == [("Remote Support", Decimal("4.00")), ("vCIO", Decimal("2.50"))]
    assert [(r["item"], r["free"], r["cost_per_run"]) for r in b["recurring"]] == [("Microsoft 365", False, 160.0), ("ThreatMate (Included)", True, 37.5)]
    assert b["tickets"] is None, "ticket detail is not collected yet and says so"


def test_a_client_not_invoiced_that_month_has_no_breakdown_and_an_agent_the_list_lacks_is_a_former_agent():
    assert p.client_breakdown(SNAP, LINES, HALO, [], "6", "2026-08") is None
    assert p.client_breakdown(SNAP, LINES, HALO, [], "99", "2026-10") is None
    snap = {**SNAP, "agents": [], "hours": [{"client": "Birch Law", "month": "2026-10", "agent_id": "93", "charge_type": "x", "hours": 1}]}
    b = p.client_breakdown(snap, None, None, [], "6", "2026-10")
    assert b is not None and b["by_agent"][0]["name"] == "Former agent 93"
    assert b["invoice_lines"] == [] and b["recurring"] == []


@needs_pg
@pytest.mark.asyncio
async def test_the_client_breakdown_endpoint_reads_this_organizations_snapshot_and_lines_and_refuses_what_is_not_there(tenant):
    from app.models.finance_profit import FinanceProfitSnapshot
    from app.models.metric_dataset import MetricDataset

    with pytest.raises(HTTPException) as none_yet:
        await with_db(tenant.id, lambda db: ep.profitability_client(tenant.user, db, "5", "2026-10"))
    assert none_yet.value.status_code == 404

    async def seed(db):
        db.add(FinanceProfitSnapshot(tenant_id=tenant.id, payload=feed.ProfitSnapshotIn.model_validate(SNAP).model_dump()))
        db.add(MetricDataset(tenant_id=tenant.id, key="invoice-lines", payload=LINES))
        await db.commit()

    await with_db(tenant.id, seed)
    out = await with_db(tenant.id, lambda db: ep.profitability_client(tenant.user, db, "5", "2026-10"))
    assert out["client_name"] == "Acme Dental, Inc." and out["revenue"] == Decimal("1000.00")
    assert [ln["item"] for ln in out["invoice_lines"]] == ["Managed Services", "Microsoft 365", "ThreatMate (Included)"]
    assert out["invoice_lines_received_at"] is not None and out["received_at"] is not None
    with pytest.raises(HTTPException) as other_month:
        await with_db(tenant.id, lambda db: ep.profitability_client(tenant.user, db, "5", "2026-01"))
    assert other_month.value.status_code == 404
    await with_db(tenant.id, lambda db: db.execute(text("delete from metric_datasets where tenant_id = :t"), {"t": tenant.id}))


def test_the_client_breakdown_route_accepts_a_real_month_and_the_per_client_month_pattern_is_not_a_literal_d():
    """The month check on the click-through route lost its backslashes once (^d{4}-d{2}$), so every real month answered 422. The published schema is what a caller is held to."""
    import re

    from app.main import app

    params = app.openapi()["paths"]["/api/v1/finance/profitability/client"]["get"]["parameters"]
    month = next(p for p in params if p["name"] == "month")
    pattern = month["schema"]["pattern"]
    assert re.fullmatch(pattern, "2026-11"), pattern
    assert not re.fullmatch(pattern, "dddd-dd") and not re.fullmatch(pattern, "2026-1")


def test_the_tickets_behind_a_clients_hours_are_listed_most_hours_first_with_who_worked_them_and_the_hours_not_on_a_listed_ticket():
    """Acme's October hours are 6.5: Dan 4.0 and Vic 2.5. CORE listed three tickets for 4.5 h (the most-worked); the other 2.0 h are on tickets it did not list."""
    tickets = [
        {"client": "Acme Dental, Inc.", "month": "2026-10", "ticket_id": "700", "summary": "Quarterly review", "hours": 2.5, "entries": 2, "agent_ids": ["41", "40"]},
        {"client": "Acme Dental Inc", "month": "2026-10", "ticket_id": "9", "summary": "Printer offline", "hours": 1.5, "entries": 1, "agent_ids": ["40"]},
        {"client": "Acme Dental, Inc.", "month": "2026-10", "ticket_id": "12", "summary": "VPN", "hours": 0.5, "entries": 1, "agent_ids": ["93"]},
        {"client": "Acme Dental, Inc.", "month": "2026-09", "ticket_id": "5", "summary": "Last month", "hours": 9, "entries": 1, "agent_ids": ["40"]},
        {"client": "Birch Law", "month": "2026-10", "ticket_id": "6", "summary": "Not Acme", "hours": 9, "entries": 1, "agent_ids": ["40"]},
    ]
    b = p.client_breakdown({**SNAP, "tickets": tickets}, LINES, HALO, [], "5", "2026-10")
    assert b is not None
    assert [(t["ticket_id"], t["summary"], t["hours"], t["entries"], t["agents"]) for t in b["tickets"]["rows"]] == [
        ("700", "Quarterly review", 2.5, 2, ["Vic Cio", "Dan Kemp"]),
        ("9", "Printer offline", 1.5, 1, ["Dan Kemp"]),
        ("12", "VPN", 0.5, 1, ["Former agent 93"]),
    ]
    assert b["tickets"]["other_hours"] == 2.0, "6.5 hours worked, 4.5 on the listed tickets"
    assert p.client_breakdown({**SNAP, "tickets": []}, LINES, HALO, [], "5", "2026-10")["tickets"] == {"rows": [], "other_hours": 6.5}
    assert p.client_breakdown({**SNAP, "tickets": None}, LINES, HALO, [], "5", "2026-10")["tickets"] is None, "an older CORE sends none: said so, not shown as zero"


def test_the_profitability_post_accepts_ticket_rows_and_an_older_core_without_them():
    from app.api.v1.endpoints.inbox_core_feed import ProfitSnapshotIn

    base = {"months": ["2026-10"], "invoices": [], "hours": [], "agents": []}
    assert ProfitSnapshotIn(**base).tickets is None
    with_rows = ProfitSnapshotIn(**base, tickets=[{"client": "Acme", "month": "2026-10", "ticket_id": "700", "summary": "x", "hours": 1.5, "entries": 2, "agent_ids": ["40"]}])
    assert with_rows.tickets[0].ticket_id == "700"
    with pytest.raises(ValueError):
        ProfitSnapshotIn(**base, tickets=[{"client": "Acme", "month": "2026-10", "ticket_id": "abc", "hours": 1}])


def test_the_tickets_of_the_month_sent_on_their_own_route_are_the_ones_listed_and_a_month_with_none_sent_says_so():
    month_rows = [
        {"client": "Acme Dental, Inc.", "month": "2026-10", "ticket_id": "700", "summary": "Quarterly review", "hours": 2.5, "entries": 2, "agent_ids": ["41", "40"]},
        {"client": "Acme Dental, Inc.", "month": "2026-10", "ticket_id": "9", "summary": "Printer offline", "hours": 4.0, "entries": 3, "agent_ids": ["40"]},
        {"client": "Birch Law", "month": "2026-10", "ticket_id": "6", "summary": "Not Acme", "hours": 9, "entries": 1, "agent_ids": ["40"]},
    ]
    old = [{"client": "Acme Dental, Inc.", "month": "2026-10", "ticket_id": "1", "summary": "From the summary", "hours": 1, "entries": 1, "agent_ids": ["40"]}]
    b = p.client_breakdown({**SNAP, "tickets": old}, LINES, HALO, [], "5", "2026-10", month_rows)
    assert [t["ticket_id"] for t in b["tickets"]["rows"]] == ["9", "700"], "the month's own rows win over any in the summary, most hours first"
    assert b["tickets"]["other_hours"] == 0.0, "all 6.5 hours are on listed tickets now"
    assert p.client_breakdown(SNAP, LINES, HALO, [], "5", "2026-10", [])["tickets"] == {"rows": [], "other_hours": 6.5}
    assert p.client_breakdown(SNAP, LINES, HALO, [], "5", "2026-10", None)["tickets"] is None, "nothing sent for the month and none in the summary: said so"


def test_a_clients_every_ticket_is_listed_however_many_there_are():
    rows = [{"client": "Acme Dental, Inc.", "month": "2026-10", "ticket_id": str(1000 + i), "summary": f"T{i}", "hours": 0.01, "entries": 1, "agent_ids": ["40"]} for i in range(250)]
    b = p.client_breakdown(SNAP, LINES, HALO, [], "5", "2026-10", rows)
    assert len(b["tickets"]["rows"]) == 250


def test_the_trend_prices_every_month_the_way_the_month_view_does_and_lists_each_client_by_month():
    t = p.profit_trend(SNAP, [], 12)
    assert t["months"] == ["2026-09", "2026-10"] and t["available_months"] == 2
    sep, octo = t["series"]
    assert (sep["revenue"], sep["labor"], sep["after_labor"], sep["clients_invoiced"]) == (Decimal("900"), Decimal("650.00"), Decimal("250.00"), 1)
    one = p.profit_for_month(SNAP, [], "2026-10")["totals"]
    assert (octo["revenue"], octo["labor"], octo["margin_percent"], octo["hours"]) == (one["revenue"], one["labor"], one["margin_percent"], one["hours"]), "the same totals as the month view"
    assert octo["clients_invoiced"] == 2
    acme, birch = t["clients"]
    assert acme["client_name"] == "Acme Dental, Inc." and acme["revenue"] == Decimal("1900") and set(acme["by_month"]) == {"2026-09", "2026-10"}
    assert birch["by_month"] == {"2026-10": {"revenue": Decimal("400.5"), "labor": Decimal("65.00"), "after_labor": Decimal("335.50")}}


def test_the_trend_takes_only_the_newest_months_and_only_the_top_clients():
    t = p.profit_trend(SNAP, [], 1, top=1)
    assert t["months"] == ["2026-10"] and [c["client_name"] for c in t["clients"]] == ["Acme Dental, Inc."] and t["clients_left_out"] == 1
    assert p.profit_trend({}, [], 6) == {"months": [], "available_months": 0, "series": [], "clients": [], "clients_left_out": 0}

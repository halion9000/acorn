"""The full profitability model: revenue to net income per client (shared costs spread to the cent), new clients, by industry, hours and utilization, the twelve-month ranking, and the inputs' endpoints.

The arithmetic first (pure, numbers worked out by hand), then the endpoints against a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).
"""

import os
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import finance as ep
from app.db.rls import set_rls_context
from app.models.finance_profit import FinanceProfitSnapshot
from app.services import profitability_full as pf
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

D = Decimal

SNAP = {
    "months": ["2026-09", "2026-10"],
    "invoices": [
        {"client_id": "5", "client_name": "Acme Dental, Inc.", "month": "2026-10", "revenue": 1000, "invoices": 2},
        {"client_id": "6", "client_name": "Birch Law", "month": "2026-10", "revenue": 400.5, "invoices": 1},
        {"client_id": "5", "client_name": "Acme Dental, Inc.", "month": "2026-09", "revenue": 900, "invoices": 1},
    ],
    "hours": [
        {"client": "Acme Dental, Inc.", "month": "2026-10", "agent_id": "40", "charge_type": "Remote Support", "hours": 4},
        {"client": "Acme Dental, Inc.", "month": "2026-10", "agent_id": "41", "charge_type": "vCIO", "hours": 2.5},
        {"client": "Birch Law", "month": "2026-10", "agent_id": "40", "charge_type": "Remote Support", "hours": 1},
        {"client": "Nobody Invoiced LLC", "month": "2026-10", "agent_id": "40", "charge_type": "No Charge", "hours": 3},
        {"client": "Acme Dental, Inc.", "month": "2026-09", "agent_id": "40", "charge_type": "Remote Support", "hours": 10},
    ],
    "agents": [{"id": "40", "name": "Dan Kemp", "team": "Support"}, {"id": "41", "name": "Vic Cio", "team": "vCIO"}],
}


def cost(category, amount, client="", month="2026-10"):
    return {"month": month, "category": category, "client_key": pf.name_key(client), "client_name": client, "amount": D(amount)}


COSTS = [
    cost("payroll_cogs", "600"),
    cost("travel", "50", "Acme Dental, Inc."),
    cost("hardware", "140.05"),
    cost("sales_marketing", "300"),
    cost("overhead", "140.05"),
]
MASTER = {
    "acmedentalinc": {"industry": "Dental", "non_profit": False, "target_margin": D("25")},
    "birchlaw": {"industry": "Legal", "non_profit": True, "target_margin": None},
}


def test_spreading_adds_up_to_exactly_the_amount_whatever_the_weights():
    out = pf.spread(D("100.00"), {"a": D(1), "b": D(1), "c": D(1)})
    assert sum(out.values()) == D("100.00") and sorted(out.values()) == [D("33.33"), D("33.33"), D("33.34")]
    assert pf.spread(D("-0.01"), {"a": D(1), "b": D(1)}) and sum(pf.spread(D("-0.01"), {"a": D(1), "b": D(1)}).values()) == D("-0.01")
    assert pf.spread(D("5"), {}) == {} and pf.spread(D("5"), {"a": D(0)}) == {} and pf.spread(D("0"), {"a": D(1)}) == {}


def test_revenue_to_net_income_per_client_with_direct_and_shared_costs():
    r = pf.full_month(SNAP, [], "2026-10", COSTS, MASTER)
    acme, birch = r["rows"]
    # Acme: labor 4h + 2.5h at the 65.00 default = 422.50; payroll true-up (600 - 487.50 direct) = 112.50 split 80.33 / 32.17 by revenue; travel is Acme's own; hardware and overhead split 100.00 / 40.05
    assert (acme["direct_labor"], acme["labor_trueup"], acme["travel"], acme["hardware"]) == (
        D("422.50"),
        D("80.33"),
        D("50.00"),
        D("100.00"),
    )
    assert (acme["total_cost"], acme["gross_profit"], acme["overhead"], acme["net_income"]) == (
        D("652.83"),
        D("347.17"),
        D("100.00"),
        D("247.17"),
    )
    assert (acme["gross_margin"], acme["net_margin"], acme["sales_marketing"], acme["new_client"]) == (34.7, 24.7, D("0.00"), False)
    # Birch Law is new this month, so it carries the whole sales and marketing cost, and loses money
    assert (birch["direct_labor"], birch["labor_trueup"], birch["hardware"], birch["sales_marketing"], birch["overhead"]) == (
        D("65.00"),
        D("32.17"),
        D("40.05"),
        D("300.00"),
        D("40.05"),
    )
    assert (birch["net_income"], birch["net_margin"], birch["new_client"]) == (D("-76.77"), -19.2, True)


def test_the_shared_parts_add_up_to_what_was_entered():
    r = pf.full_month(SNAP, [], "2026-10", COSTS, MASTER)
    t = r["totals"]
    assert t["revenue"] == D("1400.50")
    assert (
        sum(x["labor_trueup"] for x in r["rows"]) == D("600") - t["direct_labor"]
    ), "the true-up is the payroll minus what the hours priced"
    assert sum(x["hardware"] for x in r["rows"]) == D("140.05") and sum(x["overhead"] for x in r["rows"]) == D("140.05")
    assert sum(x["sales_marketing"] for x in r["rows"]) == D("300.00") and t["sales_marketing"] == D("300.00")
    assert t["net_income"] == t["revenue"] - t["total_cost"] - t["sales_marketing"] - t["overhead"]
    assert r["unplaced"] == {}


def test_what_has_not_been_entered_is_zero_and_named_not_guessed():
    r = pf.full_month(SNAP, [], "2026-10", COSTS, MASTER)
    assert r["missing"] == ["addon_software", "support_software", "equipment"]
    empty = pf.full_month(SNAP, [], "2026-10", [], {})
    assert empty["missing"] == list(pf.CATEGORIES)
    assert (
        empty["totals"]["labor_trueup"] == D("0.00")
        and empty["totals"]["net_income"] == empty["totals"]["revenue"] - empty["totals"]["direct_labor"]
    )


def test_new_clients_are_those_whose_first_revenue_is_the_month_and_never_the_oldest_month_in_the_summary():
    assert [c["client_name"] for c in pf.full_month(SNAP, [], "2026-10", [], {})["new_clients"]] == ["Birch Law"]
    assert pf.full_month(SNAP, [], "2026-09", [], {})["new_clients"] == [], "the first month cannot tell new from existing"


def test_an_amount_with_nobody_to_carry_it_is_reported_as_unplaced_not_lost():
    r = pf.full_month(
        {"months": ["2026-10"], "invoices": [], "hours": [], "agents": []},
        [],
        "2026-10",
        [cost("overhead", "10"), cost("sales_marketing", "5")],
        {},
    )
    assert r["rows"] == [] and r["unplaced"] == {"overhead": D("10.00"), "sales_marketing": D("5.00")}


def test_a_cost_charged_to_a_client_with_no_revenue_this_month_still_shows_as_a_loss():
    r = pf.full_month(SNAP, [], "2026-10", [cost("travel", "30", "Quiet Co")], {})
    quiet = next(x for x in r["rows"] if x["client_name"] == "Quiet Co")
    assert (quiet["revenue"], quiet["travel"], quiet["net_income"], quiet["net_margin"]) == (D("0.00"), D("30.00"), D("-30.00"), None)


def test_by_industry_groups_the_month_and_says_unassigned_for_a_client_with_no_master_row():
    r = pf.full_month(SNAP, [], "2026-10", COSTS, {"acmedentalinc": MASTER["acmedentalinc"]})
    groups = pf.by_industry(r)
    assert [(g["industry"], g["clients"], g["revenue"]) for g in groups] == [("Dental", 1, D("1000.00")), ("Unassigned", 1, D("400.50"))]
    assert groups[0]["net_income"] == D("247.17") and groups[0]["net_margin"] == 24.7
    both = pf.by_industry(pf.full_month(SNAP, [], "2026-10", COSTS, MASTER))
    assert next(g for g in both if g["industry"] == "Legal")["non_profit_clients"] == 1


def test_hours_by_function_and_utilization_count_no_charge_as_not_billable():
    h = pf.hours_report(SNAP, [], "2026-10", D("160"))
    assert h["total_hours"] == D("10.50")
    by = {f["function"]: f for f in h["by_function"]}
    assert (by["Remote Support"]["hours"], by["Remote Support"]["cost"], by["Remote Support"]["share_percent"]) == (
        D("5.00"),
        D("325.00"),
        47.6,
    )
    assert by["No Charge"]["billable"] is False and by["vCIO"]["billable"] is True
    dan, vic = h["by_person"]
    assert (dan["name"], dan["hours"], dan["billable_hours"], dan["utilization_percent"]) == ("Dan Kemp", D("8.00"), D("5.00"), 3.1)
    assert (vic["hours"], vic["utilization_percent"]) == (D("2.50"), 1.6)


def test_the_twelve_month_ranking_orders_by_net_income_and_flags_the_target():
    a = pf.annual(SNAP, [], COSTS, MASTER, "2026-10")
    assert a["months"] == ["2026-09", "2026-10"]
    acme, birch = a["rows"]
    assert (acme["rank"], acme["tier"], acme["net_income"], acme["revenue"], acme["net_margin"]) == (
        1,
        "Top 20",
        D("497.17"),
        D("1900.00"),
        26.2,
    )
    assert (acme["target_margin"], acme["meets_target"]) == (25.0, True), "the client master's own target applies"
    assert (birch["rank"], birch["target_margin"], birch["meets_target"], birch["bottom_20"]) == (2, 20.0, False, False)


def test_the_ranking_marks_tiers_and_the_bottom_twenty_once_there_are_more_than_twenty_clients():
    months = ["2026-09", "2026-10"]
    invoices = [
        {"client_id": str(i), "client_name": f"Client {i:03d}", "month": "2026-10", "revenue": 1000 - i, "invoices": 1}
        for i in range(1, 46)
    ]
    a = pf.annual({"months": months, "invoices": invoices, "hours": [], "agents": []}, [], [], {}, "2026-10")
    rows = a["rows"]
    assert rows[0]["tier"] == "Top 20" and rows[19]["tier"] == "Top 20" and rows[20]["tier"] == "Top 40" and rows[44]["tier"] == "Top 60"
    assert [r["rank"] for r in rows if r["bottom_20"]] == list(range(26, 46))
    assert all(r["meets_target"] for r in rows), "no costs entered, so every client keeps its whole revenue"


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
            text("insert into tenants (id, name, slug) values (:i, 'profit-full-test', :s)"), {"i": tid, "s": f"pff-{tid.hex[:8]}"}
        )
    yield SimpleNamespace(id=tid, user=SimpleNamespace(tenant_id=tid, user_id=None, email="hal@goliveoak.com"))
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for table in (
            "finance_cost_entries",
            "finance_client_master",
            "finance_settings",
            "finance_labor_rates",
            "finance_profit_snapshots",
        ):
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
async def test_inputs_typed_on_the_page_change_the_analysis_and_replace_rather_than_pile_up(tenant):
    req = SimpleNamespace(client=None, headers={})
    empty = await with_db(tenant.id, lambda db: ep.profitability_analysis(tenant.user, db, None))
    assert empty["received_at"] is None and empty["report"] is None and empty["annual"] is None

    async def ingest(db):
        db.add(FinanceProfitSnapshot(tenant_id=tenant.id, payload=SNAP))
        await db.commit()

    await with_db(tenant.id, ingest)
    for body in (
        ep.CostIn(month="2026-10", category="payroll_cogs", amount=D("600")),
        ep.CostIn(month="2026-10", category="travel", client_name="Acme Dental, Inc.", amount=D("50")),
        ep.CostIn(month="2026-10", category="overhead", client_name="Ignored Name", amount=D("100")),
    ):
        await with_db(tenant.id, lambda db, b=body: ep.save_cost(b, req, tenant.user, db))
    await with_db(
        tenant.id,
        lambda db: ep.save_client_master(
            ep.ClientMasterIn(client_name="Acme Dental, Inc.", industry=" Dental ", target_margin=D("25")), req, tenant.user, db
        ),
    )
    out = await with_db(tenant.id, lambda db: ep.profitability_analysis(tenant.user, db, "2026-10"))
    acme = out["report"]["rows"][0]
    assert (acme["travel"], acme["industry"], acme["labor_trueup"]) == (D("50.00"), "Dental", D("80.33"))
    assert out["report"]["missing"] == ["addon_software", "support_software", "equipment", "hardware", "sales_marketing"]
    assert out["industries"][0]["industry"] == "Dental" and out["annual"]["rows"][0]["rank"] == 1

    await with_db(
        tenant.id,
        lambda db: ep.save_cost(
            ep.CostIn(month="2026-10", category="travel", client_name="acme dental inc", amount=D("75")), req, tenant.user, db
        ),
    )
    inputs = await with_db(tenant.id, lambda db: ep.profitability_inputs(tenant.user, db))
    travel = [c for c in inputs["costs"] if c["category"] == "travel"]
    assert [c["amount"] for c in travel] == [D("75.00")], "saving the same month, category and client again replaced the amount"
    overhead = next(c for c in inputs["costs"] if c["category"] == "overhead")
    assert overhead["client_key"] == "" and overhead["client_name"] == "", "a company-wide category is never tied to a client"
    assert inputs["master"][0]["industry"] == "Dental" and inputs["available_hours_per_month"] == D("160")

    await with_db(tenant.id, lambda db: ep.save_finance_settings(ep.SettingsIn(available_hours_per_month=D("120")), req, tenant.user, db))
    hours = (await with_db(tenant.id, lambda db: ep.profitability_analysis(tenant.user, db, "2026-10")))["hours"]
    assert hours["available_hours_per_person"] == D("120.00") and hours["by_person"][0]["utilization_percent"] == 4.2

    await with_db(tenant.id, lambda db: ep.delete_cost(req, tenant.user, db, "2026-10", "travel", "Acme Dental, Inc."))
    with pytest.raises(HTTPException) as gone:
        await with_db(tenant.id, lambda db: ep.delete_cost(req, tenant.user, db, "2026-10", "travel", "Acme Dental, Inc."))
    assert gone.value.status_code == 404
    await with_db(tenant.id, lambda db: ep.delete_client_master(req, tenant.user, db, "Acme Dental, Inc."))
    with pytest.raises(HTTPException) as none_left:
        await with_db(tenant.id, lambda db: ep.delete_client_master(req, tenant.user, db, "Acme Dental, Inc."))
    assert none_left.value.status_code == 404
    with pytest.raises(HTTPException) as bad:
        await with_db(tenant.id, lambda db: ep.save_client_master(ep.ClientMasterIn(client_name="!!!"), req, tenant.user, db))
    assert bad.value.status_code == 422

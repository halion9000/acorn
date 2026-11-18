"""QuickBooks' P&L lines, sales by customer and customer groups on a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable, fully migrated database; migration 218 applied).

CORE posts the profit and loss and the sales by customer; a person groups customers under clients; the pages read them back, one organization never sees another's.
"""

import os
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import finance as fin
from app.api.v1.endpoints import inbox_core_feed as feed
from app.db.rls import set_rls_context
from app.models.finance_profit import FinanceProfitSnapshot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"),
]
SNAP = {
    "months": ["2026-09", "2026-10"],
    "invoices": [{"client_id": "5", "client_name": "Halo Only", "month": "2026-10", "revenue": 1, "invoices": 1}],
    "hours": [{"month": "2026-10", "client": "Acme Dental", "agent_id": "9", "hours": 10}],
    "agents": [{"id": "9", "name": "Pat"}],
}


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    async def noop(**_kw):
        return None

    monkeypatch.setattr(fin, "emit_audit", noop)


@pytest.fixture
async def world(monkeypatch):
    a, b = uuid.uuid4(), uuid.uuid4()
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for tid, name in ((a, "Live Oak A"), (b, "Live Oak B")):
                await conn.execute(text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"), {"i": tid, "n": name, "s": f"qb-{tid.hex[:10]}"})
        tokens = {"tok-a": a, "tok-b": b}

        async def verify(db, token):
            return tokens[token]

        monkeypatch.setattr(feed, "_verify_core_feed_token", verify)
        yield SimpleNamespace(a=a, b=b)
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for table in ("finance_pnl_months", "finance_cost_transactions", "finance_qbo_sales", "finance_client_groups", "finance_profit_snapshots"):
                await conn.execute(text(f"delete from {table} where tenant_id = any(:ids)"), {"ids": [a, b]})
            await conn.execute(text("delete from tenants where id = any(:ids)"), {"ids": [a, b]})
        await owner.dispose()


async def with_db(tid, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            return await work(db)
    finally:
        await engine.dispose()


def user(tid):
    return SimpleNamespace(tenant_id=tid, user_id=None, email="hal@x")


def pnl(month, income):
    return feed.PnlMonthIn(
        month=month,
        lines=[feed.PnlLineIn(depth=0, kind="header", label="Income"), feed.PnlLineIn(depth=1, kind="line", label="4000 Managed Service Revenue", amount=income), feed.PnlLineIn(depth=0, kind="total", label="Total Income", amount=income)],
    )


def sales(month, *customers):
    return feed.QboSalesMonthIn(month=month, customers=[feed.QboCustomerIn(name=n, amount=a) for n, a in customers])


async def test_the_pnl_is_kept_per_month_replaced_when_sent_again_and_private_to_its_organization(world):
    w = world
    out = await with_db(w.a, lambda db: feed.report_core_feed_pnl("tok-a", feed.PnlIn(months=[pnl("2026-08", 100.0), pnl("2026-09", 200.0), pnl("2026-10", 300.0)]), db))
    assert (out.months, out.lines) == (3, 9)
    await with_db(w.a, lambda db: feed.report_core_feed_pnl("tok-a", feed.PnlIn(months=[pnl("2026-09", 250.5)]), db))
    got = await with_db(w.a, lambda db: fin.profit_and_loss(user(w.a), db, "2026-09"))
    assert got["months"] == ["2026-08", "2026-09", "2026-10"] and got["month"] == "2026-09"
    assert [(ln["depth"], ln["kind"], ln["label"], ln["amount"]) for ln in got["lines"]] == [(0, "header", "Income", None), (1, "line", "4000 Managed Service Revenue", 250.5), (0, "total", "Total Income", 250.5)]
    assert (await with_db(w.a, lambda db: fin.profit_and_loss(user(w.a), db, "2026-08")))["lines"][1]["amount"] == 100.0, "a month not sent again stayed"
    assert (await with_db(w.a, lambda db: fin.profit_and_loss(user(w.a), db, None)))["month"] == "2026-09", "the newest complete month by default"
    other = await with_db(w.b, lambda db: fin.profit_and_loss(user(w.b), db, None))
    assert other["months"] == [] and other["lines"] == [], "another organization sees none of it"


async def test_sales_by_customer_are_grouped_into_clients_with_a_typed_group_and_the_profit_table_uses_the_booked_revenue(world):
    w = world
    sent = await with_db(w.a, lambda db: feed.report_core_feed_qbo_sales("tok-a", feed.QboSalesIn(months=[sales("2026-09", ("Acme Dental", 100), ("Acme Annex", 50), ("Sandler Corp", 40)), sales("2026-10", ("Acme Dental", 120), ("Acme Dental", 10), ("Zero", 0))]), db))
    assert (sent.months, sent.customers) == (2, 4), "two lines for one customer are one, and a zero is dropped"
    req = SimpleNamespace(client=None, headers={})
    saved = await with_db(w.a, lambda db: fin.import_client_groups(fin.GroupsImportIn(rows=[fin.GroupRowIn(name="Acme Annex", primary="Acme Dental"), fin.GroupRowIn(name="Sandler Corp", primary="Commissions")]), req, user(w.a), db))
    assert saved["saved"] == 2 and saved["removed"] == 0
    hist = await with_db(w.a, lambda db: fin.qbo_history(user(w.a), db))
    assert hist["months"] == ["2026-09", "2026-10"]
    acme = next(c for c in hist["clients"] if c["client"] == "Acme Dental")
    assert acme["total"] == Decimal("280") and acme["by_month"] == {"2026-09": Decimal("150"), "2026-10": Decimal("130")} and acme["qbo_names"] == ["Acme Annex", "Acme Dental"]
    assert [c["client"] for c in hist["clients"]] == ["Acme Dental", "Commissions"]

    async def ingest(db):
        db.add(FinanceProfitSnapshot(tenant_id=w.a, payload=SNAP))
        await db.commit()

    await with_db(w.a, ingest)
    prof = await with_db(w.a, lambda db: fin.qbo_profitability(user(w.a), db, "2026-10"))
    rep = prof["report"]
    assert rep["month"] == "2026-10" and [r["client_name"] for r in rep["rows"]] == ["Acme Dental"], "Halo's invoice is not used and commissions are not a client"
    row = rep["rows"][0]
    assert row["revenue"] == Decimal("130") and row["hours"] == Decimal("10.00") and row["months_active"] == 2
    names = await with_db(w.a, lambda db: fin.client_names(user(w.a), db))
    by = {n["name"]: n["group"] for n in names["names"]}
    assert by["Acme Annex"] == "Acme Dental" and by["Sandler Corp"] == "Commissions" and by["Halo Only"] is None
    assert {"Acme Dental", "Halo Only"} <= set(by), "the names come from HaloPSA (invoices, hours) and QuickBooks (sales by customer)"
    empty = await with_db(w.b, lambda db: fin.qbo_profitability(user(w.b), db, None))
    assert empty["report"] is None and empty["months"] == []


async def test_the_client_summary_covers_the_last_months_with_year_to_date_and_is_private_to_the_organization(world):
    w = world
    snap = {
        "months": ["2026-08", "2026-09", "2026-10"],
        "invoices": [
            {"client_id": "5", "client_name": "Acme Dental", "month": "2026-09", "revenue": 1000, "invoices": 1},
            {"client_id": "5", "client_name": "Acme Dental", "month": "2026-10", "revenue": 1200, "invoices": 1},
            {"client_id": "6", "client_name": "Birch Law", "month": "2026-10", "revenue": 300, "invoices": 1},
        ],
        "hours": [{"month": "2026-10", "client": "Acme Dental", "agent_id": "9", "hours": 4}],
        "agents": [{"id": "9", "name": "Pat"}],
    }

    async def ingest(db):
        db.add(FinanceProfitSnapshot(tenant_id=w.a, payload=snap))
        await db.commit()

    await with_db(w.a, ingest)
    out = await with_db(w.a, lambda db: fin.profitability_summary(user(w.a), db, "2026-10"))
    assert out["through"] == "2026-10" and out["months"] == ["2026-08", "2026-09", "2026-10"] and out["available"] == ["2026-08", "2026-09", "2026-10"]
    by = {r["client_name"]: r for r in out["rows"]}
    assert by["Acme Dental"]["ytd_revenue"] == Decimal("2200") and by["Acme Dental"]["months_active"] == 2
    assert by["Birch Law"]["ytd_revenue"] == Decimal("300") and set(by["Birch Law"]["by_month"]) == {"2026-10"}
    assert by["Acme Dental"]["bracket"] in ("20% to 29%", "30% to 39%", "40% and over", "10% to 19%", "0% to 9%", "Not profitable")
    default = await with_db(w.a, lambda db: fin.profitability_summary(user(w.a), db, None))
    assert default["through"] == "2026-09", "the newest complete month when none is asked for"
    other = await with_db(w.b, lambda db: fin.profitability_summary(user(w.b), db, None))
    assert other == {"received_at": None, "months": [], "through": None, "rows": []}


def tx(account, date, name, customer, amount, memo="m", split="Ramp Card", type_="Expense"):
    return feed.CostTransactionIn(account=account, date=date, type=type_, name=name, customer=customer, memo=memo, split=split, amount=amount)


async def test_travel_and_hardware_transactions_are_kept_per_month_grouped_under_clients_and_private(world):
    w = world
    sent = await with_db(w.a, lambda db: feed.report_core_feed_cost_transactions("tok-a", feed.CostTransactionsIn(months=[
        feed.CostTransactionsMonthIn(month="2026-09", rows=[tx("5805", "2026-09-02", "Urban Bird", "Live Oak IT Partners", 23.4), tx("5800", "2026-09-03", "Hotel", "Acme Annex", 200), tx("5600", "2026-09-04", "Starlink", "Acme Dental", 399.4), tx("5600", "2026-09-05", "Zero", "Acme Dental", 0), tx("5600", "2026-08-31", "Wrong month", "Acme Dental", 5)]),
        feed.CostTransactionsMonthIn(month="2026-10", rows=[tx("5805", "2026-10-01", "Gas", "", 40)]),
    ]), db))
    assert (sent.months, sent.rows) == (2, 4), "a zero amount and a transaction dated outside its month are left out"
    await with_db(w.a, lambda db: fin.import_client_groups(fin.GroupsImportIn(rows=[fin.GroupRowIn(name="Acme Annex", primary="Acme Dental")]), SimpleNamespace(client=None, headers={}), user(w.a), db))
    travel = await with_db(w.a, lambda db: fin.cost_transactions(user(w.a), db, "travel", "2026-09"))
    assert travel["months"] == ["2026-09", "2026-10"] and travel["month"] == "2026-09" and travel["kind"] == "travel"
    assert [(r["date"], r["name"], r["client"]) for r in travel["rows"]] == [("2026-09-02", "Urban Bird", "Live Oak IT Partners"), ("2026-09-03", "Hotel", "Acme Dental")], "travel is 5800 and 5805, and a customer is counted under its client group"
    assert [(c["client"], c["total"]) for c in travel["by_client"]] == [("Acme Dental", Decimal("200")), ("Live Oak IT Partners", Decimal("23.4"))] and travel["total"] == Decimal("223.4")
    hardware = await with_db(w.a, lambda db: fin.cost_transactions(user(w.a), db, "hardware", None))
    assert hardware["month"] == "2026-10" and hardware["rows"] == [] and hardware["total"] == 0, "the newest month held, and none of its transactions are hardware"
    replaced = await with_db(w.a, lambda db: feed.report_core_feed_cost_transactions("tok-a", feed.CostTransactionsIn(months=[feed.CostTransactionsMonthIn(month="2026-09", rows=[tx("5600", "2026-09-09", "New", "X", 10)])]), db))
    assert replaced.rows == 1
    after = await with_db(w.a, lambda db: fin.cost_transactions(user(w.a), db, "travel", "2026-09"))
    assert after["rows"] == [], "September was replaced"
    october = await with_db(w.a, lambda db: fin.cost_transactions(user(w.a), db, "travel", "2026-10"))
    assert october["rows"][0]["client"] == "" and [c["client"] for c in october["by_client"]] == ["(no customer)"], "a transaction with no customer is listed under that label"
    other = await with_db(w.b, lambda db: fin.cost_transactions(user(w.b), db, "travel", None))
    assert other["months"] == [] and other["rows"] == []


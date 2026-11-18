"""QuickBooks sales by customer grouped into clients, and the snapshot the QBO profitability table is built on (pure)."""

from decimal import Decimal

from app.services import qbo_books as qb
from app.services.profitability import name_key

D = Decimal
SALES = {
    "2026-08": [{"name": "Acme Dental", "amount": 100}, {"name": "Acme Dental - Annex", "amount": 50}, {"name": "Sandler Corp", "amount": 40}, {"name": "Zero Co", "amount": 0}],
    "2026-09": [{"name": "Acme Dental", "amount": 120}, {"name": "Birch Law", "amount": 70.5}],
}
GROUPS = {"Acme Dental - Annex": "Acme Dental", "Sandler Corp": "Commissions"}


def test_a_customer_is_counted_under_its_typed_group_else_its_own_name_and_names_match_loosely():
    g = qb.key_groups(GROUPS)
    assert qb.group_name("Acme Dental - Annex", g) == "Acme Dental"
    assert qb.group_name("  acme   dental - ANNEX ", g) == "Acme Dental", "case and spacing do not matter"
    assert qb.group_name("Birch Law", g) == "Birch Law"


def test_history_lists_each_month_customer_and_amount_with_its_client_and_skips_zero_amounts():
    rows = qb.history_rows(SALES, GROUPS)
    assert [(r["month"], r["qbo_name"], r["group"], r["total"]) for r in rows] == [
        ("2026-08", "Acme Dental", "Acme Dental", D("100")),
        ("2026-08", "Acme Dental - Annex", "Acme Dental", D("50")),
        ("2026-08", "Sandler Corp", "Commissions", D("40")),
        ("2026-09", "Acme Dental", "Acme Dental", D("120")),
        ("2026-09", "Birch Law", "Birch Law", D("70.5")),
    ]


def test_the_pivot_adds_customers_of_one_client_per_month_and_orders_clients_by_total():
    p = qb.pivot(qb.history_rows(SALES, GROUPS))
    assert p["months"] == ["2026-08", "2026-09"]
    first = p["clients"][0]
    assert first["client"] == "Acme Dental" and first["total"] == D("270") and first["by_month"] == {"2026-08": D("150"), "2026-09": D("120")}
    assert first["qbo_names"] == ["Acme Dental", "Acme Dental - Annex"]
    assert [c["client"] for c in p["clients"]] == ["Acme Dental", "Birch Law", "Commissions"]


def test_the_profit_snapshot_replaces_invoices_with_booked_revenue_per_client_and_leaves_commissions_out():
    snap = {"months": ["2026-07"], "hours": [{"x": 1}], "agents": [{"id": "1"}], "invoices": [{"month": "2026-07", "client_name": "Old", "revenue": 9}]}
    out = qb.profit_snapshot(snap, SALES, GROUPS)
    assert out["hours"] == snap["hours"] and out["agents"] == snap["agents"], "hours and agents are kept"
    assert out["months"] == ["2026-08", "2026-09"]
    assert [(i["month"], i["client_name"], i["revenue"]) for i in out["invoices"]] == [("2026-08", "Acme Dental", 150.0), ("2026-09", "Acme Dental", 120.0), ("2026-09", "Birch Law", 70.5)]
    assert all(i["client_id"] == f"qbo:{name_key(i['client_name'])}" for i in out["invoices"])
    assert snap["invoices"][0]["client_name"] == "Old", "the input is not changed"


def test_months_active_counts_months_with_revenue_up_to_the_month_asked_for():
    a = qb.months_active(SALES, GROUPS, "2026-09")
    assert a[name_key("Acme Dental")] == 2 and a[name_key("Birch Law")] == 1
    assert qb.months_active(SALES, GROUPS, "2026-08")[name_key("Acme Dental")] == 1
    assert name_key("Zero Co") not in a

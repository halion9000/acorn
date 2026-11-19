from app.services.finance_forecast import forecast


def rec(cid, name, *lines):
    return {"client_id": cid, "client_name": name, "lines": [{"item": i, "qty": q, "unit_price": p, "unit_cost": c} for i, q, p, c in lines]}


SNAP = {
    "recurring": [
        rec("1", "Acme", ("Huntress", 10, 5, 3), ("Managed users", 20, 100, 40), ("Setup fee", 1, 50, 0)),
        rec("1", "Acme", ("Backup", 4, 10, 4)),
        rec("2", "Birch", ("Huntress", 5, 5, 2)),
    ]
}


def row(out, name):
    return next(r for r in out["clients"] if r["client_name"] == name)


def test_with_nothing_counted_differently_the_forecast_equals_today():
    out = forecast(SNAP, {})
    a = row(out, "Acme")
    assert a["revenue_now"] == a["revenue_forecast"] == "2140.00"
    assert a["margin_percent_now"] == a["margin_percent_forecast"]
    assert a["changed_lines"] == [] and a["lines_without_cost"] == ["Setup fee"]


def test_a_counted_quantity_replaces_the_billed_one_in_revenue_cost_and_margin_and_the_change_is_listed():
    out = forecast(SNAP, {("1", "Huntress"): 14, ("1", "Managed users"): 18})
    a = row(out, "Acme")
    # revenue: Huntress 14x5=70, users 18x100=1800, setup 50, backup 40 = 1960 (was 50+2000+50+40 = 2140)
    assert a["revenue_now"] == "2140.00" and a["revenue_forecast"] == "1960.00" and a["revenue_change"] == "-180.00"
    assert [(c["item"], c["billed"], c["counted"], c["revenue_change"]) for c in a["changed_lines"]] == [("Huntress", 10, 14, "20.00"), ("Managed users", 20, 18, "-200.00")]
    assert a["margin_percent_forecast"] != a["margin_percent_now"]
    assert row(out, "Birch")["changed_lines"] == [], "another client is not touched by a count for client 1"
    assert out["totals"]["clients_with_changes"] == 1


def test_the_count_belongs_to_one_client_and_one_line_and_clients_sort_by_forecast_margin():
    out = forecast(SNAP, {("2", "Managed users"): 3, ("1", "Nope"): 9})
    assert all(r["changed_lines"] == [] for r in out["clients"]), "a count for a line the client does not have changes nothing"
    low = forecast({"recurring": [rec("1", "Thin", ("X", 1, 10, 9)), rec("2", "Fat", ("X", 1, 10, 1)), rec("3", "NoCost", ("Y", 1, 10, 0))]}, {})
    assert [r["client_name"] for r in low["clients"]] == ["Thin", "Fat", "NoCost"], "lowest margin first; no costed lines goes last"


def test_a_snapshot_with_no_recurring_invoices_or_no_client_id_gives_nothing():
    assert forecast({}, {})["clients"] == []
    assert forecast({"recurring": [rec("", "x", ("A", 1, 1, 1))]}, {})["clients"] == []

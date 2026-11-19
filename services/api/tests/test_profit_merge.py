"""Keeping every month of the profitability data (pure)."""

from app.services.profit_merge import held_months, merge_profit


def inv(month, revenue=1.0, client="5"):
    return {"client_id": client, "client_name": "Acme", "month": month, "revenue": revenue, "invoices": 1}


def hrs(month, hours=1.0):
    return {"client": "Acme", "month": month, "agent_id": "40", "charge_type": "Remote Support", "hours": hours}


OLD = {"months": ["2025-01", "2025-02", "2026-10"], "invoices": [inv("2025-01", 10), inv("2025-02", 20), inv("2026-10", 30)], "hours": [hrs("2025-01"), hrs("2026-10", 3)], "agents": [{"id": "40", "name": "Dan"}]}


def test_the_first_summary_is_kept_as_it_is():
    assert merge_profit(None, OLD) == OLD


def test_the_months_sent_are_replaced_and_every_other_month_stays():
    new = {"months": ["2026-10", "2026-11"], "invoices": [inv("2026-10", 99), inv("2026-11", 5)], "hours": [hrs("2026-10", 7)], "agents": [{"id": "40", "name": "Daniel"}, {"id": "41", "name": "Eve"}]}
    out = merge_profit(OLD, new)
    assert out["months"] == ["2025-01", "2025-02", "2026-10", "2026-11"]
    assert sorted((r["month"], r["revenue"]) for r in out["invoices"]) == [("2025-01", 10), ("2025-02", 20), ("2026-10", 99), ("2026-11", 5)]
    assert sorted((r["month"], r["hours"]) for r in out["hours"]) == [("2025-01", 1.0), ("2026-10", 7)], "the month sent replaced its hours, the old month kept its"
    assert [a["name"] for a in out["agents"]] == ["Daniel", "Eve"], "the agents are the newest list"


def test_a_month_sent_with_nothing_in_it_is_emptied_not_left_as_it_was():
    out = merge_profit(OLD, {"months": ["2026-10"], "invoices": [], "hours": [], "agents": []})
    assert [r["month"] for r in out["invoices"]] == ["2025-01", "2025-02"]
    assert [r["month"] for r in out["hours"]] == ["2025-01"]


def test_only_the_newest_months_up_to_the_limit_are_kept_and_the_rows_of_the_rest_go_too():
    out = merge_profit(OLD, {"months": ["2026-11"], "invoices": [inv("2026-11")], "hours": [], "agents": []}, limit=2)
    assert out["months"] == ["2026-10", "2026-11"]
    assert {r["month"] for r in out["invoices"]} == {"2026-10", "2026-11"}


def test_held_months_are_those_in_the_summary_that_also_have_their_tickets():
    assert held_months(OLD, {"2025-01", "2026-10", "2020-01"}) == ["2025-01", "2026-10"]
    assert held_months(None, {"2025-01"}) == []

"""Estimated margin per client: money in whole cents, only lines with a price AND a cost, gaps listed, who may see it."""

from decimal import Decimal

from app.core.security import has_permission, permission_in
from app.services import finance as fin

P = {"Huntress per endpoint": (Decimal("6.00"), Decimal("3.50")), "M365 Business Premium": (Decimal("30.00"), Decimal("22.00"))}
NAMES = {"a": "Acme", "b": "Beta", "c": "Cee"}


def test_revenue_cost_and_margin_per_client_in_whole_cents_lowest_margin_first():
    billed = {
        "a": [{"item": "Huntress per endpoint", "count": 10}, {"item": "M365 Business Premium", "count": 4}],
        "b": [{"item": "Huntress per endpoint", "count": 3}],
    }
    out = fin.margin_rows(billed, P, NAMES)
    rows = {r["client_name"]: r for r in out["clients"]}
    assert (rows["Acme"]["revenue"], rows["Acme"]["cost"], rows["Acme"]["margin"]) == ("180.00", "123.00", "57.00")
    assert rows["Acme"]["margin_percent"] == 31.7
    assert (rows["Beta"]["revenue"], rows["Beta"]["cost"], rows["Beta"]["margin"]) == ("18.00", "10.50", "7.50")
    assert [r["client_name"] for r in out["clients"]] == ["Beta", "Acme"], "lowest margin first"
    assert out["totals"] == {"revenue": "198.00", "cost": "133.50", "margin": "64.50", "margin_percent": 32.6}


def test_a_line_with_no_price_is_listed_not_counted_as_free_and_junk_lines_are_ignored():
    billed = {
        "c": [
            {"item": "Mystery line", "count": 5},
            {"item": "Huntress per endpoint", "count": 0},
            {"item": "", "count": 3},
            {"item": "Huntress per endpoint", "count": "x"},
        ]
    }
    out = fin.margin_rows(billed, P, NAMES)
    (row,) = out["clients"]
    assert row["unpriced_items"] == ["Mystery line"]
    assert (row["revenue"], row["cost"], row["margin"], row["margin_percent"]) == ("0.00", "0.00", "0.00", None)
    assert out["totals"]["margin_percent"] is None


def test_fractions_of_a_cent_round_half_up_and_never_through_floats():
    out = fin.margin_rows({"a": [{"item": "x", "count": 3}]}, {"x": (Decimal("0.335"), Decimal("0.10"))}, NAMES)
    assert out["clients"][0]["revenue"] == "1.01"  # 0.335 x 3 = 1.005 -> 1.01


def test_only_the_workspace_owner_roles_hold_the_finance_permissions_by_default():
    assert has_permission("tenant_admin", "finance:view") and has_permission("tenant_admin", "finance:write")
    for role in ("soc_lead", "soc_analyst", "threat_hunter", "viewer", "api_service"):
        assert not has_permission(role, "finance:view"), role
    assert not permission_in(["billing:view", "alerts:read"], "finance:view"), "holding the licence counts does not show money"
    assert permission_in(["finance:view"], "finance:view") and not permission_in(["finance:view"], "finance:write")

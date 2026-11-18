"""Add-on software cost per client from vendor bills and license counts (pure rules)."""

from decimal import Decimal

from app.services.addon_software import CountRow, allocate

D = Decimal


def rows(*items):
    return [CountRow(*i) for i in items]


def test_a_vendors_bill_is_split_by_the_clients_license_counts_and_adds_up_to_the_cent():
    out = allocate(
        {"Huntress": D("100.00")},
        {"Huntress": [("huntress", "Managed EDR")]},
        rows(("acme", "huntress", "Managed EDR", 10), ("birch", "huntress", "Managed EDR", 20), ("cedar", "huntress", "Managed EDR", 10)),
    )
    assert out["per_client"] == {"acme": D("25.00"), "birch": D("50.00"), "cedar": D("25.00")}
    assert out["per_vendor"]["Huntress"] == {"cost": D("100.00"), "allocated": D("100.00"), "licenses": 40, "per_license": D("2.5000")}
    assert out["unallocated"] == D("0.00")
    odd = allocate({"V": D("100.00")}, {"V": [("s", "i")]}, rows(("a", "s", "i", 1), ("b", "s", "i", 1), ("c", "s", "i", 1)))
    assert sum(odd["per_client"].values()) == D("100.00"), "three equal parts of 100.00 still add up exactly"


def test_several_counts_can_stand_behind_one_vendor_and_a_client_with_both_carries_both():
    out = allocate(
        {"Kaseya": D("90.00")},
        {"Kaseya": [("datto", "Endpoint backup"), ("datto", "SaaS backup")]},
        rows(("acme", "datto", "Endpoint backup", 2), ("acme", "datto", "SaaS backup", 1), ("birch", "datto", "SaaS backup", 3)),
    )
    assert out["per_client"] == {"acme": D("45.00"), "birch": D("45.00")}
    assert out["per_vendor"]["Kaseya"]["licenses"] == 6


def test_a_vendor_with_nothing_mapped_or_nothing_counted_is_left_unallocated_not_guessed():
    out = allocate(
        {"LastPass": D("10.00"), "Keeper": D("20.00"), "Slides": D("5.00")},
        {"Keeper": [("keeper", "Seats")], "Slides": [("slides", "Seats")]},
        rows(("acme", "keeper", "Seats", 0), ("acme", "other", "Seats", 5)),
    )
    assert out["per_client"] == {}
    assert out["unallocated"] == D("35.00")
    assert out["per_vendor"]["LastPass"]["per_license"] is None and out["per_vendor"]["Keeper"]["licenses"] == 0


def test_zero_bills_are_skipped_and_negative_counts_and_clients_with_no_key_do_not_count():
    out = allocate({"A": D("0.00"), "B": D("10.00")}, {"B": [("s", "i")]}, rows(("acme", "s", "i", -5), ("", "s", "i", 9), ("birch", "s", "i", 2)))
    assert "A" not in out["per_vendor"]
    assert out["per_client"] == {"birch": D("10.00")}


def test_a_credit_is_spread_the_same_way_and_two_vendors_add_to_the_same_client():
    out = allocate(
        {"A": D("-20.00"), "B": D("30.00")},
        {"A": [("s", "a")], "B": [("s", "b")]},
        rows(("acme", "s", "a", 1), ("birch", "s", "a", 1), ("acme", "s", "b", 1)),
    )
    assert out["per_client"] == {"acme": D("20.00"), "birch": D("-10.00")}


from datetime import UTC, datetime  # noqa: E402

from app.services.addon_software import Change, count_as_of  # noqa: E402


def at(d):
    return datetime(2026, 9, d, 12, tzinfo=UTC)


def test_a_count_at_a_month_end_is_the_count_after_the_last_change_on_or_before_it():
    h = [Change(at(5), 10), Change(at(20), 14), Change(at(28), 12)]
    assert count_as_of(h, 99, at(19)) == 10
    assert count_as_of(h, 99, at(20)) == 14, "a change at that moment counts"
    assert count_as_of(h, 99, at(30)) == 12
    assert count_as_of(list(reversed(h)), 99, at(21)) == 14, "the order the history arrives in does not matter"


def test_before_the_first_change_the_first_count_is_used_and_with_no_history_the_current_count():
    assert count_as_of([Change(at(10), 7), Change(at(15), 9)], 99, at(1)) == 7
    assert count_as_of([], 42, at(1)) == 42

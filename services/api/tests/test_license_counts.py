from datetime import UTC, datetime, timedelta

from app.services.license_counts import changes, count_at, delta, totals, window_start

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def rep(item, count, unit="device", available=None):
    return {"item": item, "unit": unit, "count": count, "available": available}


def test_a_first_report_records_every_item_with_no_previous_count():
    c = changes({}, [rep("Macs", 4), rep("Business Premium", 25, "licence", 2)])
    assert [(h["item"], h["count"], h["previous_count"]) for h in c["history"]] == [("Macs", 4, None), ("Business Premium", 25, None)]
    assert [u["item"] for u in c["upserts"]] == ["Macs", "Business Premium"] and c["removed"] == []


def test_only_a_changed_count_adds_history_and_it_keeps_the_old_count():
    c = changes({"Macs": 4, "Windows": 10}, [rep("Macs", 4), rep("Windows", 12)])
    assert [(h["item"], h["previous_count"], h["count"]) for h in c["history"]] == [("Windows", 10, 12)]
    assert len(c["upserts"]) == 2, "every reported item is stored, changed or not"


def test_an_item_that_is_no_longer_reported_is_removed_and_recorded_as_zero():
    c = changes({"Macs": 4, "Old": 3}, [rep("Macs", 4)])
    assert c["removed"] == ["Old"]
    assert c["history"] == [{"item": "Old", "unit": "other", "count": 0, "previous_count": 3}]


def test_a_repeated_item_in_one_report_counts_once():
    assert len(changes({}, [rep("Macs", 4), rep("Macs", 9)])["upserts"]) == 1


def h(days_after_t0, count):
    return {"observed_at": T0 + timedelta(days=days_after_t0), "count": count}


def test_the_count_at_a_date_is_the_newest_row_at_or_before_it():
    rows = [h(0, 10), h(10, 12), h(20, 8)]
    assert count_at(rows, 8, T0, T0 + timedelta(days=15), T0) == 12
    assert count_at(rows, 8, T0, T0 + timedelta(days=10), T0) == 12, "a change on that very day counts"
    assert count_at(rows, 8, T0, T0 + timedelta(days=25), T0) == 8


def test_an_item_with_no_row_that_old_was_unchanged_or_new():
    when = T0 + timedelta(days=30)
    assert count_at([], 7, T0, when, T0) == 7, "seen before the date and never changed"
    assert count_at([h(40, 9)], 9, T0 + timedelta(days=40), when, T0) == 0, "appeared after the date, while it was tracked"
    assert count_at([h(40, 9)], 9, T0 + timedelta(days=40), when, T0 + timedelta(days=35)) is None, "tracking had not started: unknown"


def test_delta_is_unknown_when_the_old_count_is():
    assert delta(12, 10) == 2 and delta(8, 10) == -2 and delta(5, None) is None


def test_totals_add_across_clients_with_the_change_and_unknown_when_any_client_is_unknown():
    rows = [
        {"source": "cipp", "item": "BP", "unit": "licence", "count": 25, "available": 2, "then": 20},
        {"source": "cipp", "item": "BP", "unit": "licence", "count": 10, "available": 0, "then": 10},
        {"source": "ninjaone", "item": "Macs", "unit": "device", "count": 4, "available": None, "then": None},
    ]
    t = {(r["source"], r["item"]): r for r in totals(rows)}
    assert t[("cipp", "BP")] == {"source": "cipp", "item": "BP", "unit": "licence", "clients": 2, "total": 35, "available": 2, "change": 5}
    assert t[("ninjaone", "Macs")]["change"] is None and t[("ninjaone", "Macs")]["available"] is None


def test_the_window_is_at_least_a_day_and_at_most_400():
    now = datetime(2026, 10, 25, tzinfo=UTC)
    assert window_start(now, 0) == now - timedelta(days=1)
    assert window_start(now, 9999) == now - timedelta(days=400)


from app.services.license_counts import reconcile, suggest  # noqa: E402


def test_suggestions_match_the_specific_words_first():
    assert suggest("Huntress SAT (Security Awareness Training) (Included)") == [{"source": "huntress", "item": "Awareness training learners"}]
    assert suggest("Huntress for Workstations (Included)") == [{"source": "huntress", "item": "Agents"}]
    assert [s["item"] for s in suggest("NinjaOne RMM (Included)")] == ["Windows workstations", "Windows servers", "Macs"]
    assert suggest("Datto SaaS (PassThru)") == [{"source": "datto-saas", "item": "Billable seats"}]
    assert suggest("Managed Service - taxable portion") == []


def test_reconcile_compares_each_mapped_line_with_the_added_up_counts_and_lists_the_unmapped():
    billed = [{"item": "Huntress for Workstations (Included)", "count": 35}, {"item": "NinjaOne RMM (Included)", "count": 16}, {"item": "Liongard (Included)", "count": 1}]
    held = [{"source": "huntress", "item": "Agents", "count": 40}, {"source": "ninjaone", "item": "Windows workstations", "count": 12}, {"source": "ninjaone", "item": "Macs", "count": 4}]
    mapping = {"Huntress for Workstations (Included)": [{"source": "huntress", "item": "Agents"}], "NinjaOne RMM (Included)": [{"source": "ninjaone", "item": "Windows workstations"}, {"source": "ninjaone", "item": "Macs"}, {"source": "ninjaone", "item": "Windows servers"}]}
    r = reconcile(billed, held, mapping)
    assert [(x["invoice_item"], x["billed"], x["counted"], x["difference"]) for x in r["rows"]] == [("Huntress for Workstations (Included)", 35, 40, 5), ("NinjaOne RMM (Included)", 16, 16, 0)]
    assert r["rows"][1]["parts"][2] == {"source": "ninjaone", "item": "Windows servers", "count": 0}, "a mapped item the tool does not count is shown as 0"
    assert r["unmapped"] == [{"item": "Liongard (Included)", "billed": 1}]


def test_the_biggest_difference_comes_first_whichever_way_it_goes():
    billed = [{"item": "A", "count": 10}, {"item": "B", "count": 10}]
    held = [{"source": "t", "item": "a", "count": 9}, {"source": "t", "item": "b", "count": 25}]
    r = reconcile(billed, held, {"A": [{"source": "t", "item": "a"}], "B": [{"source": "t", "item": "b"}]})
    assert [x["invoice_item"] for x in r["rows"]] == ["B", "A"]


def test_a_change_of_more_than_a_fifth_of_at_least_five_is_unusual():
    from app.services.license_counts import unusual

    assert unusual(10, 5) is True  # doubled
    assert unusual(3, 10) is True  # dropped by 70 percent
    assert unusual(0, 8) is True  # gone
    assert unusual(11, 10) is False  # a tenth
    assert unusual(12, 10) is False  # exactly a fifth is not more than a fifth
    assert unusual(13, 10) is True
    assert unusual(3, 2) is False  # too small to matter
    assert unusual(40, None) is False  # first sight: nothing to compare with


def test_a_tool_that_counts_far_fewer_machines_than_the_rmm_is_flagged_with_the_gap():
    from app.services.license_counts import endpoint_disagreements

    per = {
        "a": [{"source": "ninjaone", "item": "Windows workstations", "count": 40}, {"source": "ninjaone", "item": "Macs", "count": 10}, {"source": "huntress", "item": "Agents", "count": 30}],
        "b": [{"source": "ninjaone", "item": "Windows workstations", "count": 40}, {"source": "huntress", "item": "Agents", "count": 38}],
        "c": [{"source": "huntress", "item": "Agents", "count": 9}],
        "d": [{"source": "ninjaone", "item": "Windows workstations", "count": 3}, {"source": "huntress", "item": "Agents", "count": 0}],
        "e": [{"source": "ninjaone", "item": "Windows workstations", "count": 40}],
    }
    out = endpoint_disagreements(per)
    assert [(r["client"], r["tool"], r["gap"], r["baseline_count"]) for r in out] == [("a", "huntress", -20, 50), ("d", "huntress", -3, 3)]
    # b is within a fifth, c has no RMM count to compare with, e has no tool count (coverage, not disagreement).


def test_a_small_gap_is_not_a_disagreement_even_when_it_is_a_big_fraction():
    from app.services.license_counts import endpoint_disagreements

    assert endpoint_disagreements({"a": [{"source": "ninjaone", "item": "Macs", "count": 5}, {"source": "huntress", "item": "Agents", "count": 3}]}) == []


def test_last_reported_takes_the_newest_count_per_client_and_tool_and_marks_the_silent_ones_first():
    from app.services.license_counts import last_reported

    now = datetime(2026, 10, 25, 12, tzinfo=UTC)
    rows = [
        {"client": "a", "source": "ninjaone", "updated_at": now - timedelta(days=9)},
        {"client": "a", "source": "ninjaone", "updated_at": now - timedelta(hours=3)},
        {"client": "a", "source": "huntress", "updated_at": now - timedelta(days=5)},
        {"client": "b", "source": "huntress", "updated_at": now - timedelta(days=2, hours=23)},
        {"client": "b", "source": "slide", "updated_at": now - timedelta(days=3)},
    ]
    out = last_reported(rows, now)
    assert [(r["client"], r["source"], r["days_ago"], r["silent"]) for r in out] == [("a", "huntress", 5, True), ("b", "slide", 3, True), ("b", "huntress", 2, False), ("a", "ninjaone", 0, False)]

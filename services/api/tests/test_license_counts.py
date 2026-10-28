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
    assert suggest("Huntress SAT (Security Awareness Training) (Included)") == [
        {"source": "huntress", "item": "Awareness training learners"}
    ]
    assert suggest("Huntress for Workstations (Included)") == [{"source": "huntress", "item": "Agents"}]
    assert [s["item"] for s in suggest("NinjaOne RMM (Included)")] == ["Windows workstations", "Windows servers", "Macs"]
    assert suggest("Datto SaaS (PassThru)") == [{"source": "datto-saas", "item": "Billable seats"}]
    assert suggest("DNS Filter (PassThru)") == [{"source": "dnsfilter", "item": "Roaming agents"}], "billed as two words"
    assert suggest("Managed Service - taxable portion") == []


def test_reconcile_compares_each_mapped_line_with_the_added_up_counts_and_lists_the_unmapped():
    billed = [
        {"item": "Huntress for Workstations (Included)", "count": 35},
        {"item": "NinjaOne RMM (Included)", "count": 16},
        {"item": "Liongard (Included)", "count": 1},
    ]
    held = [
        {"source": "huntress", "item": "Agents", "count": 40},
        {"source": "ninjaone", "item": "Windows workstations", "count": 12},
        {"source": "ninjaone", "item": "Macs", "count": 4},
    ]
    mapping = {
        "Huntress for Workstations (Included)": [{"source": "huntress", "item": "Agents"}],
        "NinjaOne RMM (Included)": [
            {"source": "ninjaone", "item": "Windows workstations"},
            {"source": "ninjaone", "item": "Macs"},
            {"source": "ninjaone", "item": "Windows servers"},
        ],
    }
    r = reconcile(billed, held, mapping)
    assert [(x["invoice_item"], x["billed"], x["counted"], x["difference"]) for x in r["rows"]] == [
        ("Huntress for Workstations (Included)", 35, 40, 5),
        ("NinjaOne RMM (Included)", 16, 16, 0),
    ]
    assert r["rows"][1]["parts"][2] == {
        "source": "ninjaone",
        "item": "Windows servers",
        "count": 0,
    }, "a mapped item the tool does not count is shown as 0"
    assert r["unmapped"] == [{"item": "Liongard (Included)", "billed": 1}]


def test_a_line_saved_as_no_tool_counts_this_is_neither_compared_nor_left_to_map():
    billed = [{"item": "Managed Service", "count": 1}, {"item": "Huntress MDR", "count": 5}, {"item": "Inky", "count": 40}]
    held = [{"source": "huntress", "item": "Agents", "count": 5}]
    r = reconcile(billed, held, {"Managed Service": [], "Huntress MDR": [{"source": "huntress", "item": "Agents"}]})
    assert [x["invoice_item"] for x in r["rows"]] == ["Huntress MDR"], "the flat fee is not a row with a difference"
    assert r["unmapped"] == [
        {"item": "Inky", "billed": 40}
    ], "and it is not waiting to be mapped, while a line nobody has dealt with still is"


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
        "a": [
            {"source": "ninjaone", "item": "Windows workstations", "count": 40},
            {"source": "ninjaone", "item": "Macs", "count": 10},
            {"source": "huntress", "item": "Agents", "count": 30},
        ],
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

    assert (
        endpoint_disagreements(
            {"a": [{"source": "ninjaone", "item": "Macs", "count": 5}, {"source": "huntress", "item": "Agents", "count": 3}]}
        )
        == []
    )


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
    assert [(r["client"], r["source"], r["days_ago"], r["silent"]) for r in out] == [
        ("a", "huntress", 5, True),
        ("b", "slide", 3, True),
        ("b", "huntress", 2, False),
        ("a", "ninjaone", 0, False),
    ]


def test_a_tool_with_mapped_clients_and_no_count_is_listed_and_a_renamed_source_is_matched():
    from app.services.license_counts import tools_without_counts

    assert tools_without_counts(
        {"ninjaone", "blumira", "datto-saas-seats", "cipp-health", "petra"}, {"ninjaone", "datto-saas", "cipp"}
    ) == ["blumira", "petra"]
    assert tools_without_counts(set(), {"ninjaone"}) == []


def test_a_count_series_starts_with_what_the_first_change_replaced_has_a_point_per_change_and_ends_now():
    from app.services.license_counts import count_series

    now = datetime(2026, 10, 25, tzinfo=UTC)
    since = now - timedelta(days=30)
    hist = [
        {"observed_at": now - timedelta(days=40), "count": 10, "previous_count": None},
        {"observed_at": now - timedelta(days=20), "count": 12, "previous_count": 10},
        {"observed_at": now - timedelta(days=5), "count": 9, "previous_count": 12},
    ]
    out = count_series(hist, 9, now, since)
    assert [(p["at"], p["count"]) for p in out] == [(since, 10), (now - timedelta(days=20), 12), (now - timedelta(days=5), 9), (now, 9)]


def test_a_series_with_no_change_in_the_window_is_flat_at_the_count_it_had_and_a_new_item_starts_at_its_first_row():
    from app.services.license_counts import count_series

    now = datetime(2026, 10, 25, tzinfo=UTC)
    since = now - timedelta(days=30)
    old = [{"observed_at": now - timedelta(days=60), "count": 7, "previous_count": None}]
    assert [(p["at"], p["count"]) for p in count_series(old, 7, now, since)] == [(since, 7), (now, 7)]
    assert [p["count"] for p in count_series([], 4, now, since)] == [4, 4]
    fresh = [{"observed_at": now - timedelta(days=3), "count": 5, "previous_count": None}]
    assert [(p["at"], p["count"]) for p in count_series(fresh, 5, now, since)] == [(now - timedelta(days=3), 5), (now, 5)]


def test_a_note_accepts_a_difference_only_while_it_is_still_that_difference():
    from app.services.license_counts import note_state

    note = {"note": "flat package", "difference": 2}
    assert note_state(note, 2) == "accepted"
    assert note_state(note, 3) == "stale", "the difference moved"
    assert note_state(note, -2) == "stale", "the opposite way is a different difference"
    assert note_state(note, 0) == "none", "a line that now matches needs no note"
    assert note_state(None, 2) == "none"


def test_a_forecast_reads_a_straight_line_thirty_days_past_the_last_point_and_has_no_forecast_without_a_trend():
    from app.services.license_counts import forecast_next

    t0 = datetime(2026, 8, 1, tzinfo=UTC)
    rising = [{"at": t0 + timedelta(days=d), "count": 10 + d // 10} for d in (0, 30, 60, 90)]  # 10, 13, 16, 19: +1 every 10 days
    assert forecast_next(rising) == 22, "19 at day 90 and 3 more by day 120"
    flat = [{"at": t0 + timedelta(days=d), "count": 7} for d in (0, 45, 90)]
    assert forecast_next(flat) == 7
    falling = [{"at": t0 + timedelta(days=d), "count": 5 - d // 30 * 2} for d in (0, 30, 60)]
    assert forecast_next(falling) == 0, "never below zero"
    assert forecast_next(rising[:2]) is None, "two points are not a trend"
    assert forecast_next([{"at": t0, "count": 1}, {"at": t0, "count": 2}, {"at": t0, "count": 3}]) is None, "no time between them"


def test_a_client_with_machines_and_no_billed_line_is_listed_largest_first_and_tickets_do_not_count_as_billed():
    from app.services.license_counts import unbilled_clients

    per = {
        "a": [
            {"source": "ninjaone", "item": "Windows workstations", "count": 12},
            {"source": "halopsa", "item": "NinjaOne RMM (Included)", "count": 12, "unit": "other"},
        ],
        "b": [{"source": "ninjaone", "item": "Windows workstations", "count": 30}],
        "c": [
            {"source": "ninjaone", "item": "Macs", "count": 4},
            {"source": "halopsa", "item": "Tickets opened in the last 30 days", "count": 9, "unit": "ticket"},
        ],
        "d": [{"source": "halopsa", "item": "Managed Service", "count": 1, "unit": "other"}],
        "e": [{"source": "ninjaone", "item": "Windows workstations", "count": 0}],
        "f": [{"source": "huntress", "item": "Agents", "count": 50}],
    }
    assert unbilled_clients(per) == [{"client": "b", "machines": 30}, {"client": "c", "machines": 4}]


def test_every_suggestion_rule_has_a_confidence_and_a_line_with_no_suggestion_has_none():
    from app.services.license_counts import SUGGESTION_CONFIDENCE, SUGGESTIONS, suggestion_confidence

    assert {needle for needle, _ in SUGGESTIONS} == set(SUGGESTION_CONFIDENCE), "a rule without a stated confidence would be applied blind"
    assert set(SUGGESTION_CONFIDENCE.values()) <= {"high", "medium", "low"}
    assert suggestion_confidence("Huntress for Workstations (Included)") == "high"
    assert suggestion_confidence("Huntress SAT (Security Awareness Training) (Included)") == "high"
    assert suggestion_confidence("NinjaOne RMM (Included)") == "medium"
    assert suggestion_confidence("ThreatMate (Included)") == "low"
    assert suggestion_confidence("DNS Filter (PassThru)") == "high"
    assert suggestion_confidence("Managed Service - taxable portion") is None


# ---- how long an invoice line has disagreed ----

from app.services.license_counts import disagreement_since  # noqa: E402

_D0 = datetime(2026, 9, 1, tzinfo=UTC)


def _day(n: int) -> datetime:
    return _D0 + timedelta(days=n)


_BILLED = ("halopsa", "Endpoint protection")
_PART = ("huntress", "Agents")


def test_a_line_disagrees_since_the_change_after_which_it_never_matched_again():
    # day 0: billed 10, counted 10 (they match). day 10: the tool counts 14. day 20: billed is still 10.
    history = {
        _BILLED: [{"observed_at": _day(0), "count": 10}],
        _PART: [{"observed_at": _day(0), "count": 10}, {"observed_at": _day(10), "count": 14}],
    }
    current = {_BILLED: (10, _day(0)), _PART: (14, _day(0))}
    since, complete = disagreement_since(_BILLED, [_PART], history, current, {"halopsa": _day(0), "huntress": _day(0)}, _day(30))
    assert (since, complete) == (_day(10), True)


def test_a_difference_that_moved_but_never_matched_counts_from_the_first_change_that_started_it():
    history = {
        _BILLED: [{"observed_at": _day(0), "count": 10}],
        _PART: [{"observed_at": _day(0), "count": 10}, {"observed_at": _day(5), "count": 12}, {"observed_at": _day(15), "count": 15}],
    }
    current = {_BILLED: (10, _day(0)), _PART: (15, _day(0))}
    since, complete = disagreement_since(_BILLED, [_PART], history, current, {"halopsa": _day(0), "huntress": _day(0)}, _day(30))
    assert (since, complete) == (_day(5), True), "the line went 10/12 then 10/15: it has not matched since day 5"


def test_a_line_that_never_matched_since_it_was_first_recorded_says_it_is_only_as_old_as_the_record():
    history = {_BILLED: [{"observed_at": _day(3), "count": 10}], _PART: [{"observed_at": _day(3), "count": 14}]}
    current = {_BILLED: (10, _day(3)), _PART: (14, _day(3))}
    since, complete = disagreement_since(_BILLED, [_PART], history, current, {"halopsa": _day(3), "huntress": _day(3)}, _day(30))
    assert (since, complete) == (_day(3), False)


def test_a_billed_change_that_ended_a_match_starts_the_disagreement_there():
    # the tool counted 10 all along; the invoice was raised from 10 to 8 on day 7.
    history = {
        _BILLED: [{"observed_at": _day(0), "count": 10}, {"observed_at": _day(7), "count": 8}],
        _PART: [{"observed_at": _day(0), "count": 10}],
    }
    current = {_BILLED: (8, _day(0)), _PART: (10, _day(0))}
    since, complete = disagreement_since(_BILLED, [_PART], history, current, {"halopsa": _day(0), "huntress": _day(0)}, _day(20))
    assert (since, complete) == (_day(7), True)


def test_several_parts_are_added_up_before_they_are_compared():
    a, b = ("ninjaone", "Windows workstations"), ("ninjaone", "Windows servers")
    history = {
        _BILLED: [{"observed_at": _day(0), "count": 20}],
        a: [{"observed_at": _day(0), "count": 15}, {"observed_at": _day(4), "count": 17}],
        b: [{"observed_at": _day(0), "count": 5}],
    }
    current = {_BILLED: (20, _day(0)), a: (17, _day(0)), b: (5, _day(0))}
    since, complete = disagreement_since(_BILLED, [a, b], history, current, {"halopsa": _day(0), "ninjaone": _day(0)}, _day(9))
    assert (since, complete) == (_day(4), True), "15 + 5 matched 20; 17 + 5 does not"


def test_a_part_that_was_not_yet_tracked_leaves_the_start_as_far_back_as_it_can_be_told():
    # the tool was only tracked from day 10; before that nothing is known about it.
    history = {_BILLED: [{"observed_at": _day(0), "count": 10}], _PART: [{"observed_at": _day(10), "count": 14}]}
    current = {_BILLED: (10, _day(0)), _PART: (14, _day(10))}
    since, complete = disagreement_since(_BILLED, [_PART], history, current, {"halopsa": _day(0), "huntress": _day(10)}, _day(30))
    assert (since, complete) == (_day(10), False)

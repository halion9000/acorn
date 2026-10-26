from app.services.check_history import changes, trend


def c(key, status, evidence="e"):
    return {"key": key, "status": status, "evidence": evidence}


def test_first_report_records_every_check():
    out = changes(None, [c("a", "met"), c("b", "not_met")], "ninjaone")
    assert [(x["key"], x["status"], x["previous_status"]) for x in out] == [("a", "met", None), ("b", "not_met", None)]
    assert all(x["source"] == "ninjaone" for x in out)


def test_only_a_changed_status_is_recorded_and_it_keeps_the_old_status():
    out = changes([c("a", "met"), c("b", "not_met")], [c("a", "met", "new words"), c("b", "partly")], "x")
    assert [(x["key"], x["previous_status"], x["status"]) for x in out] == [("b", "not_met", "partly")]


def test_a_check_missing_from_the_new_report_is_not_a_change():
    assert changes([c("a", "not_met")], [c("b", "met")], "x") == [{"source": "x", "key": "b", "status": "met", "previous_status": None, "evidence": "e"}]


def test_unknown_statuses_and_keyless_rows_are_ignored_and_evidence_is_cut():
    out = changes([], [c("a", "weird"), {"status": "met"}, c("b", "met", "x" * 500), "junk"], "x")  # type: ignore[list-item]
    assert [x["key"] for x in out] == ["b"]
    assert len(out[0]["evidence"]) == 300


def test_trend_says_worse_better_same_new():
    row = lambda s: {"status": s}  # noqa: E731
    assert trend([]) == {"changes": 0, "direction": "none"}
    assert trend([row("not_met")])["direction"] == "new"
    assert trend([row("not_met"), row("met")])["direction"] == "worse"
    assert trend([row("met"), row("partly")])["direction"] == "better"
    assert trend([row("met"), row("met")])["direction"] == "same"
    assert trend([row("met"), row("partly"), row("met")])["changes"] == 3


def test_items_that_join_or_leave_a_checks_list_are_reported_and_a_first_report_or_a_new_check_is_not():
    from app.services.check_history import item_changes

    prev = [{"key": "av", "items": ["PC-1", "PC-2"]}, {"key": "gone", "items": ["X"]}]
    new = [{"key": "av", "items": ["PC-2", "PC-3", "PC-3"]}, {"key": "fresh", "items": ["A", "B"]}, {"key": "nolist"}]
    assert item_changes(prev, new) == [{"key": "av", "item": "PC-3", "event": "joined"}, {"key": "av", "item": "PC-1", "event": "left"}]
    assert item_changes(None, new) == [], "the first report would otherwise make every item join"
    assert item_changes(prev, [{"key": "av", "items": ["PC-1", "PC-2"]}]) == [], "an unchanged list says nothing"
    assert item_changes(prev, [{"key": "av"}]) == [{"key": "av", "item": "PC-1", "event": "left"}, {"key": "av", "item": "PC-2", "event": "left"}], "an emptied list means everything left"


def test_a_wholesale_replacement_keeps_only_the_first_events_of_that_check():
    from app.services.check_history import MAX_ITEM_EVENTS_PER_CHECK, item_changes

    out = item_changes([{"key": "k", "items": [f"old{i}" for i in range(300)]}], [{"key": "k", "items": [f"new{i}" for i in range(300)]}])
    assert len(out) == MAX_ITEM_EVENTS_PER_CHECK and all(e["event"] == "joined" for e in out)

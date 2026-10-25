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

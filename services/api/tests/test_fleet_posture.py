from datetime import UTC, datetime, timedelta

from app.services.fleet_posture import BOARDS, FleetCheck, board_rows, coverage_matrix, rank_clients, stale_sources, summarize, tool_rows


def chk(status, key="k", client="Acme", accepted=False):
    return FleetCheck(client_id=client.lower(), client_name=client, source="x", key=key, status=status, evidence="e", accepted=accepted)


def test_the_score_is_the_share_that_is_fine_with_partly_counting_half():
    s = summarize([chk("met"), chk("partly"), chk("not_met"), chk("met")])
    assert s == {"score": 63, "met": 2, "partly": 1, "not_met": 1, "accepted": 0}


def test_an_accepted_check_is_left_out_of_the_score_and_counted_apart():
    s = summarize([chk("met"), chk("not_met", accepted=True)])
    assert s["score"] == 100 and s["not_met"] == 0 and s["accepted"] == 1


def test_no_checks_means_no_score():
    assert summarize([])["score"] is None
    assert summarize([chk("not_met", accepted=True)])["score"] is None


def test_clients_are_ranked_worst_first_and_those_without_a_score_last():
    ranked = rank_clients(
        [
            {"client_name": "Zed", "score": 90, "not_met": 0},
            {"client_name": "Quiet", "score": None, "not_met": 0},
            {"client_name": "Beta", "score": 40, "not_met": 3},
            {"client_name": "Alpha", "score": 40, "not_met": 5},
            {"client_name": "Gamma", "score": 40, "not_met": 3},
        ]
    )
    assert [r["client_name"] for r in ranked] == ["Alpha", "Beta", "Gamma", "Zed", "Quiet"]


def test_a_board_takes_only_its_checks_worst_first_and_skips_fine_ones_unless_asked():
    rows = [
        chk("met", "a", "Zed"),
        chk("partly", "a", "Beta"),
        chk("not_met", "a", "Zed"),
        chk("not_met", "other", "Acme"),
        chk("not_met", "a", "Acme", accepted=True),
        chk("not_met", "b", "Acme"),
    ]
    got = board_rows(rows, ["a", "b"])
    assert [(r.client_name, r.key, r.status, r.accepted) for r in got] == [
        ("Acme", "b", "not_met", False),
        ("Zed", "a", "not_met", False),
        ("Beta", "a", "partly", False),
        ("Acme", "a", "not_met", True),
    ]
    assert len(board_rows(rows, ["a", "b"], include_met=True)) == 5


def test_every_board_names_checks_and_no_check_is_named_twice_in_one_board():
    for name, (title, keys) in BOARDS.items():
        assert title and keys and len(keys) == len(set(keys)), name


def test_stale_sources_are_the_ones_older_than_48_hours():
    now = datetime(2026, 10, 25, tzinfo=UTC)
    assert stale_sources({"a": now - timedelta(hours=3), "b": now - timedelta(hours=49), "c": now - timedelta(days=9)}, now) == ["b", "c"]


def test_the_coverage_matrix_lists_tools_most_used_first_and_what_each_client_lacks():
    names = {"a": "Acme", "b": "Beta", "c": "Cora"}
    m = coverage_matrix([("a", "ninjaone"), ("a", "huntress"), ("b", "ninjaone"), ("c", "slide"), ("a", "ninjaone")], names)
    assert m["tools"] == [{"vendor": "ninjaone", "clients": 2}, {"vendor": "huntress", "clients": 1}, {"vendor": "slide", "clients": 1}]
    by = {c["client_name"]: c for c in m["clients"]}
    assert by["Acme"]["tools"] == ["ninjaone", "huntress"] and by["Acme"]["missing"] == ["slide"]
    assert by["Beta"]["missing"] == ["huntress", "slide"]
    assert [c["client_name"] for c in m["clients"]][0] == "Acme", "clients with the most tools first"


def test_a_client_mapped_to_nothing_is_still_listed_missing_everything():
    m = coverage_matrix([("a", "ninjaone")], {"a": "Acme", "z": "Zed"})
    assert {c["client_name"]: c["missing"] for c in m["clients"]} == {"Acme": [], "Zed": ["ninjaone"]}
    assert coverage_matrix([], {"z": "Zed"}) == {
        "tools": [],
        "clients": [{"client_id": "z", "client_name": "Zed", "tools": [], "missing": []}],
    }


def test_accepted_risks_that_run_out_soonest_come_first_and_expired_ones_are_gone():
    from datetime import UTC, datetime, timedelta

    from app.services.fleet_posture import expiring_acceptances

    now = datetime(2026, 10, 25, tzinfo=UTC)
    rows = [
        {"client_name": "B", "key": "k1", "expires_at": now + timedelta(days=20)},
        {"client_name": "A", "key": "k2", "expires_at": None},
        {"client_name": "C", "key": "k3", "expires_at": now - timedelta(days=1)},
        {"client_name": "D", "key": "k4", "expires_at": now + timedelta(days=3)},
    ]
    assert [r["key"] for r in expiring_acceptances(rows, now)] == ["k4", "k1", "k2"]
    assert [r["key"] for r in expiring_acceptances(rows, now, 7)] == ["k4"]
    assert [r["key"] for r in expiring_acceptances(rows, now, 30)] == ["k4", "k1"], "no end date is never expiring"
    assert expiring_acceptances([], now) == []


def test_a_client_is_below_target_only_when_it_has_both_a_score_and_a_target_and_the_score_is_under():
    from app.services.fleet_posture import below_target

    assert below_target(70, 80) is True
    assert below_target(80, 80) is False, "meeting the target is not below it"
    assert below_target(95, 80) is False
    assert below_target(None, 80) is False, "no checks, no score, nothing to miss"
    assert below_target(50, None) is False


def test_the_fleet_average_leaves_out_clients_with_no_score_and_rounds():
    from app.services.fleet_posture import average_score

    assert average_score([80, 60, None, 71]) == 70, "(80 + 60 + 71) / 3 = 70.33"
    assert average_score([None, None]) is None
    assert average_score([]) is None
    assert average_score([50, 51]) == 51, "50.5 rounds up"


def test_a_check_is_overdue_only_when_its_date_has_passed_and_it_is_not_fully_met():
    from datetime import date

    from app.services.fleet_posture import is_overdue

    today = date(2026, 10, 26)
    assert is_overdue("not_met", date(2026, 10, 25), today) is True
    assert is_overdue("partly", date(2026, 10, 1), today) is True
    assert is_overdue("not_met", date(2026, 10, 26), today) is False, "the due day itself is not late"
    assert is_overdue("not_met", date(2026, 11, 1), today) is False
    assert is_overdue("met", date(2026, 10, 1), today) is False, "fixed, so not late"
    assert is_overdue("not_met", None, today) is False


def _fc(client, key, status, evidence="", items=(), source="ninjaone", accepted=False):
    from app.services.fleet_posture import FleetCheck

    return FleetCheck(
        client_id=f"id-{client}",
        client_name=client,
        source=source,
        key=key,
        status=status,
        evidence=evidence,
        items=tuple(items),
        accepted=accepted,
    )


def test_a_search_finds_a_machine_or_word_in_the_evidence_the_key_or_the_items_and_puts_problems_first():
    from app.services.fleet_posture import search_checks

    checks = [
        _fc("Aaa", "ninjaone_antivirus", "met", "All fine", ["SRV-02: protected"]),
        _fc("Acme", "ninjaone_patching", "not_met", "3 behind", ["PC-1: behind", "srv-02: 40 days"]),
        _fc("Beta", "huntress_quiet_agents", "partly", "Agent on SRV-02 quiet for 9 days"),
        _fc("Gamma", "meraki_wan", "not_met", "WAN up", ["MX-1"]),
    ]
    out = search_checks(checks, "Srv-02")
    assert [(r["client_name"], r["status"]) for r in out] == [
        ("Acme", "not_met"),
        ("Beta", "partly"),
        ("Aaa", "met"),
    ], "problems first, not by name"
    assert out[0]["matched_items"] == ["srv-02: 40 days"] and out[0]["matched_text"] is False
    assert out[1]["matched_items"] == [] and out[1]["matched_text"] is True
    assert [r["key"] for r in search_checks(checks, "quiet agents")] == ["huntress_quiet_agents"], "the check name matches with spaces"


def test_a_search_needs_two_characters_and_respects_the_limit_and_extra_spaces():
    from app.services.fleet_posture import search_checks

    checks = [_fc(f"C{i}", "k", "not_met", "disk full on host") for i in range(5)]
    assert search_checks(checks, "d") == [] and search_checks(checks, "  ") == []
    assert len(search_checks(checks, "  DISK   full ", limit=3)) == 3


def test_a_heavier_check_moves_the_score_further_and_the_counts_stay_plain_counts():
    from app.services.fleet_posture import summarize

    checks = [_fc("A", "backup", "not_met"), _fc("A", "patching", "met"), _fc("A", "av", "met")]
    assert summarize(checks)["score"] == 67, "(0 + 1 + 1) / 3"
    heavy = summarize(checks, {"backup": 3})
    assert heavy["score"] == 40, "(0*3 + 1 + 1) / (3 + 1 + 1)"
    assert (heavy["met"], heavy["not_met"]) == (2, 1)
    assert summarize(checks, {"backup": 99})["score"] == 29, "a weight above 5 counts as 5: 2 / 7"
    assert summarize(checks, {"backup": 0})["score"] == 67, "a weight below 1 counts as 1"
    assert summarize(checks, {"unrelated": 5})["score"] == 67


def test_the_breakdown_adds_up_to_the_points_lost_biggest_first_and_leaves_out_accepted_checks():
    from app.services.fleet_posture import score_breakdown

    checks = [
        _fc("A", "backup", "not_met"),
        _fc("A", "patching", "partly"),
        _fc("A", "av", "met"),
        _fc("A", "wan", "not_met", accepted=True),
    ]
    b = score_breakdown(checks)
    assert b["score"] == 50 and b["lost"] == 50.0, "(0 + .5 + 1) / 3 = 50%"
    assert [(r["key"], r["points_lost"]) for r in b["rows"]] == [("backup", 33.3), ("patching", 16.7)]
    heavy = score_breakdown(checks, {"backup": 3})
    assert [(r["key"], r["points_lost"], r["weight"]) for r in heavy["rows"]] == [("backup", 60.0, 3), ("patching", 10.0, 1)]
    assert round(sum(r["points_lost"] for r in heavy["rows"]), 1) == heavy["lost"] == 70.0
    assert score_breakdown([_fc("A", "k", "not_met", accepted=True)]) == {"score": None, "lost": 0.0, "rows": []}


def test_tool_scorecards_rank_the_tool_with_most_problems_first_and_count_clients_not_checks():
    from app.services.fleet_posture import tool_scorecards

    checks = [
        _fc("A", "k1", "not_met", source="slide"),
        _fc("A", "k2", "not_met", source="slide"),
        _fc("B", "k1", "met", source="slide"),
        _fc("A", "k3", "met", source="ninjaone"),
        _fc("B", "k3", "partly", source="ninjaone"),
        _fc("C", "k3", "not_met", source="ninjaone", accepted=True),
    ]
    out = tool_scorecards(checks)
    assert [(t["source"], t["checks"], t["percent_fine"], t["clients_with_problems"]) for t in out] == [
        ("slide", 3, 33, 1),
        ("ninjaone", 2, 75, 1),
    ]
    assert (out[0]["met"], out[0]["partly"], out[0]["not_met"]) == (1, 0, 2)
    assert tool_scorecards([]) == []


def test_similar_size_average_uses_only_clients_within_a_factor_of_two_and_with_a_score():
    from app.services.fleet_posture import similar_size_average

    others = {"a": (60, 80), "b": (45, 60), "c": (200, 10), "d": (10, 5), "e": (100, None), "f": (0, 99), "g": (90, 70)}
    out = similar_size_average(50, others)
    assert out == {
        "average": 70,
        "clients": 3,
    }, "a (60), b (45) and g (90) are within 25 to 100; c, d are not, e has no score, f has no machines"
    assert similar_size_average(0, others) == {"average": None, "clients": 0}
    assert similar_size_average(1000, others) == {"average": None, "clients": 0}


def test_a_change_is_new_worse_better_or_the_same_by_the_order_not_met_partly_met():
    from app.services.fleet_posture import classify_change

    assert classify_change("met", None) == "new"
    assert classify_change("not_met", "partly") == "worse"
    assert classify_change("partly", "met") == "worse"
    assert classify_change("met", "not_met") == "better"
    assert classify_change("partly", "not_met") == "better"
    assert classify_change("met", "met") == "same"
    assert classify_change("odd", "met") == "worse", "an unknown status is read as needing attention"


def test_a_tools_checks_are_only_that_tools_worst_first_without_fine_ones_unless_asked():
    def of(source, status, client="Acme", key="k", accepted=False):
        return FleetCheck(
            client_id=client.lower(), client_name=client, source=source, key=key, status=status, evidence="e", accepted=accepted
        )

    rows = [
        of("huntress", "met"),
        of("huntress", "partly", "Beta"),
        of("huntress", "not_met", "Zed"),
        of("threatmate", "not_met"),
        of("huntress", "not_met", "Acme", "b", accepted=True),
    ]
    got = tool_rows(rows, "huntress")
    assert [(r.client_name, r.status, r.accepted) for r in got] == [
        ("Zed", "not_met", False),
        ("Beta", "partly", False),
        ("Acme", "not_met", True),
    ]
    assert len(tool_rows(rows, "huntress", include_met=True)) == 4
    assert tool_rows(rows, "nothing") == []

from datetime import UTC, datetime, timedelta

from app.services.fleet_posture import BOARDS, FleetCheck, board_rows, coverage_matrix, rank_clients, stale_sources, summarize


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
    rows = [chk("met", "a", "Zed"), chk("partly", "a", "Beta"), chk("not_met", "a", "Zed"), chk("not_met", "other", "Acme"), chk("not_met", "a", "Acme", accepted=True), chk("not_met", "b", "Acme")]
    got = board_rows(rows, ["a", "b"])
    assert [(r.client_name, r.key, r.status, r.accepted) for r in got] == [("Acme", "b", "not_met", False), ("Zed", "a", "not_met", False), ("Beta", "a", "partly", False), ("Acme", "a", "not_met", True)]
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
    assert coverage_matrix([], {"z": "Zed"}) == {"tools": [], "clients": [{"client_id": "z", "client_name": "Zed", "tools": [], "missing": []}]}


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

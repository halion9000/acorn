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

"""The noise report: the ranking of rules whose alerts end with nothing done."""

from app.services import alert_noise as nz


def test_rules_are_ranked_by_how_many_alerts_ended_with_nothing_done_and_rules_with_none_are_left_out():
    rows = [
        {"rule": "Impossible travel", "total": 40, "quiet": 38, "with_ticket": 1},
        {"rule": "New device", "total": 100, "quiet": 12, "with_ticket": 30},
        {"rule": "All good", "total": 50, "quiet": 0, "with_ticket": 50},
        {"rule": "Empty", "total": 0, "quiet": 0, "with_ticket": 0},
        {"rule": "Chatty", "total": 38, "quiet": 38, "with_ticket": 0},
    ]
    out = nz.rank(rows)
    assert [r["rule"] for r in out] == ["Impossible travel", "Chatty", "New device"], "equal quiet counts: the busier rule first"
    assert out[0]["quiet_percent"] == 95 and out[0]["with_ticket"] == 1


def test_a_suggestion_needs_enough_alerts_and_almost_all_of_them_quiet():
    out = {r["rule"]: r for r in nz.rank([
        {"rule": "Mostly quiet", "total": 20, "quiet": 19},
        {"rule": "Few alerts", "total": 5, "quiet": 5},
        {"rule": "Half", "total": 20, "quiet": 10},
        {"rule": "Edge", "total": 10, "quiet": 9},
        {"rule": "", "total": 12, "quiet": 12},
    ])}
    assert "95% of its 20 alerts ended with nothing done" in out["Mostly quiet"]["suggestion"]
    assert out["Few alerts"]["suggestion"] is None and out["Half"]["suggestion"] is None
    assert out["Edge"]["suggestion"] is not None, "ten alerts, ninety percent: enough"
    assert "(no rule name)" in out and out["(no rule name)"]["quiet_percent"] == 100


def test_only_the_most_quiet_rules_are_listed():
    rows = [{"rule": f"r{i}", "total": 10 + i, "quiet": 1 + i} for i in range(30)]
    assert len(nz.rank(rows)) == nz.MAX_RULES
    assert nz.rank(rows)[0]["rule"] == "r29"
    assert nz.rank([]) == []

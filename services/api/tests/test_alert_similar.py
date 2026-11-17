"""Similar alerts: the reasons two alerts are alike, and the order of the matches."""

from datetime import UTC, datetime, timedelta

from app.services import alert_similar as sim

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def alert(id_, title="Login from new country", rule="r1", hosts=(), users=(), ips=(), age=1, severity="high", status="new"):
    return {"id": id_, "title": title, "rule_id": rule, "affected_hosts": list(hosts), "affected_users": list(users), "affected_ips": list(ips), "severity": severity, "status": status, "created_at": NOW - timedelta(hours=age)}


def test_the_reasons_name_the_rule_title_and_each_shared_host_user_or_address_ignoring_case():
    a = alert("a", hosts=["PC-1", "PC-2"], users=["Ann@x.com"], ips=["1.1.1.1"])
    b = alert("b", hosts=["pc-1"], users=["ann@x.com"], ips=["9.9.9.9"])
    assert sim.reasons(a, b) == ["same rule", "same title", "same host: pc-1", "same user: ann@x.com"]
    assert sim.reasons(a, alert("c", title="Other", rule="r2")) == []
    assert sim.reasons(a, alert("d", title="Other", rule=None, ips=["1.1.1.1"])) == ["same ip: 1.1.1.1"]


def test_no_reason_is_made_from_a_blank_rule_or_title_or_from_data_that_is_not_a_list():
    a = alert("a", title="", rule=None)
    assert sim.reasons(a, alert("b", title="", rule=None)) == []
    odd = {**alert("c"), "affected_hosts": "pc-1", "affected_users": None}
    assert sim.reasons({**alert("a", title="X", rule="z"), "affected_hosts": "pc-1"}, odd) == []


def test_the_best_matches_come_first_the_alert_itself_is_left_out_and_the_list_is_capped():
    this = alert("this", hosts=["pc-1"])
    cands = [
        alert("old-host", title="Different", rule="x", hosts=["pc-1"], age=2),
        alert("rule-title", age=5),
        alert("new-host", title="Different", rule="y", hosts=["pc-1"], age=1),
        alert("this"),
        alert("nothing", title="Unrelated", rule="q", hosts=["zz"]),
    ]
    assert [m["id"] for m in sim.rank(this, cands)] == ["rule-title", "new-host", "old-host"]
    many = [alert(f"m{i}", age=i + 1) for i in range(20)]
    assert len(sim.rank(this, many)) == sim.MAX_SHOWN
    assert [m["id"] for m in sim.rank(this, many, limit=2)] == ["m0", "m1"], "equal weight: the newest first"
    assert sim.rank(this, []) == []

"""The two fleet reports: Huntress agent versions and network firmware behind the newest of the same model (pure)."""

from app.services import device_reports as r


def test_versions_are_compared_by_their_numbers_not_as_text():
    assert r.version_key("1.10.2") > r.version_key("1.9.9")
    assert r.version_key("2026.3") > r.version_key("2025.12.1")
    assert r.version_key("v1.2-beta") == (1, 2)
    assert r.version_key("") == r.version_key(None) == (-1,)
    assert sorted(["1.9", "1.10", "1.2"], key=r.version_key) == ["1.2", "1.9", "1.10"]


def agent(version, client="Acme", host="PC", cb=None):
    return {"client": client, "hostname": host, "version": version, "last_callback": cb}


def test_the_huntress_spread_lists_versions_newest_first_and_marks_agents_more_than_two_releases_behind():
    devices = [agent("0.14.10", host="a"), agent("0.14.10", host="b"), agent("0.14.9", host="c"), agent("0.14.8", host="d"), agent("0.14.7", host="e", client="Birch"), agent("0.13.0", host="f", client="Acme"), agent("", host="g"), agent(None, host="h")]
    out = r.huntress_versions(devices)
    assert out["newest"] == "0.14.10" and out["agents"] == 6 and out["without_version"] == 2
    assert [(s["version"], s["agents"], s["releases_behind"]) for s in out["spread"]] == [("0.14.10", 2, 0), ("0.14.9", 1, 1), ("0.14.8", 1, 2), ("0.14.7", 1, 3), ("0.13.0", 1, 4)]
    assert [(o["hostname"], o["releases_behind"]) for o in out["old"]] == [("f", 4), ("e", 3)], "two behind is not old; three or more is, the furthest behind first"


def test_with_no_agent_versions_there_is_nothing_to_report():
    out = r.huntress_versions([agent(None), agent("  ")])
    assert out == {"newest": None, "agents": 0, "without_version": 2, "spread": [], "old": []}


def net(model, fw, host="sw", client="Acme", maker="Cisco", kind="switch"):
    return {"client": client, "hostname": host, "manufacturer": maker, "model": model, "device_type": kind, "firmware": fw}


def test_network_devices_behind_are_those_older_than_another_of_the_same_make_and_model():
    devices = [net("C9200", "17.9.4", "a"), net("C9200", "17.12.1", "b", client="Birch"), net("C9200", "17.12.1", "c"), net("C9200", "17.9.4", "d"), net("SG350", "2.5.9", "e"), net("SG350", "", "f"), net("X", "1.0", "g", maker="Meraki"), net("X", "9.0", "h", maker="Ubiquiti")]
    out = r.firmware_behind(devices)
    assert [(m["manufacturer"], m["model"], m["newest"], m["devices"], m["behind"]) for m in out["models"]] == [("Cisco", "C9200", "17.12.1", 4, 2)], "one version only, no firmware and a different make are not compared"
    assert [(d["hostname"], d["firmware"], d["newest"]) for d in out["devices"]] == [("a", "17.9.4", "17.12.1"), ("d", "17.9.4", "17.12.1")]
    assert r.firmware_behind([]) == {"models": [], "devices": []}

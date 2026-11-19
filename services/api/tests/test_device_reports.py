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


def test_offline_since_starts_when_first_seen_offline_is_kept_while_offline_and_cleared_when_back():
    from datetime import UTC, datetime

    t0, t1, t2 = datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 5, tzinfo=UTC), datetime(2026, 11, 9, tzinfo=UTC)
    first = r.carry_offline_since(None, {"status": "OFFLINE", "mac": "aa"}, t0)
    assert first["offline_since"] == t0.isoformat() and first["mac"] == "aa"
    again = r.carry_offline_since(first, {"status": "offline"}, t1)
    assert again["offline_since"] == t0.isoformat(), "still offline: the clock keeps its first time"
    assert "offline_since" not in r.carry_offline_since(again, {"status": "online"}, t2), "back online clears it"
    assert r.carry_offline_since({"offline_since": "stale"}, {"status": "online"}, t2) == {"status": "online"}
    forged = r.carry_offline_since(None, {"status": "online", "offline_since": "2020-01-01T00:00:00+00:00"}, t2)
    assert "offline_since" not in forged, "a tool cannot set the clock itself"
    assert not r.is_offline(None) and not r.is_offline({"status": None}) and r.is_offline({"status": " Disconnected "})


def test_devices_offline_for_more_than_a_week_are_listed_longest_first():
    from datetime import UTC, datetime

    now = datetime(2026, 11, 18, tzinfo=UTC)

    def dev(host, since, client="Acme"):
        return {"client": client, "hostname": host, "model": "U6", "offline_since": since}

    out = r.offline_for_days([dev("new", "2026-11-14T00:00:00+00:00"), dev("old", "2026-10-01T00:00:00+00:00"), dev("mid", "2026-11-05T00:00:00Z", "Birch"), dev("none", None), dev("bad", "x"), dev("edge", "2026-11-11T00:00:00+00:00")], now)
    assert [(d["hostname"], d["days_offline"]) for d in out] == [("old", 48), ("mid", 13)], "exactly seven days is not more than a week; no usable time is left out"


def dev(vendor, tenant, client, serial, host="PC"):
    return {"vendor": vendor, "tenant": tenant, "client": client, "serial": serial, "hostname": host}


def test_a_machine_filed_under_different_clients_in_huntress_and_ninjaone_is_a_mismatch():
    out = r.org_mismatches(
        [
            dev("ninjaone", "t1", "Acme", "5CG1234567", "ACME-PC1"),
            dev("huntress", "t2", "Birch", "5cg 1234567", "ACME-PC1"),
            dev("ninjaone", "t1", "Acme", "5CG7654321", "ACME-PC2"),
            dev("huntress", "t1", "Acme", "5CG7654321", "ACME-PC2"),
        ]
    )
    assert out == [{"serial": "5CG1234567", "hostname": "ACME-PC1", "ninjaone_client": "Acme", "huntress_client": "Birch"}]


def test_a_second_copy_elsewhere_is_not_a_mismatch_when_the_same_client_holds_both_tools_and_placeholders_never_match():
    out = r.org_mismatches(
        [
            dev("ninjaone", "t1", "Acme", "5CG1234567"),
            dev("huntress", "t1", "Acme", "5CG1234567"),
            dev("huntress", "t9", "Stray", "5CG1234567"),
            dev("ninjaone", "t1", "Acme", "To Be Filled By O.E.M."),
            dev("huntress", "t2", "Birch", "To Be Filled By O.E.M."),
            dev("ninjaone", "t1", "Acme", "9ZZ1111111"),
        ]
    )
    assert out == []


def test_the_mismatch_text_lists_machines_and_is_none_when_there_are_none():
    assert r.org_mismatch_text([]) is None
    subject, text = r.org_mismatch_text([{"serial": "S1234567", "hostname": "PC1", "ninjaone_client": "Acme", "huntress_client": "Birch"}])
    assert subject.startswith("1 machine filed under different clients")
    assert "PC1: NinjaOne says Acme, Huntress says Birch" in text

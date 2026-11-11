"""The same alert seen at other clients: one entry per client, newest first, capped, and nothing for an organization with no other tenant."""

from datetime import UTC, datetime, timedelta

from app.services import alert_other_clients as oc

T0 = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def row(tenant, alert_id, hours_ago):
    return {"tenant_id": tenant, "id": alert_id, "created_at": T0 - timedelta(hours=hours_ago)}


def test_one_entry_per_client_with_its_count_and_newest_alert_newest_client_first():
    out = oc.summarize(
        [row("a", "a-old", 20), row("b", "b1", 5), row("a", "a-new", 1), row("a", "a-mid", 10)],
        {"a": "Acme", "b": "Birch"},
    )
    assert out["total"] == 4 and out["client_count"] == 2 and out["window_hours"] == 24
    assert [c["name"] for c in out["clients"]] == ["Acme", "Birch"], "Acme's newest alert is the most recent"
    acme = out["clients"][0]
    assert acme["count"] == 3 and acme["newest_alert_id"] == "a-new" and acme["client_id"] == "a"
    assert acme["newest_at"] == (T0 - timedelta(hours=1)).isoformat()
    assert out["clients"][1] == {
        "client_id": "b",
        "name": "Birch",
        "count": 1,
        "newest_at": (T0 - timedelta(hours=5)).isoformat(),
        "newest_alert_id": "b1",
    }


def test_a_client_with_no_known_name_is_still_listed_and_a_row_with_no_date_sorts_last():
    out = oc.summarize([{"tenant_id": "x", "id": "x1", "created_at": None}, row("b", "b1", 3)], {"b": "Birch"})
    assert [c["name"] for c in out["clients"]] == ["Birch", "Unknown client"]
    assert out["clients"][1]["newest_at"] is None and out["clients"][1]["newest_alert_id"] is None and out["clients"][1]["count"] == 1


def test_the_list_is_capped_and_the_count_still_says_how_many_clients():
    rows = [row(f"t{i}", f"a{i}", i) for i in range(oc.CLIENT_CAP + 5)]
    out = oc.summarize(rows, {})
    assert len(out["clients"]) == oc.CLIENT_CAP and out["client_count"] == oc.CLIENT_CAP + 5
    assert out["clients"][0]["newest_alert_id"] == "a0"


def test_nothing_is_an_empty_answer_of_the_same_shape():
    assert oc.nothing() == oc.summarize([], {})

from datetime import UTC, datetime

from app.services import role_history as rh


def test_each_kind_of_role_change_has_a_plain_sentence():
    assert (
        rh.change_sentence("role:created", {"name": "Tier 1", "permissions": ["alerts:read", "cases:read"]})
        == "Created with alerts:read, cases:read."
    )
    assert rh.change_sentence("role:created", {"permissions": []}) == "Created with no permissions."
    updated = {
        "name": {"before": "Tier 1", "after": "Analyst"},
        "permissions_added": ["cases:write"],
        "permissions_removed": ["users:read"],
    }
    assert rh.change_sentence("role:updated", updated) == "Renamed from Tier 1 to Analyst. Gained cases:write. Lost users:read."
    assert (
        rh.change_sentence("role:updated", {"name": {"before": "A", "after": "A"}, "permissions_added": [], "permissions_removed": []})
        == "Saved with no change."
    )
    assert rh.change_sentence("role:assigned", {"user_id": "u1", "role_name": "Analyst"}) == "Given to user u1."
    assert rh.change_sentence("role:revoked", {"user_id": "u1"}) == "Taken from user u1."
    assert rh.change_sentence("role:deleted", {"name": "x", "permissions": []}) == "Deleted."


def test_a_long_list_is_cut_with_a_count_and_an_odd_payload_never_raises():
    many = [f"p{i}:read" for i in range(9)]
    assert rh.change_sentence("role:created", {"permissions": many}).endswith("p5:read and 3 more.")
    assert rh.change_sentence("role:assigned", None) == "Given to a user."
    assert rh.change_sentence("role:updated", "not a dict") == "Saved with no change."
    assert rh.change_sentence("role:something_new", {"a": 1}) == "role:something_new"
    assert rh.change_sentence("role:updated", {"permissions_added": "oops"}) == "Saved with no change."


def test_rows_keep_the_newest_ten_in_order_with_who_and_when():
    at = datetime(2026, 11, 11, 9, 30, tzinfo=UTC)
    entries = [{"created_at": at, "actor_email": f"a{i}@x.test", "action": "role:deleted", "changes": {}} for i in range(14)]
    out = rh.rows(entries)
    assert len(out) == rh.SHOWN == 10
    assert out[0] == {"at": "2026-11-11T09:30:00+00:00", "by": "a0@x.test", "action": "role:deleted", "summary": "Deleted."}
    assert rh.rows([{"created_at": None, "actor_email": "", "action": "role:revoked"}]) == [
        {"at": None, "by": None, "action": "role:revoked", "summary": "Taken from a user."}
    ]

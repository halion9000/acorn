"""Standing approvals: only reversible kinds, client-bound, never when revoked or past the date; and when Undo is possible."""

from datetime import UTC, datetime, timedelta

from app.api.v1.endpoints.approvals import UNDO_HOURS, undo_problem
from app.services import standing_approvals as sa

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def standing(**over):
    base = {"action_type": "add_case_comment", "client_id": None, "expires_at": NOW + timedelta(days=30), "revoked_at": None}
    return {**base, **over}


def test_only_reversible_kinds_can_be_given_a_standing_approval():
    assert sa.refusal("add_case_comment") is None
    assert sa.refusal(" Close_Alert ") is None
    for kind in ("isolate_host", "disable_user_account", "delete_object", "block_ip", "firewall_rule_add", "revoke_session", "unknown"):
        assert "needs a person" in (sa.refusal(kind) or ""), kind


def test_a_card_matches_by_kind_and_a_client_approval_needs_the_same_client_on_the_card():
    card = {"type": "add_case_comment", "client_id": "acme"}
    assert sa.matches(standing(), card, "t", NOW), "an approval for all clients covers any client"
    assert sa.matches(standing(client_id="acme"), card, "t", NOW)
    assert not sa.matches(standing(client_id="beta"), card, "t", NOW)
    assert not sa.matches(standing(client_id="acme"), {"type": "add_case_comment"}, "t", NOW), "a card naming no client never matches a client approval"
    assert not sa.matches(standing(), {"type": "close_alert"}, "t", NOW), "another kind of action"


def test_revoked_expired_and_destructive_never_match_even_if_a_row_somehow_exists():
    card = {"type": "add_case_comment"}
    assert not sa.matches(standing(revoked_at=NOW - timedelta(minutes=1)), card, "t", NOW)
    assert not sa.matches(standing(expires_at=NOW), card, "t", NOW), "ends at the end date, not after it"
    assert not sa.matches(standing(expires_at=NOW - timedelta(days=1)), card, "t", NOW)
    assert not sa.matches(standing(action_type="isolate_host"), {"type": "isolate_host"}, "t", NOW), "a destructive kind in the table still never matches"


def test_the_client_is_read_from_client_id_or_client_tenant_id():
    assert sa.client_of({"client_id": " acme "}) == "acme"
    assert sa.client_of({"client_tenant_id": 5}) == "5"
    assert sa.client_of({}) is None and sa.client_of(None) is None and sa.client_of({"client_id": ""}) is None


def test_undo_is_possible_once_within_24_hours_for_an_approved_action_that_said_how():
    undo = {"how": "reopen the alert"}
    ok_time = NOW - timedelta(hours=UNDO_HOURS - 1)
    assert undo_problem("approved", undo, ok_time, None, NOW) is None
    assert "already undone" in undo_problem("approved", undo, ok_time, NOW, NOW)
    assert "Only an approved" in undo_problem("pending", undo, ok_time, None, NOW)
    assert "how it can be reversed" in undo_problem("approved", None, ok_time, None, NOW)
    assert "within 24 hours" in undo_problem("approved", undo, NOW - timedelta(hours=UNDO_HOURS + 1), None, NOW)
    assert "within 24 hours" in undo_problem("approved", undo, None, None, NOW)

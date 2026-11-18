"""Who may ask for and decide a policy version's approval (pure rules)."""

from datetime import UTC, datetime, timedelta

from app.services import policy_approval as pap

T0 = datetime(2026, 11, 17, 12, tzinfo=UTC)


def test_a_request_needs_a_real_other_person_and_no_request_already_waiting():
    assert pap.request_problem("amy@x.com", "bob@x.com", False, True) == ""
    assert "no such version" in pap.request_problem("amy@x.com", "bob@x.com", False, False)
    assert "e-mail" in pap.request_problem("amy@x.com", "Bob", False, True)
    assert "e-mail" in pap.request_problem("amy@x.com", None, False, True)
    assert "own request" in pap.request_problem("Amy@X.com", " amy@x.COM ", False, True), "the same person in another spelling is still the same person"
    assert "already waiting" in pap.request_problem("amy@x.com", "bob@x.com", True, True)


def test_only_the_named_approver_decides_once_and_a_rejection_says_why():
    assert pap.decision_problem("bob@x.com", "Bob@x.com", "pending", "approved", "") == ""
    assert pap.decision_problem("bob@x.com", "bob@x.com", "pending", "rejected", "too vague about backups") == ""
    assert "Only the person named" in pap.decision_problem("amy@x.com", "bob@x.com", "pending", "approved", "")
    assert "Only the person named" in pap.decision_problem(None, "bob@x.com", "pending", "approved", "")
    assert "already been decided" in pap.decision_problem("bob@x.com", "bob@x.com", "approved", "rejected", "x")
    assert "Say why" in pap.decision_problem("bob@x.com", "bob@x.com", "pending", "rejected", "   ")
    assert "Choose" in pap.decision_problem("bob@x.com", "bob@x.com", "pending", "maybe", "")


def test_a_versions_status_is_that_of_its_newest_request():
    rows = [
        pap.Approval("1", 1, "b", "a", T0, "rejected"),
        pap.Approval("2", 1, "b", "a", T0 + timedelta(days=1), "approved"),
        pap.Approval("3", 2, "b", "a", T0, "pending"),
        pap.Approval("4", 3, "b", "a", T0, "approved"),
        pap.Approval("5", 3, "b", "a", T0 + timedelta(hours=1), "pending"),
    ]
    assert pap.status_by_version(rows) == {1: "approved", 2: "pending", 3: "pending"}
    assert pap.status_by_version([]) == {}

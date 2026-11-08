"""The client's status page: what it may show, and when a link may be used."""

from datetime import UTC, datetime, timedelta

from app.services import client_status as cs

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def test_a_link_works_only_when_live_reviewed_and_not_revoked_or_expired():
    live = {"revoked_at": None, "expires_at": NOW + timedelta(days=1), "reviewed_at": NOW}
    assert cs.link_problem(live, NOW) is None
    assert cs.link_problem({**live, "revoked_at": NOW}, NOW) == "revoked"
    assert cs.link_problem({**live, "expires_at": NOW}, NOW) == "expired"
    assert cs.link_problem({**live, "reviewed_at": None}, NOW) == "not reviewed"
    assert cs.link_problem({**live, "expires_at": None}, NOW) == "expired"


def test_a_secret_is_long_url_safe_and_only_its_hash_is_kept():
    a, b = cs.new_token(), cs.new_token()
    assert a != b and cs.well_formed(a) and len(a) >= 40
    assert cs.hash_token(a) != a and len(cs.hash_token(a)) == 64 and cs.hash_token(a) == cs.hash_token(a)
    for bad in ("", "short", "has space " * 6, "x" * 100, "../" * 20):
        assert not cs.well_formed(bad)


POSTURE = {
    "client_name": "Acme",
    "generated_at": NOW,
    "devices": {"devices": 50, "not_in_huntress": 5, "needs_attention": 7, "stale_agents": 2, "offline": 3},
    "identity": {"people": 80, "with_mfa": 60, "not_required": 10, "without_mfa": 10, "admins_without_mfa": 1},
    "alerts": {"open": 12, "critical": 3, "high": 4, "without_ticket": 5},
    "open_cases": 2,
    "tools": [{"vendor": "huntress", "vendor_client_id": "SECRET-ID-1", "vendor_client_name": "Acme Inc"}, {"vendor": "ninjaone", "vendor_client_id": "9", "vendor_client_name": None}, {"vendor": "weird-tool", "vendor_client_id": "1"}, {"vendor": "huntress", "vendor_client_id": "2"}],
    "tool_checks": {"threatmate": {"checks": [{"key": "k", "status": "not_met", "evidence": "internal host DC01 has a password in plain text"}]}},
}


def test_the_page_carries_counts_percentages_and_plain_labels_and_nothing_internal():
    page = cs.project(POSTURE)
    assert page["client_name"] == "Acme"
    assert page["devices"] == {"total": 50, "protected": 45, "percent": 90}
    assert page["people"] == {"total": 80, "protected": 70, "percent": 88}
    assert page["alerts"] == {"open": 12, "being_worked_on": 7}
    assert page["tools"] == ["Device management and patching (NinjaOne)", "Managed endpoint detection (Huntress)"], "known tools only, once each, plain labels"
    text = repr(page)
    for secret in ("SECRET-ID-1", "Acme Inc", "DC01", "password", "weird-tool", "critical", "needs_attention", "stale"):
        assert secret not in text, secret


def test_missing_numbers_are_not_guessed():
    page = cs.project({"client_name": None, "generated_at": NOW, "devices": {}, "identity": None, "alerts": {}, "tools": []})
    assert page["devices"] == {"total": 0, "protected": 0, "percent": None}
    assert page["people"] is None
    assert page["alerts"] == {"open": 0, "being_worked_on": 0}
    assert page["tools"] == [] and page["client_name"] == ""
    assert cs.percent(5, 0) is None and cs.percent(7, 3) == 100

"""The administrator-without-multi-factor rule: it fires for an enabled admin nothing protects, and for no one else; it repeats monthly, not daily."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace as NS

from app.services.identity_detections import alert_id, alert_values, detect_admins_mfa_not_required, detect_admins_without_mfa

NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
TENANT = uuid.uuid4()


def user(upn, **over):
    base = {
        "upn": upn,
        "enabled": True,
        "admin": True,
        "user_type": "Member",
        "registered": False,
        "capable": False,
        "methods": None,
        "per_user": None,
        "ca_enforced": False,
        "security_defaults": False,
        "source": "cipp",
    }
    base.update(over)
    return NS(**base)


def someone_protected():
    return user(
        "amy@x.com", admin=False, registered=True, methods="authenticator", ca_enforced=True
    )  # makes registration "known" for the client


def test_an_enabled_admin_with_no_second_factor_raises_a_high_alert_naming_them():
    out = detect_admins_without_mfa([someone_protected(), user("Boss@X.com")], NOW)
    assert len(out) == 1
    f = out[0]
    assert (f.rule_id, f.severity, f.users) == ("aisoc-id-admin-no-mfa", "high", ["boss@x.com"])
    assert ("Second factor registered or required", "no") in f.fields and "boss@x.com" in f.title


def test_an_admin_who_registered_one_that_nothing_requires_is_not_raised_the_page_calls_that_registered_not_required():
    assert detect_admins_without_mfa([user("amy@x.com", registered=True, methods="authenticator")], NOW) == []


def test_an_admin_who_is_covered_is_not_raised():
    covered = [
        user("a@x.com", registered=True, methods="authenticator", ca_enforced=True),
        user("b@x.com", registered=True, methods="authenticator", per_user="enforced"),
    ]
    assert detect_admins_without_mfa(covered, NOW) == []


def test_when_microsoft_does_not_say_who_registered_security_defaults_count_as_covered():
    users = [
        user("a@x.com", security_defaults=True),
        user("b@x.com", admin=False),
    ]  # nobody shows a method: registration is unknown, so being required is what counts
    assert detect_admins_without_mfa(users, NOW) == []
    assert len(detect_admins_without_mfa([user("a@x.com"), user("b@x.com", admin=False)], NOW)) == 1  # nothing requires it either


def test_guests_disabled_accounts_and_non_admins_are_left_out():
    users = [
        someone_protected(),
        user("g@partner.com", user_type="Guest"),
        user("old@x.com", enabled=False),
        user("staff@x.com", admin=False),
    ]
    assert detect_admins_without_mfa(users, NOW) == []


def test_a_google_admin_is_judged_by_what_google_reports():
    g = user("g@x.com", source="threatmate", registered=False)
    assert len(detect_admins_without_mfa([g], NOW)) == 1
    assert detect_admins_without_mfa([user("g@x.com", source="threatmate", registered=True, methods="2sv")], NOW) == []


def test_the_same_admin_gives_the_same_alert_all_month_and_a_new_one_next_month():
    a = detect_admins_without_mfa([user("boss@x.com")], NOW)[0]
    same_month = detect_admins_without_mfa([user("boss@x.com")], datetime(2026, 11, 28, tzinfo=UTC))[0]
    next_month = detect_admins_without_mfa([user("boss@x.com")], datetime(2026, 12, 2, tzinfo=UTC))[0]
    assert alert_id(TENANT, a) == alert_id(TENANT, same_month) != alert_id(TENANT, next_month)


def test_the_alert_row_is_an_identity_alert_for_that_client():
    f = detect_admins_without_mfa([user("boss@x.com")], NOW)[0]
    row = alert_values(TENANT, f, NOW)
    assert (
        row["tenant_id"] == TENANT
        and row["category"] == "identity"
        and row["severity"] == "high"
        and row["affected_users"] == ["boss@x.com"]
    )
    assert "aisoc-id-admin-no-mfa" in row["tags"]


def test_a_flood_is_capped():
    many = [user(f"a{i}@x.com") for i in range(120)]
    assert len(detect_admins_without_mfa(many, NOW)) == 50


def test_an_admin_with_mfa_registered_but_not_required_gets_a_medium_alert_and_is_not_also_called_unprotected():
    users = [user("amy@x.com", registered=True, methods="authenticator")]  # registered, nothing requires it
    assert detect_admins_without_mfa(users, NOW) == []
    out = detect_admins_mfa_not_required(users, NOW)
    assert len(out) == 1
    f = out[0]
    assert (f.rule_id, f.severity, f.users) == ("aisoc-id-admin-mfa-not-required", "medium", ["amy@x.com"])
    assert ("Second factor registered", "yes") in f.fields and ("Second factor required", "no") in f.fields


def test_an_admin_who_is_required_to_use_it_or_has_none_is_not_in_the_not_required_list():
    covered = user("a@x.com", registered=True, methods="authenticator", ca_enforced=True)
    none = user("b@x.com")
    assert detect_admins_mfa_not_required([covered, someone_protected()], NOW) == []
    assert detect_admins_mfa_not_required([someone_protected(), none], NOW) == []  # no second factor at all is the high alert's job


def test_the_not_required_rule_leaves_out_guests_disabled_and_non_admins_and_repeats_monthly():
    users = [
        user("g@partner.com", registered=True, methods="x", user_type="Guest"),
        user("old@x.com", registered=True, methods="x", enabled=False),
        user("staff@x.com", registered=True, methods="x", admin=False),
    ]
    assert detect_admins_mfa_not_required(users, NOW) == []
    a = detect_admins_mfa_not_required([user("amy@x.com", registered=True, methods="x")], NOW)[0]
    later = detect_admins_mfa_not_required([user("amy@x.com", registered=True, methods="x")], datetime(2026, 12, 3, tzinfo=UTC))[0]
    assert alert_id(TENANT, a) != alert_id(TENANT, later)
    assert alert_id(TENANT, a) != alert_id(
        TENANT, detect_admins_without_mfa([user("amy@x.com")], NOW)[0]
    ), "the two rules never share an alert"

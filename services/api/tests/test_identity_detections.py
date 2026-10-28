"""The identity rules raise an alert for a clear pattern in the sign-ins and directory audits CORE collects, and for nothing else; a repeat never raises a second alert."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from app.services.identity_detections import (
    Finding,
    alert_id,
    alert_values,
    detect_ca_policy_change,
    detect_device_code,
    detect_failed_after_revoke,
    detect_impossible_travel,
    detect_mass_deletion,
    detect_privileged_role_change,
    detect_rare_country,
)

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def signin(i, user="a@x.com", country="US", at=T0, success=True, interactive=True, mfa=True, ip="1.1.1.1", city="Austin"):
    return NS(
        source_id=f"s{i}",
        user_principal=user,
        country=country,
        occurred_at=at,
        success=success,
        interactive=interactive,
        mfa=mfa,
        ip_address=ip,
        city=city,
        app="Outlook",
    )


def audit(i, activity, actor="admin@x.com", target="u@x.com", at=T0, success=True, actor_is_app=False, target_type="User"):
    return NS(
        source_id=f"a{i}",
        activity=activity,
        actor=actor,
        target=target,
        occurred_at=at,
        success=success,
        actor_is_app=actor_is_app,
        actor_ip="2.2.2.2",
        target_type=target_type,
    )


# ---- rare country ------------------------------------------------------------------------------------------------------------------------------------------------


def test_a_country_the_tenant_has_not_been_seen_in_raises_one_alert_and_judges_nothing_on_a_thin_history():
    base = {"US", "CA"}
    found = detect_rare_country([signin(1, country="RO"), signin(2, country="US")], base, 500)
    assert [f.title for f in found] == ["Sign-in from an unusual country - RO"]
    assert found[0].severity == "medium" and found[0].tactic == "Initial Access"
    assert detect_rare_country([signin(1, country="RO")], base, 49) == [], "under 50 sign-ins of history is no baseline"


def test_no_multi_factor_makes_it_high_and_failed_background_or_unknown_country_sign_ins_never_count():
    assert detect_rare_country([signin(1, country="RO", mfa=False)], {"US"}, 500)[0].severity == "high"
    for r in (signin(1, country="RO", success=False), signin(2, country="RO", interactive=False), signin(3, country=None)):
        assert detect_rare_country([r], {"US"}, 500) == []


def test_one_alert_per_person_and_country_in_a_batch():
    rows = [signin(1, country="RO"), signin(2, country="RO", at=T0 + timedelta(minutes=5)), signin(3, user="b@x.com", country="RO")]
    assert len(detect_rare_country(rows, {"US"}, 500)) == 2


# ---- impossible travel -------------------------------------------------------------------------------------------------------------------------------------------


def test_two_countries_within_an_hour_is_travel_and_an_hour_and_a_minute_is_not():
    a, b = signin(1, country="US"), signin(2, country="RO", at=T0 + timedelta(minutes=40))
    found = detect_impossible_travel([a, b], {"s2"})
    assert [f.title for f in found] == ["Impossible travel - US to RO"] and found[0].severity == "high"
    assert detect_impossible_travel([a, signin(2, country="RO", at=T0 + timedelta(minutes=61))], {"s2"}) == []


def test_same_country_a_failed_sign_in_or_an_old_pair_never_raise_it():
    def later(**k):
        return signin(2, at=T0 + timedelta(minutes=10), **k)

    assert detect_impossible_travel([signin(1), later(country="US")], {"s2"}) == []
    assert detect_impossible_travel([signin(1), later(country="RO", success=False)], {"s2"}) == []
    assert detect_impossible_travel([signin(1), later(country="RO")], set()) == [], "the pair was judged when its later sign-in was new"


# ---- audits ------------------------------------------------------------------------------------------------------------------------------------------------------


def test_failed_sign_ins_after_a_revoke_need_three_inside_two_hours():
    revoke = audit(1, "Revoke user sessions", target="U@X.com")
    fails = [signin(i, user="u@x.com", success=False, at=T0 + timedelta(minutes=10 * i), ip=f"9.9.9.{i}") for i in (1, 2, 3)]
    found = detect_failed_after_revoke([revoke], fails)
    assert [f.title for f in found] == ["Failed sign-ins after sessions were revoked"]
    assert detect_failed_after_revoke([revoke], fails[:2]) == []
    late = [signin(i, user="u@x.com", success=False, at=T0 + timedelta(hours=3, minutes=i)) for i in (1, 2, 3)]
    assert detect_failed_after_revoke([revoke], late) == []
    assert detect_failed_after_revoke([audit(2, "Update user")], fails) == []


def test_ten_deletions_in_fifteen_minutes_is_mass_deletion_and_nine_or_a_slow_pace_is_not():
    burst = [audit(i, "Delete user", at=T0 + timedelta(minutes=i)) for i in range(10)]
    assert [f.title for f in detect_mass_deletion(burst)] == ["Mass deletion: 10 users or groups deleted"]
    assert detect_mass_deletion(burst[:9]) == []
    slow = [audit(i, "Delete group", at=T0 + timedelta(minutes=10 * i)) for i in range(10)]
    assert detect_mass_deletion(slow) == []
    assert detect_mass_deletion([audit(i, "Delete user", success=False, at=T0 + timedelta(minutes=i)) for i in range(10)]) == []


def test_a_role_addition_and_a_conditional_access_change_are_flagged_and_an_app_actor_or_a_delete_is_worse():
    assert detect_privileged_role_change([audit(1, "Add member to role")])[0].severity == "medium"
    assert detect_privileged_role_change([audit(1, "Add member to role", actor="Some app", actor_is_app=True)])[0].severity == "high"
    assert detect_privileged_role_change([audit(1, "Remove member from role"), audit(2, "Update user")]) == []
    assert detect_ca_policy_change([audit(1, "Update conditional access policy", target="Require MFA")])[0].severity == "medium"
    assert detect_ca_policy_change([audit(1, "Delete conditional access policy", target="Require MFA")])[0].severity == "high"
    assert detect_ca_policy_change([audit(1, "Update user")]) == []


# ---- the alert ---------------------------------------------------------------------------------------------------------------------------------------------------


def _finding(key="k"):
    return Finding(
        "aisoc-id-x",
        "Rule",
        "Title",
        "high",
        "Initial Access",
        "T1078",
        key,
        T0,
        "Summary sentence.",
        [("Person", "a@x.com"), ("Country", "RO")],
        ["a@x.com"],
        ["1.1.1.1"],
        ["s1"],
    )


def test_the_alert_has_a_fixed_id_per_client_and_finding_and_the_tactic_set():
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    assert alert_id(t1, _finding()) == alert_id(t1, _finding())
    assert alert_id(t1, _finding()) != alert_id(t2, _finding()) and alert_id(t1, _finding("a")) != alert_id(t1, _finding("b"))
    v = alert_values(t1, _finding(), T0)
    assert v["mitre_tactics"] == ["Initial Access"] and v["mitre_techniques"] == ["T1078"]
    assert v["description"] == "Summary sentence.\n\nPerson: a@x.com\nCountry: RO"
    assert v["affected_users"] == ["a@x.com"] and v["severity"] == "high" and v["connector_type"] == "cipp"


# ---- device code -------------------------------------------------------------------------------------------------------------------------------------------------


def coded(i, **over):
    row = signin(i, **over)
    row.auth_protocol, row.transfer_method, row.resource = "deviceCode", "deviceCodeFlow", "Microsoft Graph"
    return row


def test_a_successful_device_code_sign_in_raises_one_alert_naming_the_service_and_the_person():
    found = detect_device_code([coded(1), signin(2)])
    assert [f.title for f in found] == ["Device-code sign-in - a@x.com"]
    assert found[0].severity == "medium" and found[0].technique == "T1078"
    assert ("Service", "Microsoft Graph") in found[0].fields


def test_either_signal_counts_and_no_multi_factor_makes_it_high():
    only_protocol = signin(1)
    only_protocol.auth_protocol, only_protocol.transfer_method = "deviceCode", None
    only_transfer = signin(2)
    only_transfer.auth_protocol, only_transfer.transfer_method = None, "deviceCodeFlow"
    assert len(detect_device_code([only_protocol, only_transfer])) == 2
    assert detect_device_code([coded(3, mfa=False)])[0].severity == "high"


def test_failed_and_ordinary_sign_ins_and_rows_with_no_protocol_fields_are_ignored():
    plain = signin(1)  # a row stored before the columns existed has no such attributes at all
    assert detect_device_code([plain, coded(2, success=False)]) == []


def test_each_device_code_sign_in_has_its_own_alert_id():
    a, b = detect_device_code([coded(1), coded(2)])
    tenant = uuid.uuid4()
    assert alert_id(tenant, a) == alert_id(tenant, a), "a repeat is a no-op"
    assert alert_id(tenant, a) != alert_id(tenant, b)

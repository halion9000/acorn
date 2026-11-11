"""Two more identity rules: a long-quiet account active again from a new country, and a burst of outside guests invited by one person."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from app.services.identity_detections import DORMANT_DAYS, GUEST_BURST, detect_dormant_active, detect_guest_burst

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def signin(user="amy@x.com", country="RO", ok=True, interactive=True, mfa=None, at=NOW):
    return NS(
        source_id=f"s-{user}-{country}",
        user_principal=user,
        success=ok,
        interactive=interactive,
        country=country,
        city="Bucharest",
        ip_address="9.9.9.9",
        mfa=mfa,
        occurred_at=at,
    )


LONG_AGO = NOW - timedelta(days=400)


def test_a_person_quiet_for_sixty_days_signing_in_from_a_country_they_never_used_is_flagged():
    found = detect_dormant_active([signin()], {"amy@x.com": NOW - timedelta(days=90)}, {"amy@x.com": {"US"}}, LONG_AGO)
    assert len(found) == 1
    f = found[0]
    assert (f.rule_id, f.severity, f.technique) == ("aisoc-id-dormant-active", "medium", "T1078")
    assert "90 days" in f.summary and "RO" in f.summary
    assert ("Quiet for", "90 days") in f.fields


def test_no_second_factor_makes_it_high():
    found = detect_dormant_active([signin(mfa=False)], {"amy@x.com": NOW - timedelta(days=90)}, {"amy@x.com": {"US"}}, LONG_AGO)
    assert found[0].severity == "high"


def test_a_country_the_person_has_used_before_is_a_return_from_leave_not_an_alert():
    assert detect_dormant_active([signin(country="US")], {"amy@x.com": NOW - timedelta(days=90)}, {"amy@x.com": {"US"}}, LONG_AGO) == []


def test_a_person_active_within_sixty_days_is_not_dormant():
    assert detect_dormant_active([signin()], {"amy@x.com": NOW - timedelta(days=DORMANT_DAYS - 1)}, {"amy@x.com": {"US"}}, LONG_AGO) == []


def test_a_person_never_seen_before_is_not_called_dormant():
    assert detect_dormant_active([signin()], {}, {}, LONG_AGO) == []


def test_when_the_clients_history_is_too_short_nobody_can_be_called_dormant():
    short = NOW - timedelta(days=30)
    assert detect_dormant_active([signin()], {"amy@x.com": NOW - timedelta(days=90)}, {"amy@x.com": {"US"}}, short) == []
    assert detect_dormant_active([signin()], {"amy@x.com": NOW - timedelta(days=90)}, {"amy@x.com": {"US"}}, None) == []


def test_a_failed_or_background_sign_in_or_one_with_no_country_does_not_count():
    last = {"amy@x.com": NOW - timedelta(days=90)}
    seen = {"amy@x.com": {"US"}}
    for row in (signin(ok=False), signin(interactive=False), signin(country="")):
        assert detect_dormant_active([row], last, seen, LONG_AGO) == [], row


def test_one_alert_per_person_and_country_even_with_several_sign_ins():
    rows = [signin(at=NOW), signin(at=NOW + timedelta(minutes=5))]
    assert len(detect_dormant_active(rows, {"amy@x.com": NOW - timedelta(days=90)}, {"amy@x.com": {"US"}}, LONG_AGO)) == 1


# ---- guests ------------------------------------------------------------------------------------------------------------------------------------------------


def invite(i, actor="amy@x.com", ok=True, activity="Invite external user", at=NOW, app=False):
    return NS(
        source_id=f"a{i}",
        actor=actor,
        success=ok,
        activity=activity,
        occurred_at=at + timedelta(minutes=i),
        target=f"guest{i}@other.com",
        actor_is_app=app,
        actor_ip="1.2.3.4",
    )


def test_five_guests_invited_by_one_person_in_a_day_is_one_alert():
    found = detect_guest_burst([invite(i) for i in range(GUEST_BURST)])
    assert len(found) == 1
    f = found[0]
    assert (f.rule_id, f.severity, f.technique) == ("aisoc-id-guest-burst", "medium", "T1136")
    assert ("Guests", str(GUEST_BURST)) in f.fields and f.users == ["amy@x.com"]


def test_four_guests_is_normal():
    assert detect_guest_burst([invite(i) for i in range(GUEST_BURST - 1)]) == []


def test_different_people_or_different_days_do_not_add_up():
    mixed = [invite(i, actor=f"u{i}@x.com") for i in range(GUEST_BURST)]
    assert detect_guest_burst(mixed) == []
    spread = [invite(i, at=NOW - timedelta(days=i)) for i in range(GUEST_BURST)]
    assert detect_guest_burst(spread) == []


def test_failed_invites_and_other_activities_do_not_count():
    rows = [invite(i, ok=False) for i in range(GUEST_BURST)] + [invite(i + 10, activity="Add user") for i in range(GUEST_BURST)]
    assert detect_guest_burst(rows) == []


def test_an_app_doing_it_is_high():
    assert detect_guest_burst([invite(i, app=True) for i in range(GUEST_BURST)])[0].severity == "high"


# ---- stale administrators ----------------------------------------------------------------------------------------------------------------------------------

from app.services.identity_detections import STALE_ADMIN_DAYS, detect_stale_admins  # noqa: E402


def admin(upn="root@x.com", enabled=True, is_admin=True, user_type="Member"):
    return NS(upn=upn, enabled=enabled, admin=is_admin, user_type=user_type)


def test_an_enabled_admin_with_no_sign_in_for_ninety_days_is_flagged_once_the_history_reaches_that_far():
    found = detect_stale_admins([admin()], {"root@x.com": NOW - timedelta(days=120)}, LONG_AGO, NOW)
    assert len(found) == 1
    f = found[0]
    assert (f.rule_id, f.severity, f.technique) == ("aisoc-id-admin-stale", "medium", "T1078.004")
    assert "120 days" in f.summary and f.key == "root@x.com:2026-Q4"


def test_an_admin_never_seen_signing_in_is_flagged_with_the_history_we_hold_when_it_is_long_enough():
    found = detect_stale_admins([admin()], {}, LONG_AGO, NOW)
    assert len(found) == 1 and "400 days we hold" in found[0].summary


def test_an_admin_who_signed_in_recently_is_fine():
    assert detect_stale_admins([admin()], {"root@x.com": NOW - timedelta(days=STALE_ADMIN_DAYS - 1)}, LONG_AGO, NOW) == []


def test_with_less_history_than_ninety_days_nobody_is_called_stale():
    assert detect_stale_admins([admin()], {}, NOW - timedelta(days=30), NOW) == []
    assert detect_stale_admins([admin()], {}, None, NOW) == []


def test_disabled_accounts_guests_and_people_who_are_not_admins_are_left_out():
    people = [admin(enabled=False), admin(user_type="Guest"), admin(is_admin=False)]
    assert detect_stale_admins(people, {}, LONG_AGO, NOW) == []

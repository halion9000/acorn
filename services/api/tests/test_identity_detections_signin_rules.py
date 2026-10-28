"""Sign-in rules that read failures and protocols: password spray, multi-factor fatigue, a guessed password, a legacy protocol."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from app.services.identity_detections import (
    detect_guessed_password,
    detect_legacy_protocol,
    detect_mfa_fatigue,
    detect_password_spray,
    detect_risky_signin,
)

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def row(i, user="a@x.com", ip="9.9.9.9", code=0, at=T0, client_app=None, mfa=None, country="RO"):
    return NS(
        source_id=f"s{i}",
        user_principal=user,
        ip_address=ip,
        error_code=code,
        success=code == 0,
        occurred_at=at,
        client_app=client_app,
        mfa=mfa,
        country=country,
        city=None,
        app="Outlook",
        interactive=True,
    )


def ids(rows):
    return {r.source_id for r in rows}


# ---- password spray ---------------------------------------------------------------------------------------------------------------------------------------------


def test_five_people_failing_a_password_from_one_address_in_an_hour_is_one_spray_alert():
    rows = [row(i, user=f"u{i}@x.com", code=50126, at=T0 + timedelta(minutes=i)) for i in range(5)]
    found = detect_password_spray(rows, ids(rows))
    assert len(found) == 1
    f = found[0]
    assert (f.severity, f.technique, f.ips) == ("high", "T1110.003", ["9.9.9.9"])
    assert len(f.users) == 5


def test_four_people_or_five_failures_by_one_person_are_not_a_spray():
    four = [row(i, user=f"u{i}@x.com", code=50126) for i in range(4)]
    assert detect_password_spray(four, ids(four)) == []
    one = [row(i, user="a@x.com", code=50126) for i in range(9)]
    assert detect_password_spray(one, ids(one)) == []


def test_other_errors_other_addresses_and_old_hours_do_not_count():
    other_error = [row(i, user=f"u{i}@x.com", code=53003) for i in range(6)]
    assert detect_password_spray(other_error, ids(other_error)) == []
    scattered = [row(i, user=f"u{i}@x.com", code=50126, ip=f"9.9.9.{i}") for i in range(6)]
    assert detect_password_spray(scattered, ids(scattered)) == []
    rows = [row(i, user=f"u{i}@x.com", code=50126) for i in range(5)]
    assert detect_password_spray(rows, set()) == [], "none of them new"


def test_the_same_spray_seen_again_has_the_same_key():
    rows = [row(i, user=f"u{i}@x.com", code=50126, at=T0 + timedelta(minutes=i)) for i in range(5)]
    more = [*rows, row(9, user="u9@x.com", code=50126, at=T0 + timedelta(minutes=20))]
    assert detect_password_spray(rows, ids(rows))[0].key == detect_password_spray(more, ids(more))[0].key


# ---- multi-factor fatigue ---------------------------------------------------------------------------------------------------------------------------------------


def test_five_failed_multi_factor_requests_in_an_hour_is_one_alert():
    rows = [row(i, code=500121, at=T0 + timedelta(minutes=i)) for i in range(5)]
    found = detect_mfa_fatigue(rows, ids(rows))
    assert [f.title for f in found] == ["Repeated multi-factor prompts - a@x.com"]
    assert found[0].technique == "T1621"


def test_four_prompts_or_prompts_spread_over_two_hours_are_not_fatigue():
    four = [row(i, code=500121) for i in range(4)]
    assert detect_mfa_fatigue(four, ids(four)) == []
    spread = [row(i, code=500121, at=T0 + timedelta(minutes=30 * i)) for i in range(5)]
    assert detect_mfa_fatigue(spread, ids(spread)) == []


# ---- a guessed password -----------------------------------------------------------------------------------------------------------------------------------------


def test_a_new_success_after_five_wrong_passwords_is_raised_once_and_names_both_addresses():
    fails = [row(i, code=50126, ip="1.1.1.1", at=T0 + timedelta(minutes=i)) for i in range(5)]
    ok = row(10, code=0, ip="2.2.2.2", at=T0 + timedelta(minutes=10), mfa=False)
    found = detect_guessed_password([*fails, ok], {"s10"})
    assert len(found) == 1
    f = found[0]
    assert f.title == "Sign-in succeeded after 5 wrong passwords - a@x.com"
    assert "2.2.2.2" in f.ips and "1.1.1.1" in f.ips
    assert ("Multi-factor", "not used") in f.fields


def test_four_wrong_passwords_old_failures_other_people_and_old_successes_do_not_count():
    four = [row(i, code=50126, at=T0 + timedelta(minutes=i)) for i in range(4)]
    ok = row(10, at=T0 + timedelta(minutes=10))
    assert detect_guessed_password([*four, ok], {"s10"}) == []
    five = [row(i, code=50126, at=T0 + timedelta(minutes=i)) for i in range(5)]
    late = row(11, at=T0 + timedelta(hours=2))
    assert detect_guessed_password([*five, late], {"s11"}) == [], "the failures were more than an hour earlier"
    others = [row(i, user=f"u{i}@x.com", code=50126) for i in range(5)]
    assert detect_guessed_password([*others, row(12, user="a@x.com")], {"s12"}) == []
    assert detect_guessed_password([*five, ok], set()) == [], "the success is not new"


# ---- a legacy protocol ------------------------------------------------------------------------------------------------------------------------------------------


def test_a_successful_imap_sign_in_is_one_alert_and_a_modern_client_is_none():
    found = detect_legacy_protocol([row(1, client_app="IMAP4"), row(2, client_app="Browser"), row(3, client_app="IMAP4", code=50126)])
    assert [f.title for f in found] == ["Legacy-protocol sign-in (IMAP4) - a@x.com"]
    assert found[0].severity == "medium"


def test_the_same_person_and_protocol_is_one_alert_a_day_and_a_new_day_is_a_new_one():
    rows = [
        row(1, client_app="POP3"),
        row(2, client_app="POP3", at=T0 + timedelta(hours=3)),
        row(3, client_app="POP3", at=T0 + timedelta(days=1)),
        row(4, client_app="SMTP"),
    ]
    found = detect_legacy_protocol(rows)
    assert len(found) == 3
    assert len({f.key for f in found}) == 3


def test_a_row_with_no_client_app_is_ignored():
    assert detect_legacy_protocol([row(1)]) == []


# ---- Microsoft's own risk rating ---------------------------------------------------------------------------------------------------------------------------------


def test_a_successful_medium_or_high_risk_sign_in_is_an_alert_with_matching_severity():
    rows = [row(1), row(2), row(3)]
    rows[0].risk, rows[1].risk, rows[2].risk = "high", "medium", "low"
    found = detect_risky_signin(rows)
    assert [(f.title, f.severity) for f in found] == [("High-risk sign-in - a@x.com", "high"), ("Medium-risk sign-in - a@x.com", "medium")]


def test_failed_unrated_and_rows_without_a_risk_field_are_ignored():
    failed = row(1, code=50126)
    failed.risk = "high"
    assert detect_risky_signin([failed, row(2)]) == []

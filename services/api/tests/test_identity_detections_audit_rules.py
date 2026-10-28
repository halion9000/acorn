"""Directory audit rules for sign-in methods changed by an administrator, application consent and credentials added to an application.

The activity names are the ones Microsoft wrote in real audit logs read through CIPP (2026-10-28).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace as NS

from app.services.identity_detections import detect_app_consent, detect_app_credentials_added, detect_security_info_changed_by_admin

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def audit(i, activity, actor="admin@x.com", target="u@x.com", success=True, actor_is_app=False):
    return NS(
        source_id=f"a{i}",
        activity=activity,
        actor=actor,
        target=target,
        occurred_at=T0,
        success=success,
        actor_is_app=actor_is_app,
        actor_ip="2.2.2.2",
        target_type="User",
    )


def test_an_admin_registering_or_deleting_security_info_is_one_alert_each_and_the_person_registering_their_own_is_not():
    rows = [
        audit(1, "Admin registered security info"),
        audit(2, "Admin deleted security info"),
        audit(3, "User registered security info", actor="u@x.com"),
        audit(4, "User registered all required security info", actor="u@x.com"),
        audit(5, "Admin registered security info", success=False),
    ]
    found = detect_security_info_changed_by_admin(rows)
    assert [f.title for f in found] == [
        "Sign-in methods registered by an administrator - u@x.com",
        "Sign-in methods deleted by an administrator - u@x.com",
    ]
    assert found[0].technique == "T1556.006" and found[0].users == ["admin@x.com", "u@x.com"]


def test_consent_and_a_delegated_grant_each_raise_one_alert_about_the_application():
    rows = [
        audit(1, "Consent to application", target="Evil Mail Reader"),
        audit(2, "Add delegated permission grant", target="Evil Mail Reader"),
        audit(3, "Remove delegated permission grant"),
        audit(4, "Add service principal"),
    ]
    found = detect_app_consent(rows)
    assert [f.key for f in found] == ["consent:a1", "consent:a2"]
    assert found[0].title == "Consent given to an application - Evil Mail Reader"
    assert found[0].users == ["admin@x.com"], "an application name is not a person"


def test_a_secret_or_certificate_added_to_an_application_is_an_alert_and_removing_one_is_not():
    rows = [
        audit(1, "Add service principal credentials", target="Backup App"),
        audit(2, "Update application – Certificates and secrets management", target="Backup App"),
        audit(3, "Create application – Certificates and secrets management", target="New App"),
        audit(4, "Remove service principal credentials"),
        audit(5, "Update application", target="Backup App"),
        audit(6, "Add service principal credentials", success=False),
    ]
    found = detect_app_credentials_added(rows)
    assert [f.key for f in found] == ["appcred:a1", "appcred:a2", "appcred:a3"]
    assert found[0].technique == "T1098.001"

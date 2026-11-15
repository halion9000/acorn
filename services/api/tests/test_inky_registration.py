"""INKY is a per-client tool: wherever a tool's checks, name, count and alert are registered, INKY is too (the CORE sweep sends them under vendor and source "inky")."""

from __future__ import annotations

from app.services import check_alerts, client_status, compliance_tests, infra_review, license_counts, nist_coverage, source_labels


def test_inky_checks_are_kept_under_its_own_source_and_named():
    assert infra_review.TOOL_CHECK_SOURCES["inky"] == "inky"
    assert source_labels.source_label("inky") == "INKY"
    assert client_status.TOOL_LABELS["inky"] == "Email protection (INKY)"


def test_a_team_without_protection_raises_an_alert_and_the_mail_flow_check_does_not():
    assert check_alerts.raises_alert("inky_active")
    assert not check_alerts.raises_alert("inky_mail_flow")


def test_inky_checks_count_toward_the_email_protection_control_test_and_the_nist_coverage():
    test = compliance_tests.BY_ID["email-protection"]
    assert set(test.checks) == {"inky_active", "inky_mail_flow"}
    covered = {key for keys in nist_coverage.MAPPING.values() for key in keys}
    assert {"inky_active", "inky_mail_flow"} <= covered


def test_protected_mailboxes_are_offered_for_an_inky_invoice_line():
    assert ("inky", (("inky", "Protected mailboxes"),)) in license_counts.SUGGESTIONS
    assert license_counts.SUGGESTION_CONFIDENCE["inky"] == "high"

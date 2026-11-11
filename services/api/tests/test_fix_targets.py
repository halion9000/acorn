"""Time-to-fix targets by severity: critical 4 hours, high 24 hours, medium 5 days, low 14 days."""

from datetime import UTC, datetime, timedelta

from app.services.check_alerts import WATCHED
from app.services.fix_targets import TARGET_HOURS, severity_of, standing

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def test_the_accepted_targets():
    assert TARGET_HOURS == {"critical": 4, "high": 24, "medium": 120, "low": 336}


def test_severity_comes_from_the_weight_and_an_alerting_check_is_at_least_high():
    assert [severity_of("x", w) for w in (1, 2, 3, 4, 5)] == ["low", "low", "medium", "high", "critical"]
    watched = next(iter(WATCHED))
    assert severity_of(watched, 1) == "high"
    assert severity_of(watched, 5) == "critical", "a heavier weight still wins"


def test_only_a_not_met_check_with_a_known_since_has_a_clock_and_it_is_overdue_past_its_target():
    assert standing("x", "not_met", NOW - timedelta(days=13), NOW, 1) == (336, False)
    assert standing("x", "not_met", NOW - timedelta(days=15), NOW, 1) == (336, True)
    assert standing("x", "not_met", NOW - timedelta(hours=25), NOW, 4) == (24, True)
    assert standing("x", "not_met", NOW - timedelta(hours=3), NOW, 5) == (4, False)
    assert standing("x", "partly", NOW - timedelta(days=99), NOW, 5) == (None, False)
    assert standing("x", "met", NOW - timedelta(days=99), NOW, 5) == (None, False)
    assert standing("x", "not_met", None, NOW, 5) == (None, False)


def test_the_insurance_readiness_checklist_asks_about_the_checks_built_on_2026_11_09_with_unique_keys():
    from app.services.client_review import TOOL_ITEMS

    keys = [k for _, k, _ in TOOL_ITEMS]
    assert len(keys) == len(set(keys)) and len({q for _, _, q in TOOL_ITEMS}) == len(TOOL_ITEMS)
    wanted = {
        "cipp_ca_legacy_auth",
        "cipp_mailbox_forwarding",
        "cipp_defender_vulnerabilities",
        "ninjaone_software_patches",
        "addigy_unsupported_macos",
        "meraki_end_of_support",
        "ninjaone_disk_health",
    }
    assert wanted <= {c for c, _, _ in TOOL_ITEMS}

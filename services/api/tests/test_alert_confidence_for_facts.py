"""A fact a tool or a check states (MDM is off, an account is disabled with a licence) has no detection confidence: the response says none, instead of an always-low score that told the reader nothing."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.api.v1.endpoints.alerts import AlertResponse, states_a_fact

NOW = datetime(2026, 11, 16, tzinfo=UTC)


def alert(connector_type: str | None, source: str | None = None) -> AlertResponse:
    item = AlertResponse(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        title="x",
        description=None,
        severity="medium",
        status="new",
        priority=50,
        category=None,
        mitre_tactics=[],
        mitre_techniques=[],
        connector_type=connector_type,
        ai_score=None,
        ai_summary=None,
        ai_recommendations=[],
        confidence=14,
        confidence_label="low",
        confidence_rationale=[{"factor": "severity"}],
        disposition=None,
        affected_ips=[],
        affected_hosts=[],
        affected_users=[],
        case_id=None,
        tags=[],
        event_time=NOW,
        first_seen=NOW,
        last_seen=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    item.source = source  # the list sets it from the raw event after the model is built
    return item


def test_which_alerts_state_a_fact() -> None:
    assert states_a_fact("aisoc-checks", None)
    assert states_a_fact("core_feed", None)
    assert states_a_fact("json_inbox", "addigy"), "a tool CORE says it came from"
    assert not states_a_fact("splunk", None)
    assert not states_a_fact(None, None)


def test_a_check_alert_has_no_confidence_in_the_response() -> None:
    out = alert("aisoc-checks").model_dump()
    assert (out["confidence"], out["confidence_label"], out["confidence_rationale"]) == (None, None, None)


def test_a_tool_alert_has_no_confidence_even_though_the_source_is_set_after_the_model_is_built() -> None:
    out = alert("json_inbox", "liongard").model_dump(mode="json")
    assert out["confidence"] is None and out["confidence_label"] is None


def test_a_detection_keeps_its_confidence() -> None:
    out = alert("splunk").model_dump()
    assert (out["confidence"], out["confidence_label"]) == (14, "low")
    assert out["confidence_rationale"] == [{"factor": "severity"}]

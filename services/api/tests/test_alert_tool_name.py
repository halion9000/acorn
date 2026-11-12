"""An alert that came in through the generic inbox is named by the tool that sent it (Huntress), never by the inbox ("Generic Generic JSON"): in the related-entities rail, in the
narrative, and in a narrative that was already stored with the inbox's name."""

from types import SimpleNamespace

from app.services.alert_rail import build_related_entities
from app.services.narrative_loader import build_narrative
from app.services.narrative_projection import project_alert_to_narrative_inputs
from app.services.source_labels import alert_tool_name, is_generic_inbox, narrative_names_the_inbox


def alert(connector_type="Generic Generic JSON", raw_event=None, **over):
    base = {
        "connector_type": connector_type,
        "raw_event": {"source": "huntress"} if raw_event is None else raw_event,
        "title": "Potential Unsecured Credentials in Files",
        "severity": "low",
        "affected_hosts": ["GSCTX-C8KSWC4"],
        "affected_users": [],
        "affected_ips": [],
        "affected_assets": [],
        "mitre_tactics": [],
        "mitre_techniques": [],
        "tags": [],
        "case_id": None,
        "enrichment_data": {},
        "confidence": None,
        "confidence_label": None,
        "confidence_rationale": None,
        "narrative": None,
    }
    return SimpleNamespace(**{**base, **over})


def entities(a):
    return {(e.group, e.kind): e.value for e in build_related_entities(a)}


def test_the_inbox_is_recognised_however_it_was_stored_and_a_real_connector_is_not():
    for name in ("Generic Generic JSON", "generic_json", "generic-json", "Generic JSON", " generic  generic json "):
        assert is_generic_inbox(name), name
    for name in ("huntress", "Generic Syslog", "", None):
        assert not is_generic_inbox(name), name


def test_the_tool_is_the_senders_own_name_when_the_alert_came_through_the_inbox():
    assert alert_tool_name("Generic Generic JSON", {"source": "huntress"}) == "Huntress"
    assert alert_tool_name("generic_json", {"source": "aisoc-checks"}) == "A.C.O.R.N posture checks"
    assert alert_tool_name("Generic Generic JSON", {}) == "Generic JSON", "no sender named: the inbox, said once"
    assert alert_tool_name("Generic Generic JSON", {"source": 7}) == "Generic JSON"
    assert alert_tool_name("Generic Generic JSON", None) == "Generic JSON"
    assert alert_tool_name("crowdstrike", {"source": "huntress"}) == "Crowdstrike", "a real connector keeps its own name"
    assert alert_tool_name(None, {"source": "huntress"}) == "Huntress"


def test_the_rail_names_the_tool_as_the_connector_and_does_not_invent_a_rule_from_the_inbox():
    found = entities(alert())
    assert found[("tenant", "connector")] == "Huntress"
    assert ("workflow", "rule") not in found, "the inbox's name is not a detection rule"
    assert "Generic Generic JSON" not in {e.value for e in build_related_entities(alert())}


def test_a_rule_the_tool_named_is_still_shown_and_a_real_connector_still_stands_in_for_a_missing_rule():
    named = entities(alert(raw_event={"source": "huntress", "rule_name": "Unsecured credentials"}))
    assert named[("workflow", "rule")] == "Unsecured credentials"
    real = entities(alert(connector_type="crowdstrike", raw_event={}))
    assert (
        real[("workflow", "rule")] == "crowdstrike" and real[("tenant", "connector")] == "crowdstrike"
    ), "a real connector is shown as it is stored"


def test_the_narrative_says_the_tool():
    text = build_narrative(project_alert_to_narrative_inputs(alert()))
    assert "from `Huntress`" in text
    assert "Generic" not in text


def test_a_stored_narrative_that_names_the_inbox_is_one_to_write_again():
    assert narrative_names_the_inbox("**Low** alert: X on **H** from `Generic Generic JSON`.")
    assert not narrative_names_the_inbox("**Low** alert: X on **H** from `Huntress`.")
    assert not narrative_names_the_inbox(None)
    assert not narrative_names_the_inbox("")

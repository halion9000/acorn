"""Readable names for the tools and feeds in the Executive Digest's top alert sources."""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.executive_digest import _top_sources
from app.services.source_labels import source_label


def test_known_tools_get_their_proper_names_and_our_own_alerts_say_what_they_are():
    assert [source_label(k) for k in ("huntress", "ninjaone", "fieldeffect", "aisoc-checks", "manual")] == [
        "Huntress",
        "NinjaOne",
        "Field Effect",
        "A.C.O.R.N posture checks",
        "Entered by hand",
    ]


def test_an_unknown_key_is_tidied_and_the_doubled_generic_name_is_one_word_shorter():
    assert source_label("some_new-feed") == "Some New Feed"
    assert source_label("Generic Generic JSON") == "Generic JSON"
    assert source_label("") == "Unknown" and source_label(None) == "Unknown"


def _alert(source, connector_type):
    now = datetime(2026, 10, 30, tzinfo=UTC)
    return SimpleNamespace(source=source, connector_type=connector_type, event_time=now)


def test_the_top_sources_use_the_tool_the_alert_names_before_the_generic_connector_type_and_carry_a_label():
    rows = [_alert("huntress", "Generic Generic JSON")] * 3 + [_alert(None, "aisoc-checks")] * 2 + [_alert(None, "Generic Generic JSON")]
    got = _top_sources(rows)
    assert [(s.connector_type, s.count, s.label) for s in got] == [
        ("huntress", 3, "Huntress"),
        ("aisoc-checks", 2, "A.C.O.R.N posture checks"),
        ("Generic Generic JSON", 1, "Generic JSON"),
    ]

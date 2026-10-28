"""The rule list tells the Rules page which category each rule belongs to, so the page can filter by it."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.api.v1.endpoints.detection_compat import _to_frontend


def rule(category):
    now = datetime(2026, 10, 28, tzinfo=UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Device code sign-in",
        description=None,
        rule_language="sigma",
        rule_body="detection: x",
        status="active",
        tags=[],
        mitre_techniques=["T1528"],
        mitre_tactics=[],
        severity="high",
        created_at=now,
        updated_at=now,
        last_triggered=None,
        total_hits=0,
        category=category,
    )


def test_the_rules_category_reaches_the_page():
    assert _to_frontend(rule("identity")).category == "identity"


def test_a_rule_with_no_category_has_none_rather_than_an_empty_string():
    assert _to_frontend(rule(None)).category is None
    assert _to_frontend(rule("")).category is None

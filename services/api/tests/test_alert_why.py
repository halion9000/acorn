"""Why an alert was raised: the facts come only from what the alert stores, a missing fact is left out, and the raw event is never copied out."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
from app.api.v1.endpoints import alert_why as ep
from app.services.alert_why import why_raised
from fastapi import HTTPException

OWNER = uuid.uuid4()


def alert(**over):
    base = {
        "raw_event": {"source": "Huntress", "password": "hunter2", "token": "abc"},
        "connector_type": None,
        "rule_id": "r-17",
        "rule_name": "Unexpected Country",
        "severity": "high",
        "confidence": 82,
        "confidence_label": "high",
        "confidence_rationale": ["Seen on two tools", {"text": "Admin account"}, {"other": "ignored"}],
        "affected_users": ["a@acme.com"],
        "affected_hosts": ["PC-1", "PC-2"],
        "affected_ips": [],
        "mitre_tactics": ["Initial Access"],
        "mitre_techniques": ["T1078"],
        "created_at": datetime(2026, 11, 4, 9, 0, tzinfo=UTC),
    }
    base.update(over)
    return NS(**base)


def facts(a):
    return [(r["label"], r["value"]) for r in why_raised(a)]


def test_the_facts_read_in_order_from_the_alert_itself():
    got = facts(alert())
    assert got[:4] == [("Raised by", "huntress"), ("Rule", "Unexpected Country (r-17)"), ("Severity", "high"), ("Confidence", "82% (high)")]
    assert ("Because", "Seen on two tools") in got and ("Because", "Admin account") in got
    assert ("Names the people", "a@acme.com") in got and ("Names the devices", "PC-1, PC-2") in got
    assert ("Attack techniques", "T1078") in got and got[-1] == ("Raised at", "2026-11-04T09:00:00+00:00")


def test_a_fact_the_alert_does_not_have_is_left_out_not_filled_in():
    got = dict(facts(alert(affected_ips=[], confidence=None, confidence_rationale=None, mitre_tactics=[], rule_name=None, rule_id=None)))
    for label in ("Names the addresses", "Confidence", "Because", "Attack tactics", "Rule"):
        assert label not in got
    assert got["Raised by"] == "huntress"


def test_the_raw_event_is_never_copied_out_so_secrets_in_it_cannot_leak():
    text = repr(why_raised(alert()))
    assert "hunter2" not in text and "abc" not in text and "password" not in text


def test_a_long_list_is_cut_and_says_how_many_more_and_a_long_text_is_cut():
    many = facts(alert(affected_users=[f"u{i}@acme.com" for i in range(8)]))
    assert dict(many)["Names the people"].endswith("and 3 more")
    assert len(dict(facts(alert(rule_name="x" * 1000)))["Rule"]) <= 300
    assert dict(facts(alert(raw_event={}, connector_type="CIPP")))["Raised by"] == "cipp"


class FakeDB:
    def __init__(self, row):
        self.row = row

    async def execute(self, _stmt):
        out = MagicMock()
        out.scalar_one_or_none.return_value = self.row
        return out


@pytest.fixture
def wired(monkeypatch):
    @contextlib.asynccontextmanager
    async def scope(_db, _own, _alert_id):
        yield OWNER

    monkeypatch.setattr(ep, "alert_scope", scope)


def call(db):
    return asyncio.run(ep.alert_why(uuid.uuid4(), NS(tenant_id=OWNER), db))


def test_the_endpoint_returns_the_facts_for_a_visible_alert(wired):
    out = call(FakeDB(alert()))
    assert out.facts[0].label == "Raised by" and out.facts[0].value == "huntress"


def test_the_endpoint_says_not_found_when_the_alert_is_not_there(wired):
    with pytest.raises(HTTPException) as e:
        call(FakeDB(None))
    assert e.value.status_code == 404


def test_the_route_needs_alerts_read():
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    assert set(required_permissions(found[("GET", "/alerts/{alert_id}/why")])) == {"alerts:read"}

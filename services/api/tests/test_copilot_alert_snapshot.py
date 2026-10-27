"""Leafy gets the live alert list up front for alert questions, and its search tool can filter by severity and time across the tenant's clients."""

from __future__ import annotations

import uuid
from types import SimpleNamespace as NS

import pytest
from app import copilot_tools as ct


def test_alert_questions_are_recognised_and_small_talk_is_not():
    for q in ("Summarize the top 5 critical alerts in the last 24 hours.", "what is the worst incident today", "any new detections?", "Investigate host FILE01"):
        assert ct.wants_alert_data(q), q
    for q in ("hi", "who are you?", "thanks!", ""):
        assert not ct.wants_alert_data(q), q


def test_the_snapshot_text_lists_each_alert_with_its_id_and_never_invents_one():
    text = ct.format_alert_snapshot(
        {"alerts": [{"id": "a-1", "severity": "critical", "status": "new", "client": "Acme Dental", "title": "Ransomware on FILE01"}, {"id": "a-2", "severity": "high", "status": "new", "title": "VPN from new country"}]},
        24,
    )
    assert "a-1 | critical | new | client: Acme Dental | Ransomware on FILE01" in text and "a-2 | high | new | VPN from new country" in text
    assert "last 24 hours" in text
    empty = ct.format_alert_snapshot({"alerts": []}, 24)
    assert "No open alerts" in empty and "a-" not in empty


@pytest.mark.asyncio
async def test_the_snapshot_is_none_when_the_caller_may_not_read_alerts(monkeypatch):
    async def deny(name, args, tenant_id, *, user):
        return {"error": "permission denied: search_alerts requires alerts:read"}

    monkeypatch.setattr(ct, "execute_copilot_tool", deny)
    assert await ct.alert_snapshot(tenant_id=str(uuid.uuid4()), user=NS()) is None


@pytest.mark.asyncio
async def test_the_snapshot_asks_for_open_alerts_of_the_last_day(monkeypatch):
    seen = {}

    async def fake(name, args, tenant_id, *, user):
        seen.update(name=name, args=args)
        return {"alerts": []}

    monkeypatch.setattr(ct, "execute_copilot_tool", fake)
    out = await ct.alert_snapshot(tenant_id=str(uuid.uuid4()), user=NS(), hours=24)
    assert seen == {"name": "search_alerts", "args": {"hours": 24, "only_open": True, "limit": 10}} and "No open alerts" in out


def test_the_search_tool_offers_severity_hours_and_open_only_and_needs_no_keyword():
    fn = next(t["function"] for t in ct.COPILOT_TOOL_SCHEMAS if t["function"]["name"] == "search_alerts")
    props = fn["parameters"]["properties"]
    assert {"query", "severity", "hours", "only_open", "limit"} <= set(props)
    assert props["severity"]["enum"] == ["critical", "high", "medium", "low", "info"]
    assert fn["parameters"]["required"] == []


@pytest.mark.asyncio
async def test_a_bad_severity_is_refused_with_the_valid_ones():
    out = await ct.search_alerts(tenant_id=str(uuid.uuid4()), severity="urgent")
    assert "error" in out and "critical" in out["error"]

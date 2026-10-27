"""A scan with nothing to discover with says so (409) instead of "started" followed by nothing, and each scan's outcome is recorded for the page."""

from __future__ import annotations

import uuid
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import easm
from fastapi import BackgroundTasks, HTTPException


def settings(**over):
    base = dict(AISOC_FEATURE_EASM=True, AISOC_EASM_SHODAN_API_KEY="", AISOC_EASM_CENSYS_API_ID="", AISOC_EASM_CENSYS_API_SECRET="", AISOC_EASM_ACTIVE_SCAN_ENABLED=False)
    base.update(over)
    return NS(**base)


def test_nothing_set_up_gives_one_clear_thing_to_change():
    plan = easm.scan_plan(settings(), [])
    assert plan["can_run"] is False and plan["sources"] == []
    assert "AISOC_EASM_SHODAN_API_KEY" in plan["problem"] and "AISOC_EASM_ACTIVE_SCAN_ENABLED" in plan["problem"]


def test_addresses_typed_while_the_port_check_is_off_are_explained_not_silently_dropped():
    plan = easm.scan_plan(settings(), ["203.0.113.10"])
    assert plan["can_run"] is False
    assert "switched off" in plan["problem"] and "AISOC_EASM_ACTIVE_SCAN_ENABLED=true" in plan["problem"]


def test_the_port_check_on_with_no_addresses_asks_for_addresses():
    plan = easm.scan_plan(settings(AISOC_EASM_ACTIVE_SCAN_ENABLED=True), [])
    assert plan["can_run"] is False and "Enter the public IP addresses" in plan["problem"]


def test_each_source_that_is_set_up_runs_and_a_half_set_up_censys_does_not():
    assert easm.scan_plan(settings(AISOC_EASM_SHODAN_API_KEY="k"), [])["sources"] == ["shodan"]
    assert easm.scan_plan(settings(AISOC_EASM_CENSYS_API_ID="i"), [])["can_run"] is False, "a Censys id without its secret is not a source"
    both = easm.scan_plan(settings(AISOC_EASM_CENSYS_API_ID="i", AISOC_EASM_CENSYS_API_SECRET="s", AISOC_EASM_ACTIVE_SCAN_ENABLED=True), ["203.0.113.10"])
    assert both["sources"] == ["censys", "port check"] and both["problem"] is None


@pytest.mark.asyncio
async def test_the_scan_route_refuses_with_a_409_when_nothing_can_run_and_queues_nothing(monkeypatch):
    monkeypatch.setattr(easm, "get_settings", lambda: settings())
    tid = uuid.uuid4()
    db = MagicMock()
    db.get = AsyncMock(return_value=NS(id=tid, name="Acme"))
    tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as e:
        await easm.trigger_easm_scan(easm.ScanRequest(ip_targets=["8.8.8.8"]), tasks, db, NS(tenant_id=tid))
    assert e.value.status_code == 409 and "switched off" in e.value.detail
    assert tasks.tasks == []


@pytest.mark.asyncio
async def test_the_scan_route_queues_the_job_when_a_source_is_set_up(monkeypatch):
    monkeypatch.setattr(easm, "get_settings", lambda: settings(AISOC_EASM_SHODAN_API_KEY="k"))
    tid = uuid.uuid4()
    db = MagicMock()
    db.get = AsyncMock(return_value=NS(id=tid, name="Acme"))
    tasks = BackgroundTasks()
    out = await easm.trigger_easm_scan(easm.ScanRequest(), tasks, db, NS(tenant_id=tid))
    assert out["status"] == "accepted" and out["sources"] == ["shodan"] and len(tasks.tasks) == 1


@pytest.mark.asyncio
async def test_the_status_route_returns_the_plan_and_the_last_scan(monkeypatch):
    monkeypatch.setattr(easm, "get_settings", lambda: settings(AISOC_EASM_SHODAN_API_KEY="k"))
    tid = uuid.uuid4()
    last = {"found": 4, "changes": 1, "error": None}
    db = MagicMock()
    db.get = AsyncMock(return_value=NS(id=tid, settings={"easm_last_scan": last}))
    out = await easm.easm_status(db, NS(tenant_id=tid))
    assert out["plan"]["sources"] == ["shodan"] and out["last_scan"] == last
    db.get = AsyncMock(return_value=NS(id=tid, settings=None))
    assert (await easm.easm_status(db, NS(tenant_id=tid)))["last_scan"] is None

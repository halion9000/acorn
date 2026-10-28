"""A scan with nothing to discover with says so (409) instead of "started" followed by nothing, and each scan's outcome is recorded for the page."""

from __future__ import annotations

import uuid
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import easm
from fastapi import BackgroundTasks, HTTPException


def settings(**over):
    base = dict(AISOC_FEATURE_EASM=True, AISOC_EASM_SHODAN_API_KEY="", AISOC_EASM_CENSYS_API_ID="", AISOC_EASM_CENSYS_API_SECRET="", AISOC_EASM_ACTIVE_SCAN_ENABLED=False, AISOC_EASM_INTERNETDB_ENABLED=False)
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


def test_the_keyless_internetdb_lookup_needs_only_addresses():
    plan = easm.scan_plan(settings(AISOC_EASM_INTERNETDB_ENABLED=True), ["8.8.8.8"])
    assert plan["sources"] == ["internetdb"] and plan["can_run"] is True and plan["problem"] is None
    empty = easm.scan_plan(settings(AISOC_EASM_INTERNETDB_ENABLED=True), [])
    assert empty["can_run"] is False and "Enter the public IP addresses" in empty["problem"]


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
    out = await easm.trigger_easm_scan(easm.ScanRequest(ip_targets=["8.8.8.8"]), tasks, db, NS(tenant_id=tid))
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


class _Resolver:
    def __init__(self, answers):
        self.answers = answers

    async def mx(self, name):
        return []

    async def a(self, name):
        return self.answers.get(name, [])


@pytest.mark.asyncio
async def test_with_nothing_typed_the_scan_uses_the_domains_of_the_tenants_people_and_looks_up_their_addresses(monkeypatch):
    monkeypatch.setattr(easm, "get_settings", lambda: settings(AISOC_EASM_INTERNETDB_ENABLED=True))
    monkeypatch.setattr(easm, "DohResolver", lambda: _Resolver({"acme.com": ["8.8.8.8"], "www.acme.com": ["8.8.8.8", "1.1.1.1"]}))
    tid = uuid.uuid4()
    db = MagicMock()
    db.get = AsyncMock(return_value=NS(id=tid, name="Acme"))
    db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: NS(all=lambda: ["a@acme.com", "b@acme.com", "c@gmail.com"])))
    tasks = BackgroundTasks()
    out = await easm.trigger_easm_scan(easm.ScanRequest(), tasks, db, NS(tenant_id=tid))
    assert out["sources"] == ["internetdb"]
    (task,) = tasks.tasks
    assert task.args[2] == [], "no typed addresses, so nothing is port-probed"
    assert task.args[3] == ["8.8.8.8", "1.1.1.1"]
    assert task.args[4] == {"acme.com": ["8.8.8.8", "1.1.1.1"]}


@pytest.mark.asyncio
async def test_domains_with_no_public_address_say_so_instead_of_starting_a_scan_that_finds_nothing(monkeypatch):
    monkeypatch.setattr(easm, "get_settings", lambda: settings(AISOC_EASM_INTERNETDB_ENABLED=True))
    monkeypatch.setattr(easm, "DohResolver", lambda: _Resolver({}))
    tid = uuid.uuid4()
    db = MagicMock()
    db.get = AsyncMock(return_value=NS(id=tid, name="Acme"))
    tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as e:
        await easm.trigger_easm_scan(easm.ScanRequest(ip_targets=["gone.example.org"]), tasks, db, NS(tenant_id=tid))
    assert e.value.status_code == 409 and "gone.example.org" in e.value.detail and tasks.tasks == []


def test_the_status_page_counts_the_keyless_lookup_as_available_before_anything_is_typed():
    plan = easm.scan_plan(settings(AISOC_EASM_INTERNETDB_ENABLED=True), [], targets_expected=True)
    assert plan["sources"] == ["internetdb"] and plan["can_run"] is True
    assert easm.scan_plan(settings(AISOC_EASM_INTERNETDB_ENABLED=True), [])["can_run"] is False

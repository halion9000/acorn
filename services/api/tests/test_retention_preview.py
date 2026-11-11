"""The retention preview: a dry run that reports counts, says whether the sweeper really deletes, and asks for a platform permission."""

import asyncio

import app.core.config as config
from app.api.v1.endpoints import data_lifecycle as ep
from app.core.security import has_permission
from app.workers import retention_sweeper as rs


def test_the_preview_is_a_dry_run_that_reports_counts_by_kind_and_failures(monkeypatch):
    seen = {}

    async def fake_sweep_once(*args, **kwargs):
        seen["kwargs"] = kwargs
        return rs.SweepResult(dry_run=True, counts={"response_actions": 12, "alerts": 0, "copilot_conversations": 3}, errors={"posture_history": "OperationalError"})

    monkeypatch.setattr(rs, "sweep_once", fake_sweep_once)
    monkeypatch.setattr(config.settings, "RETENTION_DRY_RUN", False)  # the object in place now: the handler reads it at call time
    out = asyncio.run(ep.retention_preview())
    assert seen["kwargs"] == {"dry_run": True}, "it must never be asked to delete"
    assert out.would_delete == {"alerts": 0, "copilot_conversations": 3, "response_actions": 12}
    assert out.failed == {"posture_history": "OperationalError"}
    assert out.switched_on is True and "deleting for real" in out.note and "nothing was deleted" in out.note


def test_a_sweeper_set_to_dry_run_says_it_deletes_nothing(monkeypatch):
    async def fake_sweep_once(*args, **kwargs):
        return rs.SweepResult(dry_run=True, counts={})

    monkeypatch.setattr(rs, "sweep_once", fake_sweep_once)
    # The handler reads the settings object at call time; another test may have replaced it since this file was imported, so patch the one in place now.
    monkeypatch.setattr(config.settings, "RETENTION_DRY_RUN", True)
    out = asyncio.run(ep.retention_preview())
    assert out.switched_on is False and "deletes nothing" in out.note


def test_only_a_platform_administrator_holds_the_permission_it_needs():
    assert has_permission("platform_admin", "platform:cross_tenant_query")
    assert not has_permission("tenant_admin", "platform:cross_tenant_query")
    assert not has_permission("soc_lead", "platform:cross_tenant_query")

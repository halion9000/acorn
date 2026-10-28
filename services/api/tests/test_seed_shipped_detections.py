"""Seeding the shipped detections at startup: both loaders run, and a failure never escapes."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.scripts import load_builtin_detections as builtin
from app.scripts import load_catalog_detections as catalog
from app.services import seed_shipped_detections as seed


def test_it_is_on_unless_switched_off():
    assert seed.enabled({})
    for off in ("0", "false", "No", "off"):
        assert not seed.enabled({"AISOC_SEED_SHIPPED_DETECTIONS": off})


class Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def commit(self):
        pass


def test_both_loaders_run_once_per_tenant_and_for_the_catalog(monkeypatch):
    calls = []

    async def tenants(_s):
        return ["t1", "t2"]

    async def load_rules(_s, rules, tid, skipped):
        calls.append(tid)
        return SimpleNamespace(created=3)

    async def load_catalog(_s, entries):
        return {"created": len(entries), "existing": 0}

    monkeypatch.setattr(builtin, "list_tenant_ids", tenants)
    monkeypatch.setattr(builtin, "load", load_rules)
    monkeypatch.setattr(catalog, "load", load_catalog)
    out = asyncio.run(seed.seed_once(lambda: Session()))
    assert calls == ["t1", "t2"]
    assert out["builtin"] == {"tenants": 2, "created": 6}
    assert out["catalog"]["created"] > 0


def test_a_failure_is_reported_not_raised(monkeypatch):
    async def boom(_s):
        raise RuntimeError("database is not ready")

    monkeypatch.setattr(builtin, "list_tenant_ids", boom)
    out = asyncio.run(seed.seed_once(lambda: Session()))
    assert "database is not ready" in out["error"]


def test_no_detections_folder_does_nothing(monkeypatch):
    monkeypatch.setattr(builtin, "detections_dir", lambda *a, **k: None)
    assert asyncio.run(seed.seed_once(lambda: Session())) == {"skipped": "no detections folder"}

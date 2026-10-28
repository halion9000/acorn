"""Seeding the shipped detections at startup: both loaders run, and a failure never escapes."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.scripts import load_builtin_detections as builtin
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


def test_the_builtin_loader_runs_once_per_tenant_and_the_sigma_rules_are_loaded_as_packs_from_the_shipped_files(monkeypatch):
    calls = []

    async def tenants(_s):
        return ["t1", "t2"]

    async def load_rules(_s, rules, tid, skipped):
        calls.append(tid)
        return SimpleNamespace(created=3)

    packed = []

    async def seed_packs(_factory, entries):
        packed.append(len(entries))
        return {"parents": 1, "rules_created": len(entries), "packs_created": 6, "links_created": len(entries)}

    monkeypatch.setattr(builtin, "list_tenant_ids", tenants)
    monkeypatch.setattr(builtin, "load", load_rules)
    monkeypatch.setattr(seed, "seed_packs", seed_packs)
    out = asyncio.run(seed.seed_once(lambda: Session()))
    assert calls == ["t1", "t2"]
    assert out["builtin"] == {"tenants": 2, "created": 6}
    assert "catalog" not in out, "there is no Detection Catalog any more"
    assert packed and packed[0] >= 50, "the shipped Sigma files are what the packs are made from"
    assert out["packs"]["packs_created"] == 6


def test_a_failure_is_reported_not_raised(monkeypatch):
    async def boom(_s):
        raise RuntimeError("database is not ready")

    monkeypatch.setattr(builtin, "list_tenant_ids", boom)
    out = asyncio.run(seed.seed_once(lambda: Session()))
    assert "database is not ready" in out["error"]


def test_no_detections_folder_does_nothing(monkeypatch):
    monkeypatch.setattr(builtin, "detections_dir", lambda *a, **k: None)
    assert asyncio.run(seed.seed_once(lambda: Session())) == {"skipped": "no detections folder"}

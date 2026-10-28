"""Playbook dry runs end to end against a REAL Postgres: only the clients the MSSP ticked are watched, a pass records what would have run, a second pass adds nothing, and the list endpoint shows it.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database).
"""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.playbook_dry_runs import list_dry_runs
from app.services import playbook_dry_runs as dr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")

ATO = {
    "id": "ato-test-v1",
    "name": "ATO test",
    "enabled": True,
    "trigger": {"on": "alert", "severity": ["high"], "tags": ["account-takeover"]},
    "steps": [{"id": "e1", "type": "enrich", "name": "Enrich"}, {"id": "r1", "type": "revoke_session", "name": "Revoke sessions"}],
}


@pytest.fixture
async def world():
    parent, ticked, unticked = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    now = datetime.now(UTC)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for tid, name, p, role, settings in (
                (parent, "parent", None, "parent", {}),
                (ticked, "ticked", parent, "child", {"playbook_automation": True}),
                (unticked, "unticked", parent, "child", {}),
            ):
                await conn.execute(
                    text(
                        "insert into tenants (id, name, slug, parent_tenant_id, mssp_role, settings) values (:i, :n, :s, :p, :r, cast(:st as jsonb))"
                    ),
                    {"i": tid, "n": f"{name}-{tag}", "s": f"{name}-{tag}", "p": p, "r": role, "st": json.dumps(settings)},
                )
            for tid in (ticked, unticked):
                await conn.execute(
                    text(
                        "insert into alerts (id, tenant_id, title, severity, status, category, tags, event_time, first_seen, last_seen, created_at) "
                        "values (:i, :t, 'Guessed password', 'high', 'new', 'identity', cast(:tags as jsonb), :now, :now, :now, :now)"
                    ),
                    {"i": uuid.uuid4(), "t": tid, "tags": json.dumps(["account-takeover"]), "now": now - timedelta(minutes=5)},
                )
        yield engine, parent, ticked, unticked
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            ids = [str(i) for i in (parent, ticked, unticked)]
            for table in ("playbook_dry_runs", "alerts"):
                await conn.execute(text(f"delete from {table} where tenant_id = any(cast(:t as uuid[]))"), {"t": ids})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[])) and parent_tenant_id is not null"), {"t": ids})
            await conn.execute(text("delete from tenants where id = :p"), {"p": parent})
        await engine.dispose()


@pytest.mark.asyncio
async def test_only_the_ticked_client_is_watched_a_second_pass_adds_nothing_and_the_list_shows_what_would_have_run(world):
    engine, parent, ticked, unticked = world
    factory = async_sessionmaker(engine, expire_on_commit=False)
    asked: list[uuid.UUID] = []

    async def fetch(tenant_id):
        asked.append(tenant_id)
        return [ATO]

    first = await dr.run_once(factory, fetch)
    assert first["recorded"] >= 1 and first["skipped"] == 0
    assert ticked in asked and unticked not in asked, "only clients the MSSP ticked are looked at"
    second = await dr.run_once(factory, fetch)
    assert second["recorded"] == 0, "the same alert and playbook are never recorded twice"

    db = factory()
    await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
    out = await list_dry_runs(SimpleNamespace(tenant_id=parent), db, alert_id=None, limit=50)
    await db.close()
    mine = [i for i in out.items if i.client_id in (ticked, unticked)]
    assert out.nothing_was_run is True
    assert [(i.client_id, i.playbook_id, i.alert_title) for i in mine] == [(ticked, "ato-test-v1", "Guessed password")]
    assert mine[0].matched_on == ["severity high", "tag account-takeover"]
    assert [s.type for s in mine[0].steps] == ["enrich", "revoke_session"]


@pytest.mark.asyncio
async def test_a_client_whose_playbooks_cannot_be_read_is_skipped_and_the_pass_carries_on(world):
    engine, _parent, _ticked, _unticked = world
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def broken(_tenant_id):
        raise RuntimeError("agents service is down")

    report = await dr.run_once(factory, broken)
    assert report["skipped"] >= 1 and report["recorded"] == 0

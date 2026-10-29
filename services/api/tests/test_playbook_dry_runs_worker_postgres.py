"""The playbook dry-run worker on a REAL Postgres: a client with nothing unfinished costs no request to the agents service, a client's playbooks are asked for once per cache window, old dry runs are deleted, a deleted alert takes
its dry runs with it (migration 128), and a dry run for the organization's own alert names the organization.

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
    "steps": [{"id": "e1", "type": "enrich", "name": "Enrich"}],
}


@pytest.fixture
async def world():
    """A parent with an alert of its own, one ticked client with only a RESOLVED alert (nothing to watch), and one ticked client with a live alert."""
    parent, quiet, busy = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    now = datetime.now(UTC)
    ids = {"parent": parent, "quiet": quiet, "busy": busy}
    alert_ids = {"quiet": uuid.uuid4(), "busy": uuid.uuid4(), "own": uuid.uuid4()}
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, tid in ids.items():
                await conn.execute(
                    text(
                        "insert into tenants (id, name, slug, parent_tenant_id, mssp_role, settings) "
                        "values (:i, :n, :s, :p, :r, cast(:st as jsonb))"
                    ),
                    {
                        "i": tid,
                        "n": f"{key}-{tag}",
                        "s": f"{key}-{tag}",
                        "p": None if key == "parent" else parent,
                        "r": "parent" if key == "parent" else "child",
                        "st": json.dumps({} if key == "parent" else {"playbook_automation": True}),
                    },
                )
            for key, tid, status in (("quiet", quiet, "resolved"), ("busy", busy, "new"), ("own", parent, "new")):
                await conn.execute(
                    text(
                        "insert into alerts (id, tenant_id, title, severity, status, category, tags, event_time, first_seen, last_seen, created_at) "
                        "values (:i, :t, :title, 'high', :st, 'identity', cast(:tags as jsonb), :now, :now, :now, :now)"
                    ),
                    {
                        "i": alert_ids[key],
                        "t": tid,
                        "title": f"{key} alert",
                        "st": status,
                        "tags": json.dumps(["account-takeover"]),
                        "now": now - timedelta(minutes=5),
                    },
                )
        yield engine, SimpleNamespace(parent=parent, quiet=quiet, busy=busy, alerts=alert_ids, now=now)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            tids = [str(i) for i in ids.values()]
            for table in ("playbook_dry_runs", "alerts"):
                await conn.execute(text(f"delete from {table} where tenant_id = any(cast(:t as uuid[]))"), {"t": tids})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[])) and parent_tenant_id is not null"), {"t": tids})
            await conn.execute(text("delete from tenants where id = :p"), {"p": parent})
        await engine.dispose()


async def count_runs(engine, tenant):
    async with engine.begin() as conn:
        await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        return (await conn.execute(text("select count(*) from playbook_dry_runs where tenant_id = :t"), {"t": tenant})).scalar_one()


async def add_run(engine, tenant, alert, playbook, created_at=None):
    async with engine.begin() as conn:
        await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await conn.execute(
            text(
                "insert into playbook_dry_runs (tenant_id, alert_id, playbook_id, playbook_name, created_at) "
                "values (:t, :a, :p, :p, coalesce(cast(:c as timestamptz), now()))"
            ),
            {"t": tenant, "a": alert, "p": playbook, "c": created_at},
        )


@pytest.mark.asyncio
async def test_a_client_with_nothing_unfinished_is_not_asked_about_for_playbooks(world):
    engine, w = world
    factory = async_sessionmaker(engine, expire_on_commit=False)
    dr.reset_playbook_cache()
    asked: list[uuid.UUID] = []

    async def fetch(tenant_id):
        asked.append(tenant_id)
        return [ATO]

    report = await dr.run_once(factory, fetch, now=w.now)
    assert w.busy in asked, "a client with a live alert is asked about"
    assert w.quiet not in asked, "a client whose only alert is resolved costs no request to the agents service"
    assert report["idle"] >= 1 and report["recorded"] >= 1


@pytest.mark.asyncio
async def test_a_clients_playbooks_are_asked_for_once_in_the_cache_window_not_every_pass(world):
    engine, w = world
    factory = async_sessionmaker(engine, expire_on_commit=False)
    dr.reset_playbook_cache()
    calls: list[uuid.UUID] = []

    async def fetch(tenant_id):
        calls.append(tenant_id)
        return [ATO]

    await dr.run_once(factory, fetch, now=w.now)
    await dr.run_once(factory, fetch, now=w.now + timedelta(minutes=1))
    assert calls.count(w.busy) == 1, "the second pass, a minute later, reuses the playbooks"
    await dr.run_once(factory, fetch, now=w.now + timedelta(minutes=10))
    assert calls.count(w.busy) == 2, "after the window they are asked for again"
    await dr.run_once(factory, fetch, now=w.now + timedelta(minutes=11), playbook_ttl_seconds=0)
    assert calls.count(w.busy) == 3, "a window of 0 means never reuse"


@pytest.mark.asyncio
async def test_a_failed_fetch_is_not_remembered_so_the_next_pass_tries_again(world):
    engine, w = world
    factory = async_sessionmaker(engine, expire_on_commit=False)
    dr.reset_playbook_cache()
    state = {"down": True}
    calls: list[uuid.UUID] = []

    async def fetch(tenant_id):
        calls.append(tenant_id)
        if state["down"]:
            raise RuntimeError("agents service is down")
        return [ATO]

    first = await dr.run_once(factory, fetch, now=w.now)
    assert first["skipped"] >= 1 and first["recorded"] == 0
    state["down"] = False
    second = await dr.run_once(factory, fetch, now=w.now + timedelta(seconds=30))
    assert second["recorded"] >= 1 and calls.count(w.busy) == 2


@pytest.mark.asyncio
async def test_dry_runs_older_than_the_retention_are_deleted_at_each_pass_and_recent_ones_are_kept(world):
    engine, w = world
    factory = async_sessionmaker(engine, expire_on_commit=False)
    dr.reset_playbook_cache()
    await add_run(engine, w.busy, w.alerts["busy"], "old-one", w.now - dr.RETENTION - timedelta(days=3))
    await add_run(engine, w.busy, w.alerts["busy"], "recent-one", w.now - timedelta(days=2))

    async def nothing_matches(_tenant_id):
        return []

    report = await dr.run_once(factory, nothing_matches, now=w.now)
    assert report["pruned"] == 1
    async with engine.begin() as conn:
        await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        left = set(
            (await conn.execute(text("select playbook_id from playbook_dry_runs where tenant_id = :t"), {"t": w.busy})).scalars().all()
        )
    assert left == {"recent-one"}


@pytest.mark.asyncio
async def test_deleting_an_alert_takes_its_dry_runs_with_it(world):
    engine, w = world
    await add_run(engine, w.busy, w.alerts["busy"], "p")
    assert await count_runs(engine, w.busy) == 1
    async with engine.begin() as conn:
        await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await conn.execute(text("delete from alerts where id = :a"), {"a": w.alerts["busy"]})
    assert await count_runs(engine, w.busy) == 0, "no dry run is left pointing at an alert that is gone"


@pytest.mark.asyncio
async def test_a_dry_run_cannot_point_at_an_alert_that_does_not_exist(world):
    engine, w = world
    with pytest.raises(Exception, match="foreign key|violates"):
        await add_run(engine, w.busy, uuid.uuid4(), "p")


@pytest.mark.asyncio
async def test_a_dry_run_for_the_organizations_own_alert_names_the_organization(world):
    engine, w = world
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await add_run(engine, w.parent, w.alerts["own"], "p")
    db = factory()
    await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
    out = await list_dry_runs(SimpleNamespace(tenant_id=w.parent), db, alert_id=None, limit=50)
    await db.close()
    own = [i for i in out.items if i.client_id == w.parent]
    assert len(own) == 1 and own[0].client_name and own[0].client_name.startswith("parent-"), own

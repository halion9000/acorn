"""The fleet change and acceptance reports on a REAL Postgres, as the application's own (row-level-security) role.

Each is ONE query across the organization's clients now (it was one per client, sorted in Python and cut to a limit after the fact). Worsening checks come first, then the newest; the limit is applied in the database; an organization's own report never holds
another organization's client; and the bounds the API advertises are the ones it applies (days up to 90, limit up to 1000 where it used to say 400 and 5000 and clamp in silence).

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database) and AISOC_TEST_PG_APP_URL (the application role on it).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

import pytest
from app.api.v1.endpoints import client_posture as ep
from app.db.rls import set_rls_context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:8]
    ids = {k: uuid.uuid4() for k in ("msp", "c1", "c2", "stranger", "stranger_client")}
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    now = datetime.now(UTC)
    try:
        async with owner.begin() as c:
            await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, tid in ids.items():
                parent = {"c1": ids["msp"], "c2": ids["msp"], "stranger_client": ids["stranger"]}.get(key)
                await c.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {"i": tid, "n": f"fr-{key}-{tag}", "s": f"fr-{key}-{tag}", "p": parent, "r": "child" if parent else "parent"},
                )
            history = [
                # (tenant, key, status, previous, hours ago)
                ("c1", "backup_ok", "met", "not_met", 1),
                ("c1", "edr_on", "not_met", "met", 30),
                ("c2", "mfa_on", "not_met", None, 5),
                ("c2", "patching", "partly", "met", 2),
                ("c1", "old_check", "not_met", None, 24 * 40),  # older than 7 days
                ("stranger_client", "secret_check", "not_met", None, 1),
            ]
            for who, key, status, previous, hours in history:
                await c.execute(
                    text(
                        "insert into client_check_history (tenant_id, source, key, status, previous_status, evidence, observed_at) "
                        "values (:t, 'tool', :k, :s, :p, '', :at)"
                    ),
                    {"t": ids[who], "k": key, "s": status, "p": previous, "at": now - timedelta(hours=hours)},
                )
            for who, key, days in (
                ("c1", "edr_on", 20),
                ("c2", "mfa_on", 3),
                ("c1", "patching", None),
                ("stranger_client", "secret_check", 1),
            ):
                await c.execute(
                    text(
                        "insert into client_check_acceptances (tenant_id, key, reason, accepted_at, expires_at) "
                        "values (:t, :k, 'accepted for now', :now, :exp)"
                    ),
                    {"t": ids[who], "k": key, "now": now, "exp": None if days is None else now + timedelta(days=days)},
                )
        yield ids, tag
    finally:
        async with owner.begin() as c:
            await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            tids = [str(v) for v in ids.values()]
            for table in ("client_check_history", "client_check_acceptances"):
                await c.execute(text(f"delete from {table} where tenant_id = any(cast(:t as uuid[]))"), {"t": tids})
            await c.execute(text("delete from tenants where id = any(cast(:t as uuid[])) and parent_tenant_id is not null"), {"t": tids})
            await c.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": tids})
        await owner.dispose()


async def as_msp(world_ids, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, world_ids["msp"])
            return await work(db, NS(tenant_id=world_ids["msp"]))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_changes_put_the_worsening_ones_first_then_the_newest_and_leave_out_old_and_foreign_ones(world):
    ids, _ = world
    out = await as_msp(ids, lambda db, user: ep.fleet_changes(user, db, days=7, limit=300))
    keys = [c.key for c in out]
    assert "secret_check" not in keys, "another organization's client is never in this organization's report"
    assert "old_check" not in keys, "older than the window"
    # The checks that became not_met come first, newest first (mfa_on 5 hours ago, edr_on 30), then the rest newest first (backup_ok 1 hour ago, patching 2).
    assert keys == ["mfa_on", "edr_on", "backup_ok", "patching"], keys


@pytest.mark.asyncio
async def test_the_limit_is_applied_after_the_ordering(world):
    ids, _ = world
    out = await as_msp(ids, lambda db, user: ep.fleet_changes(user, db, days=7, limit=2))
    assert [c.key for c in out] == ["mfa_on", "edr_on"], "a short list is the worst two, not an arbitrary two"
    assert {c.client_name.split("-")[1] for c in out} == {"c2", "c1"}


@pytest.mark.asyncio
async def test_acceptances_list_the_ones_ending_first_and_never_another_organizations(world):
    ids, _ = world
    out = await as_msp(ids, lambda db, user: ep.fleet_acceptances(user, db, within_days=None, limit=300))
    keys = [a.key for a in out]
    assert "secret_check" not in keys
    assert set(keys) == {"edr_on", "mfa_on", "patching"}
    assert keys.index("mfa_on") < keys.index("edr_on"), "the one ending in 3 days comes before the one ending in 20"
    within = await as_msp(ids, lambda db, user: ep.fleet_acceptances(user, db, within_days=7, limit=300))
    assert [a.key for a in within] == ["mfa_on"]
    short = await as_msp(ids, lambda db, user: ep.fleet_acceptances(user, db, within_days=None, limit=1))
    assert len(short) == 1


@pytest.mark.asyncio
async def test_an_organization_with_no_clients_gets_empty_reports(world):
    ids, _ = world
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, ids["stranger_client"])
            assert await ep.fleet_changes(NS(tenant_id=ids["stranger_client"]), db, days=7, limit=10) == []
            assert await ep.fleet_acceptances(NS(tenant_id=ids["stranger_client"]), db, within_days=None, limit=10) == []
    finally:
        await engine.dispose()

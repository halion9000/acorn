"""The quarterly business review endpoint against a REAL Postgres as the restricted role (opt in with AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import qbr as ep
from app.db.rls import set_rls_context
from fastapi import HTTPException
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
    owner_id, acme, birch = (uuid.uuid4() for _ in range(3))
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("insert into tenants (id, name, slug) values (:i, :n, :s)"), {"i": owner_id, "n": f"o-{tag}", "s": f"o-{tag}"})
            for tid, name in ((acme, "Acme"), (birch, "Birch")):
                await conn.execute(text("insert into tenants (id, name, slug, parent_tenant_id) values (:i, :n, :s, :p)"), {"i": tid, "n": name, "s": f"{name.lower()}-{tag}", "p": owner_id})
            rows = [
                (acme, "critical", "new", "now() - interval '3 days'", "null"),
                (acme, "high", "resolved", "now() - interval '10 days'", "now() - interval '9 days'"),
                (acme, "low", "closed", "now() - interval '400 days'", "now() - interval '399 days'"),
                (birch, "critical", "new", "now() - interval '1 day'", "null"),
            ]
            for tid, sev, status, created, resolved in rows:
                await conn.execute(
                    text(
                        "insert into alerts (id, tenant_id, title, severity, status, priority, affected_hosts, affected_users, created_at, updated_at, resolved_at) "
                        f"values (gen_random_uuid(), :t, 'a', :sev, :st, 50, cast('[]' as jsonb), cast('[]' as jsonb), {created}, now(), {resolved})"
                    ),
                    {"t": tid, "sev": sev, "st": status},
                )
            await conn.execute(
                text("insert into cases (id, tenant_id, case_number, title, status, priority, created_at, updated_at, closed_at) values (gen_random_uuid(), :t, :n, 'c', 'closed', 'medium', now() - interval '5 days', now(), now() - interval '2 days')"),
                {"t": acme, "n": f"C-{tag}"},
            )
        yield SimpleNamespace(owner=owner_id, acme=acme, birch=birch)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for table in ("alerts", "cases"):
                await conn.execute(text(f"delete from {table} where tenant_id = any(cast(:t as uuid[]))"), {"t": [str(w) for w in (acme, birch)]})
            await conn.execute(text("delete from tenants where parent_tenant_id = :t"), {"t": owner_id})
            await conn.execute(text("delete from tenants where id = :t"), {"t": owner_id})
        await engine.dispose()


async def call(w, client):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, w.owner)
            return await ep.qbr(SimpleNamespace(tenant_id=w.owner), db, client, 3)
    finally:
        await engine.dispose()


async def test_the_pack_counts_only_the_clients_own_alerts_in_the_period_and_has_no_finance(world):
    out = await call(world, world.acme)
    assert out["client"] == "Acme"
    assert out["security"]["alerts_received"] == 2 and out["security"]["alerts_handled"] == 1
    assert out["security"]["alerts_open_now"] == 1, "Birch's open alert is not Acme's"
    assert out["work"] == {"cases_opened": 1, "cases_closed": 1, "alerts_resolved": 1}
    assert not any("revenue" in k or "cost" in k or "margin" in k for k in out)


async def test_a_client_that_is_not_the_callers_is_not_found(world):
    with pytest.raises(HTTPException) as e:
        await call(world, uuid.uuid4())
    assert e.value.status_code == 404

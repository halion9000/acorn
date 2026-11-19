"""A toolbox request against a REAL Postgres as the restricted role: it becomes a pending approval naming the client and every value, never runs, never auto-approves, and a client that is not the caller's is
refused (opt in with AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import toolbox as ep
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
    owner, acme, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'owner', :s)"), {"i": owner, "s": f"to-{tag}"})
            await conn.execute(text("insert into tenants (id, name, slug, parent_tenant_id) values (:i, 'Acme', :s, :p)"), {"i": acme, "s": f"ta-{tag}", "p": owner})
            await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'Stranger', :s)"), {"i": stranger, "s": f"ts-{tag}"})
        yield SimpleNamespace(owner=owner, acme=acme, stranger=stranger)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from agent_approvals where tenant_id = :t"), {"t": owner})
            await conn.execute(text("alter table audit_log disable trigger user"))
            await conn.execute(text("delete from audit_log where tenant_id = :t"), {"t": owner})
            await conn.execute(text("alter table audit_log enable trigger user"))
            await conn.execute(text("delete from tenants where parent_tenant_id = :t"), {"t": owner})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [str(owner), str(stranger)]})
        await engine.dispose()


async def call(w, client, tool, args):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, w.owner)
            user = SimpleNamespace(tenant_id=w.owner, user_id=None, email="tech@liveoakit.com")
            return await ep.make_request(ep.RequestIn(tool=tool, client_id=client, args=args), user, db)
    finally:
        await engine.dispose()


async def approvals(w):
    engine = create_async_engine(PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            return (await conn.execute(text("select status, risk_level, requested_by, title, action from agent_approvals where tenant_id = :t"), {"t": w.owner})).all()
    finally:
        await engine.dispose()


async def test_a_press_creates_one_pending_approval_with_every_value_and_runs_nothing(world):
    out = await call(world, world.acme, "reset_mfa", {"user": "ann@acme.com", "reason": "lost phone"})
    assert out["status"] == "pending" and out["risk"] == "high" and "Nothing has been run" in out["note"]
    rows = await approvals(world)
    assert len(rows) == 1
    status, risk, by, title, action = rows[0]
    assert (status, risk, by, title) == ("pending", "high", "toolbox:tech@liveoakit.com", "Reset a person's MFA: ann@acme.com")
    assert action == {"kind": "toolbox", "tool": "reset_mfa", "client_id": str(world.acme), "client": "Acme", "args": {"user": "ann@acme.com", "reason": "lost phone"}}


async def test_a_bad_request_or_a_foreign_client_creates_nothing(world):
    with pytest.raises(HTTPException) as e:
        await call(world, world.acme, "reset_mfa", {"user": "ann@acme.com"})
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e2:
        await call(world, world.stranger, "reset_mfa", {"user": "a@b.co", "reason": "x"})
    assert e2.value.status_code == 404
    assert await approvals(world) == []

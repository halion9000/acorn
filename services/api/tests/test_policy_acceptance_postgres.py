"""Policy acceptance on a REAL Postgres: recording is idempotent, needs saved text, refuses a version that does not exist or a future day, and another owner sees nothing.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database, migration 205 applied)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import governance as ep
from app.api.v1.endpoints.governance import AcceptanceIn, ItemIn, VersionIn
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]
TODAY = datetime.now(UTC).date()


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    async def noop(**_kw):
        return None

    async def nobody(_db, _owner, _client):
        return [], {}

    monkeypatch.setattr(ep, "emit_audit", noop)
    import app.api.v1.endpoints.identities as ids

    monkeypatch.setattr(ids, "_people", nobody)  # the people list is tested with the Identities page


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    a, b = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (a, b):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"pa-{t.hex[:10]}"})
        await s.commit()
        s.info.update(a=a, b=b)
        yield s
        await off(s)
        for tbl in ("policy_acceptances", "governance_versions", "governance_items"):
            await s.execute(text(f"delete from {tbl} where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine.dispose()


def user(t):
    return SimpleNamespace(tenant_id=t, user_id=None, email="hal@x")


async def test_record_is_idempotent_needs_text_and_is_private(world):
    s, a, b = world, world.info["a"], world.info["b"]
    await off(s)
    item = await ep.create_item(a, ItemIn(kind="policy", title="Acceptable use"), None, user(a), s)
    await off(s)
    with pytest.raises(HTTPException) as e:
        await ep.record_acceptances(a, item.id, AcceptanceIn(emails=["ann@x.com"]), None, user(a), s)
    assert e.value.status_code == 422, "nothing to accept before the text is saved"
    await ep.add_version(a, item.id, VersionIn(body="v1"), None, user(a), s)
    await off(s)
    out = await ep.record_acceptances(a, item.id, AcceptanceIn(emails=["Ann@x.com", "ann@x.com", "bob@x.com", "nope"]), None, user(a), s)
    assert out.version == 1 and sorted(o.email for o in out.others) == ["ann@x.com", "bob@x.com"], "listed nowhere, so shown as others"
    await off(s)
    again = await ep.record_acceptances(a, item.id, AcceptanceIn(emails=["ann@x.com"]), None, user(a), s)
    assert len(again.others) == 2, "same person and version twice changes nothing"
    await off(s)
    for bad in (AcceptanceIn(emails=["c@x.com"], version=2), AcceptanceIn(emails=["c@x.com"], accepted_on=TODAY + timedelta(days=1)), AcceptanceIn(emails=["nope"])):
        with pytest.raises(HTTPException) as e:
            await ep.record_acceptances(a, item.id, bad, None, user(a), s)
        assert e.value.status_code == 422
        await off(s)
    with pytest.raises(HTTPException) as e:
        await ep.list_acceptances(b, item.id, user(b), s)
    assert e.value.status_code == 404, "another owner cannot see it"

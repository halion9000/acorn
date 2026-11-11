"""The NIST coverage endpoint on a REAL Postgres: it lists the seeded NIST CSF controls for the owner's client, calls none of them met without evidence, and refuses another owner's client.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.nist_coverage import nist_for_client
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    owner, other, client, foreign = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t, name in ((owner, "owner"), (other, "other")):
            await s.execute(
                text("insert into tenants (id, name, slug) values (:t, :n, :s)"), {"t": t, "n": name, "s": f"{name}-{t.hex[:10]}"}
            )
        for t, name, parent in ((client, "Acme Test", owner), (foreign, "Not yours", other)):
            await s.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, :n, :s, :p)"),
                {"t": t, "n": name, "s": f"c-{t.hex[:10]}", "p": parent},
            )
        await s.commit()
        s.info.update(owner=owner, client=client, foreign=foreign)
        yield s
        await off(s)
        await s.execute(text("delete from tenants where parent_tenant_id in (:a, :b)"), {"a": owner, "b": other})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": owner, "b": other})
        await s.commit()
    await engine.dispose()


async def test_the_seeded_controls_are_listed_for_a_bare_client_and_none_is_met_without_evidence(world):
    s = world
    await off(s)
    out = await nist_for_client(s.info["client"], SimpleNamespace(tenant_id=s.info["owner"]), s)
    assert out["client_name"] == "Acme Test" and out["framework"] == "nist_csf"
    assert len(out["controls"]) >= 20
    assert out["totals"]["met"] == 0 and out["totals"]["no_evidence"] == len(out["controls"])
    assert {c["control_id"] for c in out["controls"]} >= {"PR.AA-03", "DE.AE-02", "RC.RP-01"}


async def test_another_owners_client_is_a_404(world):
    s = world
    await off(s)
    with pytest.raises(HTTPException) as err:
        await nist_for_client(s.info["foreign"], SimpleNamespace(tenant_id=s.info["owner"]), s)
    assert err.value.status_code == 404

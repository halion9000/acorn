"""A client mapping a person just saved applies to the very next report, though the mapping is kept for a few seconds, against a REAL Postgres.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database).
"""

import os
import uuid

import pytest
from app.api.v1.endpoints import billing
from app.models.client_alias import ClientAlias
from app.services import alias_view as av
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:10]
    w = {k: uuid.uuid4() for k in ("parent", "acme")}
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    av.forget_aliases()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key in ("parent", "acme"):
                parent = w["parent"] if key == "acme" else None
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {"i": w[key], "n": f"av-{key}-{tag}", "s": f"av-{key}-{tag}", "p": parent, "r": "child" if parent else "parent"},
                )
        yield w, engine
    finally:
        av.forget_aliases()
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            t = [str(w["parent"]), str(w["acme"])]
            for table in ("client_license_counts", "client_license_history", "client_aliases"):
                await conn.execute(text(f"delete from {table} where tenant_id = any(cast(:t as uuid[]))"), {"t": t})
            await conn.execute(text("delete from tenants where id = :c"), {"c": w["acme"]})
            await conn.execute(text("delete from tenants where id = :p"), {"p": w["parent"]})
        await engine.dispose()


def report():
    return billing.LicenseCountsReport(vendor="huntress", vendor_client_id="7", counts=[billing.LicenseCountIn(item="Agents", unit="device", count=12)])


async def post(engine, w):
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
        out = await billing.apply_license_counts(db, w["parent"], report())
        await db.commit()
        return out


async def test_a_mapping_saved_through_the_orm_applies_to_the_next_report_at_once_and_an_ignore_does_too(world):
    w, engine = world
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
        db.add(ClientAlias(tenant_id=w["parent"], vendor="huntress", vendor_client_id="7", vendor_client_name="Seven", normalized_name="seven", match_source="manual"))
        await db.commit()
    first = await post(engine, w)
    assert (first.accepted, first.unmapped) == (0, 1), "not mapped yet"
    # The mapping is saved now. The report that follows is within the few seconds the view is kept, and must still see it.
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
        alias = (await db.execute(select(ClientAlias).where(ClientAlias.tenant_id == w["parent"], ClientAlias.vendor_client_id == "7"))).scalar_one()
        alias.child_tenant_id = w["acme"]
        await db.commit()
    second = await post(engine, w)
    assert (second.accepted, second.unmapped) == (1, 0), "mapped: the next report is stored"
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
        alias = (await db.execute(select(ClientAlias).where(ClientAlias.tenant_id == w["parent"], ClientAlias.vendor_client_id == "7"))).scalar_one()
        alias.ignored = True
        await db.commit()
    third = await post(engine, w)
    assert (third.accepted, third.ignored) == (0, 1), "ignored: the next report is skipped"

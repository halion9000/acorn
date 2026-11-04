"""TLS-RPT policies stored and summarised against a REAL Postgres as the restricted application role.

The SQLite tests replace the cross-tenant block with a no-op, so they cannot show that a policy is written under the CLIENT's tenant under row-level security, that a report read twice is stored once,
or that the overview (read the way a signed-in owner's request reads it: a session pinned to the owner's tenant) sees the owner's clients and never another organization's. Opt in with AISOC_TEST_PG_URL
and AISOC_TEST_PG_APP_URL (a disposable, fully migrated database).
"""

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.dmarc import tls_overview
from app.db import rls_hook  # noqa: F401  (installs the listener that makes a tagged session work)
from app.db.rls_sessions import mark_platform, mark_tenant
from app.services import dmarc_store as store
from app.services.tls_report import TlsPolicy
from app.services.tls_report import TlsReport as Parsed
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.test_dmarc_store_postgres import world as dmarc_world  # noqa: F401  (the tenants and people the domains match to)

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
    ),
]


@pytest.fixture
async def world(dmarc_world):  # noqa: F811  (a fixture takes the imported fixture by name)
    ids, domains = dmarc_world
    yield ids, domains
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(
                text("delete from tls_reports where tenant_id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in ids.values()]}
            )
    finally:
        await owner.dispose()


def tls_report(domain, report_id="t1", success=90, failure=10, kinds=(("certificate-expired", 7), ("starttls-not-supported", 3))):
    now = datetime.now(UTC)
    return Parsed(
        "google.com", report_id, now - timedelta(hours=1), now, [TlsPolicy(domain, "sts", success, failure, list(kinds))]
    ), TlsPolicy(domain, "sts", success, failure, list(kinds))


async def store_as_platform(owner_id, domain, report_id="t1", **kw):
    report, policy = tls_report(domain, report_id, **kw)
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            mark_platform(db)
            out = await store.store_tls_policy(db, owner_id, report, policy)
            await db.commit()
            return out
    finally:
        await engine.dispose()


async def overview_as(owner_id):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            mark_tenant(db, owner_id)
            return await tls_overview(SimpleNamespace(tenant_id=owner_id), db, days=30)
    finally:
        await engine.dispose()


async def test_a_policy_is_stored_under_the_client_whose_people_use_the_domain(world):
    ids, domains = world
    out = await store_as_platform(ids["owner"], domains["acme"])
    assert (out.outcome, out.tenant_id, out.matched) == ("stored", ids["acme"], True)


async def test_a_report_read_twice_is_stored_once(world):
    ids, domains = world
    await store_as_platform(ids["owner"], domains["acme"])
    again = await store_as_platform(ids["owner"], domains["acme"], success=1, failure=1)
    assert again.outcome == "duplicate" and again.tenant_id == ids["acme"]
    overview = await overview_as(ids["owner"])
    (row,) = (d for d in overview.domains if d.domain == domains["acme"])
    assert (row.reports, row.success, row.failure) == (1, 90, 10), "the second read must not add to the counts"


async def test_the_overview_sums_a_clients_reports_and_names_why_sessions_failed(world):
    ids, domains = world
    await store_as_platform(ids["owner"], domains["acme"], report_id="t1")
    await store_as_platform(ids["owner"], domains["acme"], report_id="t2", success=10, failure=0, kinds=())
    overview = await overview_as(ids["owner"])
    (row,) = (d for d in overview.domains if d.domain == domains["acme"])
    assert (row.client_id, row.matched, row.reports, row.success, row.failure) == (str(ids["acme"]), True, 2, 100, 10)
    assert [(f.type, f.count) for f in row.failures] == [("certificate-expired", 7), ("starttls-not-supported", 3)]


async def test_the_overview_never_shows_another_organizations_domain(world):
    ids, domains = world
    theirs = await store_as_platform(ids["owner"], domains["stranger"])
    assert (theirs.tenant_id, theirs.matched) == (ids["owner"], False), "a client of another organization is not this owner's to claim"
    mine = await overview_as(ids["owner"])
    other = await overview_as(ids["other_owner"])
    # An unmatched domain is kept under the owner whose mailbox received it, so it shows for that owner only, flagged as not matched to a client.
    assert [d.matched for d in mine.domains if d.domain == domains["stranger"]] == [False]
    assert [
        d for d in other.domains if d.domain == domains["stranger"]
    ] == [], "the other organization must not see a report that arrived in this owner's mailbox"

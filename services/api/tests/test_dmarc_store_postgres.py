"""Storing DMARC reports against a REAL Postgres as the restricted application role, the way the mailbox reader does it: a platform session (no tenant, the cross-tenant switch on).

The SQLite tests replace the cross-tenant block with a no-op, so they cannot show whether the matching read sees the owner's clients (and only them), whether the report is written under the CLIENT's tenant
under row-level security, or whether a report read twice is stored once. Opt in with AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL (a disposable, fully migrated database).
"""

import os
import uuid
from datetime import UTC, datetime

import pytest
from app.db import rls_hook  # noqa: F401  (installs the listener that makes a platform-marked session work)
from app.db.rls_sessions import mark_platform
from app.services import dmarc_store as store
from app.services.dmarc_report import DmarcReport as Parsed
from app.services.dmarc_report import Record
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
    ),
]


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:10]
    ids = {k: uuid.uuid4() for k in ("owner", "acme", "birch", "other_owner", "stranger")}
    domains = {"acme": f"acme-{tag}.example", "stranger": f"stranger-{tag}.example", "birch": f"birch-{tag}.example"}
    owner = create_async_engine(PG_URL)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, tid in ids.items():
                parent = {"acme": "owner", "birch": "owner", "stranger": "other_owner"}.get(key)
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {
                        "i": tid,
                        "n": f"{key}-{tag}",
                        "s": f"{key}-{tag}",
                        "p": ids[parent] if parent else None,
                        "r": "child" if parent else "parent",
                    },
                )
            for who in ("acme", "birch", "stranger"):
                await conn.execute(
                    text(
                        "insert into identity_mfa_users (tenant_id, source, user_id, upn, enabled, admin, licensed, registered, capable, ca_enforced, security_defaults, snapshot_id) "
                        "values (:t, 'cipp', 'u1', :upn, true, false, true, true, true, false, false, gen_random_uuid())"
                    ),
                    {"t": ids[who], "upn": f"pat@{domains[who]}"},
                )
        yield ids, domains
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            everyone = [str(x) for x in ids.values()]
            for table in ("dmarc_reports", "identity_mfa_users"):
                await conn.execute(text(f"delete from {table} where tenant_id = any(cast(:t as uuid[]))"), {"t": everyone})
            await conn.execute(
                text("delete from tenants where id = any(cast(:t as uuid[])) and parent_tenant_id is not null"), {"t": everyone}
            )
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": everyone})
        await owner.dispose()


def report(domain, report_id="r1", count=10):
    now = datetime.now(UTC)
    return Parsed(
        "google.com",
        "noreply@google.com",
        report_id,
        domain,
        now,
        now,
        "none",
        [Record("1.2.3.4", count, "none", True, True, domain, domain)],
    )


async def store_as_platform(owner_id, parsed):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            mark_platform(db)
            out = await store.store_report(db, owner_id, parsed)
            await db.commit()
            return out
    finally:
        await engine.dispose()


async def rows_of(domain):
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with owner.connect() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            return (await conn.execute(text("select tenant_id, matched, total from dmarc_reports where domain = :d"), {"d": domain})).all()
    finally:
        await owner.dispose()


async def test_a_report_is_stored_under_the_client_whose_people_use_the_domain(world):
    ids, domains = world
    out = await store_as_platform(ids["owner"], report(domains["acme"]))
    assert (out.outcome, out.tenant_id, out.matched) == ("stored", ids["acme"], True)
    assert [(r[0], r[1], r[2]) for r in await rows_of(domains["acme"])] == [(ids["acme"], True, 10)]


async def test_a_report_read_twice_is_stored_once(world):
    ids, domains = world
    await store_as_platform(ids["owner"], report(domains["acme"]))
    again = await store_as_platform(ids["owner"], report(domains["acme"], count=99))
    assert again.outcome == "duplicate" and again.tenant_id == ids["acme"]
    assert len(await rows_of(domains["acme"])) == 1


async def test_another_organizations_client_is_never_matched_and_an_unknown_domain_is_kept_under_the_owner(world):
    ids, domains = world
    theirs = await store_as_platform(ids["owner"], report(domains["stranger"]))
    assert (theirs.tenant_id, theirs.matched) == (ids["owner"], False), "a client of another organization is not this owner's to claim"
    unknown = await store_as_platform(ids["owner"], report(f"nobody-{uuid.uuid4().hex[:6]}.example"))
    assert (unknown.tenant_id, unknown.matched) == (ids["owner"], False)


async def test_two_different_reports_for_one_domain_are_both_kept(world):
    ids, domains = world
    await store_as_platform(ids["owner"], report(domains["acme"], report_id="r1"))
    second = await store_as_platform(ids["owner"], report(domains["acme"], report_id="r2"))
    assert second.outcome == "stored"
    assert len(await rows_of(domains["acme"])) == 2

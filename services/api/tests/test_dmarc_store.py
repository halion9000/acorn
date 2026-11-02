"""Storing DMARC reports per client: matching the domain to a client, storing each report once, keeping what cannot be matched."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime

import pytest
from app.db.database import Base
from app.models.dmarc import DmarcReport
from app.models.identity_source import IdentitySource
from app.models.signin import IdentityMfaUser
from app.models.tenant import Tenant
from app.services import dmarc_store as store
from app.services.dmarc_report import DmarcReport as Parsed
from app.services.dmarc_report import Record
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TABLES = [m.__table__ for m in (Tenant, IdentitySource, IdentityMfaUser, DmarcReport)]


@pytest.fixture(autouse=True)
def no_rls(monkeypatch):
    @contextlib.asynccontextmanager
    async def plain(_db):
        yield

    monkeypatch.setattr(store, "cross_tenant_reads", plain)  # the row-level-security switch is Postgres-only


def run(coro_fn):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as c:
            await c.run_sync(lambda conn: Base.metadata.create_all(conn, tables=TABLES))
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            try:
                return await coro_fn(s)
            finally:
                await engine.dispose()

    return asyncio.run(main())


async def tenant(s, name, parent=None):
    t = Tenant(id=uuid.uuid4(), name=name, slug=f"{name}-{uuid.uuid4().hex[:6]}".lower(), parent_tenant_id=parent)
    s.add(t)
    await s.flush()
    return t


def person(tenant_id, upn, via="mfa"):
    if via == "mfa":
        return IdentityMfaUser(tenant_id=tenant_id, source="m365", user_id=uuid.uuid4().hex, upn=upn, snapshot_id=uuid.uuid4())
    return IdentitySource(tenant_id=tenant_id, vendor="huntress", external_id=uuid.uuid4().hex, email=upn)


def report(domain="client.com", report_id="r1", reporter="google.com", records=None):
    recs = records if records is not None else [Record("1.2.3.4", 40, "none", True, True, domain, domain), Record("9.9.9.9", 5, "quarantine", False, False, domain, "evil.example")]
    return Parsed(reporter, "noreply@google.com", report_id, domain, datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 2, tzinfo=UTC), "none", recs)


def test_a_report_goes_to_the_client_whose_people_use_the_domain():
    async def body(s):
        owner = await tenant(s, "Owner")
        acme, birch = await tenant(s, "Acme", owner.id), await tenant(s, "Birch", owner.id)
        s.add_all([person(acme.id, "a@client.com"), person(acme.id, "b@client.com", "src"), person(birch.id, "c@other.com")])
        await s.commit()
        out = await store.store_report(s, owner.id, report())
        await s.commit()
        row = (await s.execute(select(DmarcReport))).scalar_one()
        return out, acme.id, row

    out, acme_id, row = run(body)
    assert (out.outcome, out.tenant_id, out.matched) == ("stored", acme_id, True)
    assert (row.domain, row.reporter, row.report_id, row.total, row.passed, row.failed, row.policy) == ("client.com", "google.com", "r1", 45, 40, 5, "none")
    assert row.rows[0]["ip"] == "1.2.3.4" and row.rows[0]["pass"] is True and row.rows[1]["disposition"] == "quarantine"


def test_a_report_nobody_can_be_matched_to_is_kept_under_the_owner_marked_unmatched():
    async def body(s):
        owner = await tenant(s, "Owner")
        acme = await tenant(s, "Acme", owner.id)
        s.add(person(acme.id, "a@acme.example"))
        await s.commit()
        out = await store.store_report(s, owner.id, report("unknown.example"))
        return out, owner.id

    out, owner_id = run(body)
    assert (out.tenant_id, out.matched) == (owner_id, False)


def test_a_tie_between_two_clients_is_not_guessed():
    async def body(s):
        owner = await tenant(s, "Owner")
        a, b = await tenant(s, "A", owner.id), await tenant(s, "B", owner.id)
        s.add_all([person(a.id, "x@shared.example"), person(b.id, "y@shared.example")])
        await s.commit()
        return await store.client_for_domain(s, owner.id, "shared.example"), owner.id

    client, _ = run(body)
    assert client is None


def test_the_domain_is_matched_without_regard_to_case_and_only_among_the_owners_own_clients():
    async def body(s):
        owner, stranger = await tenant(s, "Owner"), await tenant(s, "Stranger")
        mine, theirs = await tenant(s, "Mine", owner.id), await tenant(s, "Theirs", stranger.id)
        s.add_all([person(mine.id, "A@Client.COM"), person(theirs.id, "z@client.com"), person(theirs.id, "y@onlytheirs.example")])
        await s.commit()
        return await store.client_for_domain(s, owner.id, "CLIENT.com."), await store.client_for_domain(s, owner.id, "onlytheirs.example"), mine.id

    got, theirs_only, mine = run(body)
    assert got == mine and theirs_only is None


def test_the_same_report_is_stored_once_however_often_it_is_read():
    async def body(s):
        owner = await tenant(s, "Owner")
        await s.commit()
        first = await store.store_report(s, owner.id, report())
        await s.commit()
        again = await store.store_report(s, owner.id, report())
        other = await store.store_report(s, owner.id, report(report_id="r2"))
        await s.commit()
        return first.outcome, again.outcome, other.outcome, len((await s.execute(select(DmarcReport))).scalars().all())

    assert run(body) == ("stored", "duplicate", "stored", 2)


def test_only_the_biggest_sources_are_kept_when_a_report_is_huge(monkeypatch):
    monkeypatch.setattr(store, "MAX_ROWS_STORED", 3)
    recs = [Record(f"10.0.0.{i}", i, "none", True, True, "client.com", "client.com") for i in range(1, 8)]
    rows = store.compact_rows(report(records=recs))
    assert [r["count"] for r in rows] == [7, 6, 5]


def test_the_managing_companys_own_domain_is_matched_to_itself_not_left_unmatched():
    async def body(s):
        owner = await tenant(s, "Live Oak")
        acme = await tenant(s, "Acme", owner.id)
        s.add_all([person(owner.id, "hal@goliveoak.com"), person(acme.id, "a@acme.example")])
        await s.commit()
        own = await store.store_report(s, owner.id, report("goliveoak.com", "own1"))
        theirs = await store.store_report(s, owner.id, report("acme.example", "c1"))
        return own, theirs, owner.id, acme.id

    own, theirs, owner_id, acme_id = run(body)
    assert (own.tenant_id, own.matched) == (owner_id, True)
    assert (theirs.tenant_id, theirs.matched) == (acme_id, True)  # a client's domain still goes to the client, not the owner

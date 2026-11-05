"""The newest BEC search shown on each Identities row: found by any of the person's addresses, the newest wins, an abandoned open search shows as failed, and a list never fails because of it."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.api.v1.endpoints import identities as ep
from app.db.database import Base
from app.models.bec_case import BecCase
from app.models.tenant import Tenant
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
ACME, BIRCH = uuid.uuid4(), uuid.uuid4()


def person(email="amy@acme.com", client=ACME, aliases=()):
    return ep.PersonOut(
        key=f"{client}:{email}",
        client_id=client,
        email=email,
        kind="user",
        admin=False,
        mfa="unknown",
        tools=[],
        open_alerts=0,
        aliases=[ep.AliasOut(email=a, reason="merged") for a in aliases],
    )


def test_a_search_for_any_address_of_the_person_shows_on_the_row_and_the_newest_start_wins():
    older, newer = NOW - timedelta(days=5), NOW - timedelta(days=1)
    cases = {(ACME, "amy@acme.com"): ("done", "Low", older), (ACME, "amy@acme.onmicrosoft.com"): ("done", "High", newer)}
    out = ep.attach_bec([person(aliases=["amy@acme.onmicrosoft.com"])], cases)
    assert (out[0].bec.status, out[0].bec.level, out[0].bec.at) == ("done", "High", newer)


def test_nobody_else_gets_a_badge_and_another_clients_search_is_not_theirs():
    cases = {(BIRCH, "amy@acme.com"): ("done", "High", NOW)}
    out = ep.attach_bec([person(), person(email="zed@acme.com")], cases)
    assert [p.bec for p in out] == [None, None], "the same address at another client is a different person"


def test_the_address_matches_whatever_its_case():
    out = ep.attach_bec([person(email="Amy@Acme.com")], {(ACME, "amy@acme.com"): ("running", None, NOW)})
    assert out[0].bec.status == "running" and out[0].email == "Amy@Acme.com", "the address shown is untouched"


@pytest.fixture
def plain(monkeypatch):
    @contextlib.asynccontextmanager
    async def no_rls(_db):
        yield

    monkeypatch.setattr(ep, "cross_tenant_reads", no_rls)


def run(body):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as c:
            await c.run_sync(lambda conn: Base.metadata.create_all(conn, tables=[Tenant.__table__, BecCase.__table__]))
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            try:
                s.add_all([Tenant(id=ACME, name="Acme", slug="acme"), Tenant(id=BIRCH, name="Birch", slug="birch")])
                await s.flush()
                return await body(s)
            finally:
                await engine.dispose()

    return asyncio.run(main())


def case(tenant, email, status, created, updated=None, level=None):
    return BecCase(
        id=uuid.uuid4(),
        tenant_id=tenant,
        case_ref=f"BEC-{uuid.uuid4().hex[:6]}",
        email=email,
        status=status,
        summary={"level": level} if level else {},
        created_at=created,
        updated_at=updated or created,
    )


def test_the_page_gets_each_persons_newest_search_from_the_database_and_a_forgotten_open_one_shows_as_failed(plain, monkeypatch):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.replace(tzinfo=None)  # SQLite hands datetimes back without a zone

    monkeypatch.setattr(ep, "datetime", Frozen)

    async def body(s):
        s.add_all(
            [
                case(ACME, "amy@acme.com", "done", NOW - timedelta(days=3), level="Low"),
                case(ACME, "amy@acme.com", "done", NOW - timedelta(days=1), level="High"),
                case(ACME, "kim@acme.com", "running", NOW - timedelta(hours=3), updated=NOW - timedelta(hours=3)),
                case(ACME, "lee@acme.com", "failed", NOW - timedelta(days=2)),
                case(BIRCH, "amy@acme.com", "done", NOW, level="Medium"),
            ]
        )
        await s.commit()
        return await ep.with_bec_badges(
            s, [person("amy@acme.com"), person("kim@acme.com"), person("lee@acme.com"), person("nobody@acme.com")]
        )

    out = run(body)
    badges = [(p.email, p.bec.status if p.bec else None, p.bec.level if p.bec else None) for p in out]
    assert badges == [
        ("amy@acme.com", "done", "High"),
        ("kim@acme.com", "failed", None),
        ("lee@acme.com", "failed", None),
        ("nobody@acme.com", None, None),
    ]


def test_a_list_page_still_loads_when_the_searches_cannot_be_read():
    class Broken:
        def begin_nested(self):
            raise RuntimeError("relation bec_cases does not exist")

    items = [person()]
    assert asyncio.run(ep.with_bec_badges(Broken(), items)) == items
    assert asyncio.run(ep.with_bec_badges(Broken(), [])) == []

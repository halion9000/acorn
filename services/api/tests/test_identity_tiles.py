"""The extra Identities tiles: guests, failed sign-ins in the last 24 hours, and people who look like brute-force targets."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.api.v1.endpoints import identities as ep
from app.db.database import Base
from app.models.signin import SigninEvent
from app.models.tenant import Tenant
from app.services import identity_people as ip
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.test_identity_people import NOW, ms, src

A = uuid.uuid4()


def run(coro_fn):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as c:
            await c.run_sync(lambda conn: Base.metadata.create_all(conn, tables=[Tenant.__table__, SigninEvent.__table__]))
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            try:
                return await coro_fn(s)
            finally:
                await engine.dispose()

    return asyncio.run(main())


@pytest.fixture(autouse=True)
def plain(monkeypatch):
    @contextlib.asynccontextmanager
    async def no_rls(_db):
        yield

    monkeypatch.setattr(ep, "cross_tenant_reads", no_rls)


def event(tenant, who, ok, minutes_ago=30, code=None):
    return SigninEvent(
        tenant_id=tenant,
        source="m365",
        source_id=uuid.uuid4().hex,
        user_principal=who,
        success=ok,
        error_code=code,
        occurred_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )


def test_failed_signins_are_counted_for_24_hours_and_a_person_with_ten_is_flagged():
    async def body(s):
        t = Tenant(id=A, name="Acme", slug="acme")
        other = Tenant(id=uuid.uuid4(), name="Other", slug="other")
        s.add_all([t, other])
        await s.flush()
        s.add_all(
            [event(A, "bob@acme.com", False) for _ in range(10)]  # exactly ten: flagged
            + [event(A, "amy@acme.com", False) for _ in range(9)]  # nine: counted, not flagged
            + [event(A, "amy@acme.com", True) for _ in range(5)]  # successes are not failures
            + [event(A, "old@acme.com", False, minutes_ago=60 * 25)]  # older than 24 hours
            + [event(other.id, "x@other.com", False) for _ in range(40)]  # another tenant, outside the scope
        )
        await s.commit()
        return await ep.signin_failures(s, [A], datetime.now(UTC))

    assert run(body) == (19, 1)


def test_a_sign_in_that_only_asked_for_more_proof_is_not_a_failure():
    async def body(s):
        s.add(Tenant(id=A, name="Acme", slug="acme"))
        await s.flush()
        s.add_all(
            [event(A, "bob@acme.com", False, code=50074) for _ in range(12)]
            + [event(A, "bob@acme.com", False, code=50076) for _ in range(3)]
            + [event(A, "bob@acme.com", False, code=50126) for _ in range(2)]
        )
        await s.commit()
        return await ep.signin_failures(s, [A], datetime.now(UTC))

    assert run(body) == (2, 0)  # only the two wrong-password errors (50126) count


def test_nobody_failing_gives_zero_not_none():
    async def body(s):
        s.add(Tenant(id=A, name="Acme", slug="acme"))
        await s.commit()
        return await ep.signin_failures(s, [A], datetime.now(UTC))

    assert run(body) == (0, 0)


def test_guests_are_counted_from_the_kind_of_account():
    people = ip.build_people(
        {A: "Acme"},
        [ms(A, "amy@acme.com"), ms(A, "ext@partner.com", user_type="Guest")],
        [src(A, "cipp", "g2@other.com", kind="guest")],
        NOW,
    )
    assert ep.summarize(people).guests == 2


# ---- the two sign-in tiles open lists, and disabled accounts are not "missing" anything --------------------------------------------------------------------


def test_the_failed_signin_and_brute_force_lists_hold_exactly_the_people_the_tiles_counted():
    async def body(s):
        other = uuid.uuid4()
        s.add_all([Tenant(id=A, name="Acme", slug="acme"), Tenant(id=other, name="Other", slug="other")])
        await s.flush()
        s.add_all(
            [event(A, "Bob@Acme.com", False) for _ in range(10)]  # ten: brute force (and failed); the address is matched ignoring case
            + [event(A, "amy@acme.com", False) for _ in range(2)]  # failed only
            + [event(A, "ok@acme.com", True) for _ in range(30)]  # successes never count
            + [event(A, "mfa@acme.com", False, code=50074) for _ in range(20)]  # asked for more proof: not a failure
            + [event(A, "old@acme.com", False, minutes_ago=60 * 25)]  # older than a day
            + [event(other, "x@other.com", False) for _ in range(40)]  # outside the scope
        )
        await s.commit()
        now = datetime.now(UTC)
        return (
            await ep.failing_people(s, [A], now, 1),
            await ep.failing_people(s, [A], now, ep.BRUTE_FORCE_FAILURES),
            await ep.signin_failures(s, [A], now),
        )

    failed, brute, (total, flagged) = run(body)
    assert failed == {(A, "bob@acme.com"), (A, "amy@acme.com")}
    assert brute == {(A, "bob@acme.com")}
    assert len(brute) == flagged and total == 12


def test_the_signin_filter_keeps_only_those_people_and_leaves_the_tile_numbers_alone():
    people = ip.build_people({A: "Acme"}, [ms(A, "bob@acme.com"), ms(A, "amy@acme.com"), ms(A, "zed@acme.com")], [], NOW)
    failing = {(A, "bob@acme.com")}
    kept = [p for p in people if (p.tenant_id, p.email.lower()) in failing]
    assert [p.email for p in ip.filter_people(kept)] == ["bob@acme.com"]
    assert ep.summarize(people).total == 3  # the summary is always everyone


def test_a_disabled_account_is_not_counted_or_listed_as_missing_multi_factor_or_a_backup_problem():
    people = ip.build_people(
        {A: "Acme"},
        [ms(A, "on@acme.com", enabled=True), ms(A, "off@acme.com", enabled=False)],
        [
            src(A, "dropsuite", "on@acme.com", enabled=True, details={"last_backup": None}),
            src(A, "dropsuite", "off@acme.com", enabled=True, details={"last_backup": None}),
        ],
        NOW,
    )
    for p in people:
        p.mfa = "none"
    problems = [p.email for p in ip.filter_people(people, backup="problem")]
    no_mfa = [p.email for p in ip.filter_people(people, mfa="none")]
    assert problems == ["on@acme.com"] and no_mfa == ["on@acme.com"]
    s = ep.summarize(people)
    assert (s.backup_problems, s.without_mfa) == (1, 1)  # the tiles and the lists agree
    assert [p.email for p in ip.filter_people(people, disabled=True)] == ["off@acme.com"]  # a disabled account is still found as disabled

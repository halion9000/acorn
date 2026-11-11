"""Listing and taking back the owner's hand decisions on the Identities page (a merge, or a "not the same person" mark), on a real (in-memory) database.

Without this a mistaken "not the same person" could never be undone: it stops every automatic rule from joining the pair, and nothing showed that it existed.
"""

import asyncio
import contextlib
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import identity_merges as ep
from app.db.database import Base
from app.models.identity_merge import IdentityMerge
from app.services import identity_people as ip
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.test_identity_people import NOW, ms

A, B = uuid.uuid4(), uuid.uuid4()
OWNER = uuid.uuid4()
USER = type("U", (), {"tenant_id": OWNER, "user_id": uuid.uuid4()})()
NAMES = {A: "Acme", B: "Other"}


def acct(tenant, upn, **over):
    return ms(tenant, upn, **{"licensed": False, **over})


def build(users, separate=None):
    return ip.build_people(NAMES, list(users), [], NOW, separate=separate)


@pytest.fixture
def wired(monkeypatch):
    audit = AsyncMock()
    monkeypatch.setattr(ep, "_scope", AsyncMock(return_value=([A], {A: "Acme"})))
    monkeypatch.setattr(ep, "_as", lambda db, owner, tid: contextlib.nullcontext())
    monkeypatch.setattr(ep, "emit_audit", audit)
    # Brandon is known by two addresses (joined by his display name); Adam by one.
    people = build([acct(A, "bmoore@acme.com", display_name="brandon.moore@acme.com"), acct(A, "brandon.moore@acme.com", display_name="Brandon Moore"), acct(A, "adam@acme.com")])
    monkeypatch.setattr(ep, "_people", AsyncMock(return_value=(people, {})))
    return audit


def run(fn):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as c:
            await c.run_sync(lambda conn: Base.metadata.create_all(conn, tables=[IdentityMerge.__table__]))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as s:
                return await fn(s)
        finally:
            await engine.dispose()

    return asyncio.run(main())


def seed(s, rows):
    for tenant, a, b, kind, age in rows:
        s.add(IdentityMerge(tenant_id=tenant, address_a=a, address_b=b, kind=kind, created_at=NOW - timedelta(hours=age)))


ROWS = [
    (A, "adam@acme.com", "bmoore@acme.com", "separate", 3),
    (A, "bmoore@acme.com", "zed@acme.com", "merge", 1),
    (A, "adam@acme.com", "zed@acme.com", "separate", 2),
    (B, "a@other.com", "b@other.com", "merge", 0),
]


def test_all_of_a_clients_decisions_are_listed_newest_first_and_never_another_clients(wired):
    async def body(s):
        seed(s, ROWS)
        await s.commit()
        return await ep.list_decisions(USER, s, client_id=A)

    out = run(body)
    assert [(d.address_a, d.address_b, d.kind) for d in out.items] == [
        ("bmoore@acme.com", "zed@acme.com", "merge"),
        ("adam@acme.com", "zed@acme.com", "separate"),
        ("adam@acme.com", "bmoore@acme.com", "separate"),
    ]


def test_one_persons_decisions_are_those_touching_any_address_they_are_known_by(wired):
    async def body(s):
        seed(s, ROWS)
        await s.commit()
        return await ep.list_decisions(USER, s, client_id=A, email="brandon.moore@acme.com")  # asked by the OTHER address of the same person

    out = run(body)
    assert {(d.address_a, d.address_b) for d in out.items} == {("adam@acme.com", "bmoore@acme.com"), ("bmoore@acme.com", "zed@acme.com")}


def test_an_address_nobody_knows_still_lists_the_decisions_naming_it(wired):
    async def body(s):
        seed(s, ROWS)
        await s.commit()
        return await ep.list_decisions(USER, s, client_id=A, email="zed@acme.com")

    assert len(run(body).items) == 2


def test_a_decision_is_removed_whichever_way_round_it_is_named_and_audited(wired):
    async def body(s):
        seed(s, ROWS)
        await s.commit()
        await ep.remove_decision(MagicMock(), USER, s, client_id=A, address_a="bmoore@acme.com", address_b="adam@acme.com")
        left = (await s.execute(select(IdentityMerge.address_a, IdentityMerge.address_b).where(IdentityMerge.tenant_id == A))).all()
        other = (await s.execute(select(IdentityMerge).where(IdentityMerge.tenant_id == B))).scalars().all()
        return left, other

    left, other = run(body)
    assert ("adam@acme.com", "bmoore@acme.com") not in left and len(left) == 2
    assert len(other) == 1, "another client's decision is untouched"
    kw = wired.await_args.kwargs
    assert kw["action"] == "identities:decision_removed" and kw["tenant_id"] == A and kw["changes"] == {"address": "adam@acme.com", "other": "bmoore@acme.com", "was": "separate"}


def test_removing_a_decision_that_does_not_exist_or_belongs_to_another_client_is_a_404_and_audits_nothing(wired):
    async def body(s, a, b):
        seed(s, ROWS)
        await s.commit()
        await ep.remove_decision(MagicMock(), USER, s, client_id=A, address_a=a, address_b=b)

    for a, b in (("adam@acme.com", "nobody@acme.com"), ("a@other.com", "b@other.com")):
        with pytest.raises(HTTPException) as e:
            run(lambda s, a=a, b=b: body(s, a, b))
        assert e.value.status_code == 404
    wired.assert_not_awaited()


def test_a_bad_address_is_refused(wired):
    async def body(s):
        await ep.remove_decision(MagicMock(), USER, s, client_id=A, address_a="not an address", address_b="adam@acme.com")

    with pytest.raises(HTTPException) as e:
        run(body)
    assert e.value.status_code == 422


def test_taking_back_a_not_the_same_person_mark_lets_the_rules_join_the_pair_again(wired):
    users = [acct(A, "bmoore@acme.com", display_name="brandon.moore@acme.com"), acct(A, "brandon.moore@acme.com", display_name="Brandon Moore")]
    pair = (A, *ep.ordered("bmoore@acme.com", "brandon.moore@acme.com"))
    assert len(build(users, separate=[pair])) == 2, "marked: kept apart"
    assert len(build(users, separate=[])) == 1, "mark removed: joined by the rule again"


def test_the_routes_need_the_right_permissions():
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    assert set(required_permissions(found[("GET", "/identities/merges")])) == {"alerts:read"}
    assert set(required_permissions(found[("DELETE", "/identities/merges")])) == {"alerts:write"}

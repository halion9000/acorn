"""Changing your own password, an administrator resetting someone's, and signing a person out everywhere (A11, A12). Real routers, a real database, the fake Redis from conftest."""

import asyncio
import uuid

import pytest
from app.api.v1 import deps
from app.api.v1.endpoints import auth, tenants
from app.core import token_revocation
from app.core.password_policy import MIN_LENGTH, password_problem
from app.core.security import get_password_hash
from app.db.database import Base
from app.models.login_failure import LoginFailure
from app.models.tenant import ApiKey, Tenant, User
from app.models.user_totp import UserTotp
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

OLD = "correct horse battery staple"
NEW = "a brand new long passphrase"


@pytest.fixture
def world(tmp_path):
    path = tmp_path / "pw.db"
    sync = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(sync, tables=[Tenant.__table__, User.__table__, ApiKey.__table__, LoginFailure.__table__, UserTotp.__table__])
    tenant = Tenant(id=uuid.uuid4(), name="T", slug="t-" + uuid.uuid4().hex[:6])
    other = Tenant(id=uuid.uuid4(), name="U", slug="u-" + uuid.uuid4().hex[:6])
    admin = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        account_name="boss",
        email="boss@example.com",
        username="boss",
        hashed_password=get_password_hash(OLD),
        role="tenant_admin",
    )
    analyst = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        account_name="ann",
        email="ann@example.com",
        username="ann",
        hashed_password=get_password_hash(OLD),
        role="soc_analyst",
    )
    stranger = User(
        id=uuid.uuid4(),
        tenant_id=other.id,
        account_name="eve",
        email="eve@example.com",
        username="eve",
        hashed_password=get_password_hash(OLD),
        role="soc_analyst",
    )
    with Session(sync, expire_on_commit=False) as s:
        s.add_all([tenant, other, admin, analyst, stranger])
        s.commit()
    factory = async_sessionmaker(create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool), expire_on_commit=False)
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(tenants.router)

    async def session():
        async with factory() as s:
            yield s

    app.dependency_overrides[deps.get_db] = session
    yield type("World", (), {"client": TestClient(app), "admin": admin, "analyst": analyst, "stranger": stranger})
    sync.dispose()


def login(world, name, password=OLD):
    return world.client.post("/auth/login", json={"account_name": name, "password": password})


def bearer(r):
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestThePasswordRule:
    def test_it_asks_for_length_and_a_new_value(self):
        assert password_problem("x" * (MIN_LENGTH - 1))
        assert password_problem("x" * MIN_LENGTH) is None
        assert password_problem("y" * 200)
        assert password_problem(" padded password  ")
        assert password_problem(OLD, OLD) == "The new password must be different from the current one."


class TestChangeOwnPassword:
    def test_the_new_password_works_the_old_one_does_not_and_every_session_ends(self, world):
        first, second = login(world, "ann"), login(world, "ann")
        assert world.client.get("/auth/me", headers=bearer(second)).status_code == 200
        r = world.client.post("/auth/password", headers=bearer(first), json={"current_password": OLD, "new_password": NEW})
        assert r.status_code == 200 and r.json()["changed"] is True
        assert world.client.get("/auth/me", headers=bearer(first)).status_code == 401, "the session that changed it ends too"
        assert world.client.get("/auth/me", headers=bearer(second)).status_code == 401, "so does every other session"
        assert world.client.post("/auth/refresh", json={"refresh_token": first.json()["refresh_token"]}).status_code == 401
        assert login(world, "ann", OLD).status_code == 401
        assert login(world, "ann", NEW).status_code == 200

    def test_a_wrong_current_password_changes_nothing(self, world):
        tokens = login(world, "ann")
        r = world.client.post("/auth/password", headers=bearer(tokens), json={"current_password": "not it at all!!", "new_password": NEW})
        assert r.status_code == 403
        assert login(world, "ann", OLD).status_code == 200
        assert world.client.get("/auth/me", headers=bearer(tokens)).status_code == 200

    def test_a_weak_or_unchanged_new_password_is_refused_and_sessions_stay(self, world):
        tokens = login(world, "ann")
        assert (
            world.client.post("/auth/password", headers=bearer(tokens), json={"current_password": OLD, "new_password": "short"}).status_code
            == 422
        )
        assert (
            world.client.post("/auth/password", headers=bearer(tokens), json={"current_password": OLD, "new_password": OLD}).status_code
            == 422
        )
        assert world.client.get("/auth/me", headers=bearer(tokens)).status_code == 200

    def test_it_needs_a_sign_in(self, world):
        assert world.client.post("/auth/password", json={"current_password": OLD, "new_password": NEW}).status_code in (401, 403)


class TestAdminActions:
    def test_an_admin_resets_a_password_and_the_person_is_signed_out(self, world):
        boss, ann = login(world, "boss"), login(world, "ann")
        r = world.client.post(f"/tenants/me/users/{world.analyst.id}/password", headers=bearer(boss), json={"new_password": NEW})
        assert r.status_code == 200 and r.json()["done"] is True
        assert world.client.get("/auth/me", headers=bearer(ann)).status_code == 401
        assert world.client.get("/auth/me", headers=bearer(boss)).status_code == 200, "the admin's own session is untouched"
        assert login(world, "ann", OLD).status_code == 401
        assert login(world, "ann", NEW).status_code == 200

    def test_an_admin_cannot_reset_their_own_password_here_or_use_a_weak_one(self, world):
        boss = login(world, "boss")
        assert (
            world.client.post(f"/tenants/me/users/{world.admin.id}/password", headers=bearer(boss), json={"new_password": NEW}).status_code
            == 403
        )
        assert (
            world.client.post(
                f"/tenants/me/users/{world.analyst.id}/password", headers=bearer(boss), json={"new_password": "short"}
            ).status_code
            == 422
        )
        assert login(world, "ann", OLD).status_code == 200

    def test_a_person_without_user_rights_cannot_reset_anyone(self, world):
        ann = login(world, "ann")
        r = world.client.post(f"/tenants/me/users/{world.admin.id}/password", headers=bearer(ann), json={"new_password": NEW})
        assert r.status_code == 403
        assert login(world, "boss", OLD).status_code == 200

    def test_nobody_can_reach_a_user_of_another_organisation(self, world):
        boss = login(world, "boss")
        assert (
            world.client.post(
                f"/tenants/me/users/{world.stranger.id}/password", headers=bearer(boss), json={"new_password": NEW}
            ).status_code
            == 404
        )
        assert world.client.post(f"/tenants/me/users/{world.stranger.id}/sign-out", headers=bearer(boss)).status_code == 404
        assert login(world, "eve", OLD).status_code == 200

    def test_sign_out_everywhere_ends_their_sessions_but_they_can_sign_in_again(self, world):
        boss, ann = login(world, "boss"), login(world, "ann")
        assert world.client.post(f"/tenants/me/users/{world.analyst.id}/sign-out", headers=bearer(boss)).status_code == 200
        assert world.client.get("/auth/me", headers=bearer(ann)).status_code == 401
        assert world.client.post("/auth/refresh", json={"refresh_token": ann.json()["refresh_token"]}).status_code == 401
        assert world.client.get("/auth/me", headers=bearer(boss)).status_code == 200

    def test_a_store_outage_says_the_sessions_were_not_ended(self, world, revocation_store):
        boss = login(world, "boss")
        revocation_store.down = True
        r = world.client.post(f"/tenants/me/users/{world.analyst.id}/sign-out", headers=bearer(boss))
        assert r.status_code == 503


class TestTheCutoff:
    def test_only_tokens_issued_at_or_before_it_are_refused(self):
        uid = uuid.uuid4()
        asyncio.run(token_revocation.sign_out_everywhere(uid, now=1000))
        assert asyncio.run(token_revocation.signed_out_everywhere({"sub": str(uid), "iat": 999}))
        assert asyncio.run(token_revocation.signed_out_everywhere({"sub": str(uid), "iat": 1000}))
        assert not asyncio.run(token_revocation.signed_out_everywhere({"sub": str(uid), "iat": 1001}))
        assert not asyncio.run(token_revocation.signed_out_everywhere({"sub": str(uuid.uuid4()), "iat": 1}))
        assert not asyncio.run(token_revocation.signed_out_everywhere({"sub": str(uid)})), "no issue time: not judged"

    def test_a_store_outage_while_checking_lets_the_request_through(self, revocation_store):
        revocation_store.down = True
        assert not asyncio.run(token_revocation.signed_out_everywhere({"sub": "x", "iat": 1}))

    def test_the_cutoff_lives_as_long_as_the_longest_token(self, revocation_store):
        asyncio.run(token_revocation.sign_out_everywhere("u1"))
        assert revocation_store.ttls["aisoc:signed-out-after:u1"] > 7 * 86400

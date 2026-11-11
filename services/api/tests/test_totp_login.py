"""Authenticator-app codes on the password sign-in (A13): set up, confirm, sign in with a code, a recovery code, replay, throttling, turning off.

A real (SQLite) database with the real auth and totp routers; time is a variable so codes are exact.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.api.v1 import deps
from app.api.v1.endpoints import auth
from app.api.v1.endpoints import totp as totp_endpoints
from app.core.config import settings
from app.core.security import get_password_hash
from app.db.database import Base
from app.models.login_failure import LoginFailure
from app.models.tenant import ApiKey, Tenant, User
from app.models.user_totp import UserTotp
from app.services import totp, totp_store
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

PASSWORD = "correct horse battery staple"
START = 1_800_000_000.0  # a fixed moment, in seconds


@pytest.fixture
def world(tmp_path, monkeypatch):
    path = tmp_path / "totp.db"
    sync = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(sync, tables=[Tenant.__table__, User.__table__, ApiKey.__table__, LoginFailure.__table__, UserTotp.__table__])
    tenant = Tenant(id=uuid.uuid4(), name="A", slug="a-" + uuid.uuid4().hex[:6])
    me = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="me@a.example",
        username="me",
        account_name="me-acct",
        hashed_password=get_password_hash(PASSWORD),
        role="admin",
        is_active=True,
    )
    with Session(sync, expire_on_commit=False) as s:
        s.add_all([tenant, me])
        s.commit()
    factory = async_sessionmaker(create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool), expire_on_commit=False)

    clock = {"t": START}

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromtimestamp(clock["t"], tz or UTC)

    monkeypatch.setattr(totp_store, "datetime", FakeDatetime)

    async def no_audit(**_kw):
        return None

    monkeypatch.setattr(totp_endpoints, "emit_audit", no_audit)

    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(totp_endpoints.router)

    async def session():
        # Like the real get_db: committed when the request ends without an error.
        async with factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[deps.get_db] = session
    app.dependency_overrides[deps.require_signed_in_session] = lambda: deps.CurrentUser(
        user_id=me.id, tenant_id=tenant.id, role="admin", email="me@a.example"
    )
    yield SimpleNamespace(client=TestClient(app), factory=factory, me=me, clock=clock)
    sync.dispose()


def login(w, **extra):
    return w.client.post("/auth/login", json={"account_name": "me-acct", "password": PASSWORD, **extra})


def turn_on(w):
    """Set up and confirm; returns (secret, recovery codes). Afterwards time moves on one full step so the next code is a new one."""
    secret = w.client.post("/auth/totp/enrol").json()["secret"]
    r = w.client.post("/auth/totp/confirm", json={"code": totp.code_for_step(secret, totp.current_step(w.clock["t"]))})
    assert r.status_code == 200, r.text
    w.clock["t"] += 30
    return secret, r.json()["recovery_codes"]


def code_now(w, secret):
    return totp.code_for_step(secret, totp.current_step(w.clock["t"]))


def test_without_an_authenticator_app_signing_in_is_exactly_as_before(world):
    assert login(world).status_code == 200
    assert world.client.get("/auth/totp").json() == {"enabled": False, "recovery_codes_left": 0}


def test_a_started_but_unconfirmed_setup_changes_nothing_about_signing_in(world):
    r = world.client.post("/auth/totp/enrol").json()
    assert r["otpauth_uri"].startswith("otpauth://totp/") and r["secret"] in r["otpauth_uri"]
    assert world.client.get("/auth/totp").json()["enabled"] is False
    assert login(world).status_code == 200, "no code is asked for until the person has proved they can read one"
    wrong = world.client.post("/auth/totp/confirm", json={"code": "000000"})
    assert wrong.status_code == 400 and world.client.get("/auth/totp").json()["enabled"] is False


def test_once_confirmed_a_password_alone_is_not_enough_and_the_right_code_signs_in(world):
    secret, recovery = turn_on(world)
    assert len(recovery) == 10 and world.client.get("/auth/totp").json() == {"enabled": True, "recovery_codes_left": 10}
    asked = login(world)
    assert asked.status_code == 428 and "authenticator" in asked.json()["detail"]
    assert "access_token" not in asked.text
    assert login(world, totp_code="123456").status_code == 401
    ok = login(world, totp_code=code_now(world, secret))
    assert ok.status_code == 200 and ok.json()["access_token"]


def test_a_code_works_once_so_a_copied_code_cannot_be_replayed(world):
    secret, _ = turn_on(world)
    code = code_now(world, secret)
    assert login(world, totp_code=code).status_code == 200
    assert login(world, totp_code=code).status_code == 401


def test_a_wrong_password_is_refused_before_any_code_is_asked_for(world):
    turn_on(world)
    r = world.client.post("/auth/login", json={"account_name": "me-acct", "password": "wrong"})
    assert r.status_code == 401 and r.status_code != 428, "someone without the password learns nothing about the second factor"


def test_a_recovery_code_signs_in_once_and_then_is_gone(world):
    _, recovery = turn_on(world)
    assert login(world, totp_code=recovery[0]).status_code == 200
    assert login(world, totp_code=recovery[0]).status_code == 401
    assert login(world, totp_code=recovery[1].upper()).status_code == 200
    assert world.client.get("/auth/totp").json()["recovery_codes_left"] == 8


def test_wrong_codes_count_like_wrong_passwords_and_lock_the_account(world, monkeypatch):
    secret, _ = turn_on(world)
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES_PER_ACCOUNT", 2)
    assert login(world, totp_code="111111").status_code == 401
    assert login(world, totp_code="222222").status_code == 401
    assert login(world, totp_code=code_now(world, secret)).status_code == 429, "locked, even with the right code"


def test_the_secret_is_stored_encrypted_never_in_the_clear(world):
    import asyncio

    secret = world.client.post("/auth/totp/enrol").json()["secret"]

    async def stored():
        async with world.factory() as s:
            return (await s.execute(select(UserTotp.secret_enc))).scalar_one()

    enc = asyncio.run(stored())
    assert enc != secret and secret not in enc


def test_turning_it_off_needs_the_password_and_a_code_and_then_signing_in_needs_no_code(world):
    secret, _ = turn_on(world)
    assert world.client.post("/auth/totp/disable", json={"password": "wrong", "code": code_now(world, secret)}).status_code == 403
    assert world.client.post("/auth/totp/disable", json={"password": PASSWORD, "code": "000000"}).status_code == 403
    assert world.client.get("/auth/totp").json()["enabled"] is True
    assert world.client.post("/auth/totp/disable", json={"password": PASSWORD, "code": code_now(world, secret)}).status_code == 200
    assert world.client.get("/auth/totp").json()["enabled"] is False
    assert login(world).status_code == 200


def test_a_second_setup_is_refused_while_one_is_on(world):
    turn_on(world)
    assert world.client.post("/auth/totp/enrol").status_code == 409


def test_new_recovery_codes_need_the_password_and_a_code_and_the_old_ones_stop_working(world):
    secret, old = turn_on(world)
    assert world.client.post("/auth/totp/recovery", json={"password": "wrong", "code": code_now(world, secret)}).status_code == 403
    assert world.client.post("/auth/totp/recovery", json={"password": PASSWORD, "code": "000000"}).status_code == 403
    assert (
        world.client.get("/auth/totp").json()["recovery_codes_left"] == 10 and login(world, totp_code=old[0]).status_code == 200
    )  # nothing changed yet (and that sign-in used one old code)
    world.clock["t"] += 30
    r = world.client.post("/auth/totp/recovery", json={"password": PASSWORD, "code": code_now(world, secret)})
    assert r.status_code == 200, r.text
    fresh = r.json()["recovery_codes"]
    assert len(fresh) == 10 and not set(fresh) & set(old)
    assert world.client.get("/auth/totp").json() == {"enabled": True, "recovery_codes_left": 10}
    assert login(world, totp_code=old[1]).status_code in (400, 401, 403, 428), "an old recovery code is dead once replaced"
    assert login(world, totp_code=fresh[0]).status_code == 200
    assert world.client.get("/auth/totp").json()["recovery_codes_left"] == 9


def test_new_recovery_codes_are_refused_when_the_app_is_not_on(world):
    assert world.client.post("/auth/totp/recovery", json={"password": PASSWORD, "code": "123456"}).status_code == 403

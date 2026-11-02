"""A person whose ONE role is a custom role can do exactly what that role grants: nothing from Viewer or any other built-in role is added, and nothing is left unenforced.

Real routers, a real (SQLite) database and real sign-in tokens."""

import asyncio
import uuid

import pytest
from app.api.v1 import deps
from app.api.v1.endpoints import auth, tenants
from app.core.security import get_password_hash
from app.db.database import Base
from app.models.login_failure import LoginFailure
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.responder import PasskeyCredential
from app.models.tenant import ApiKey, Tenant, User
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

PW = "correct horse battery staple"
TABLES = [m.__table__ for m in (Tenant, User, ApiKey, LoginFailure, Role, Permission, RolePermission, UserRole, PasskeyCredential)]


@pytest.fixture
def world(tmp_path):
    path = tmp_path / "custom.db"
    sync = create_engine(f"sqlite:///{path}")
    column = Role.__table__.c.hidden_nav  # a Postgres-only default; SQLite cannot create it
    saved, column.server_default = column.server_default, None
    try:
        Base.metadata.create_all(sync, tables=TABLES)
    finally:
        column.server_default = saved
    tenant = Tenant(id=uuid.uuid4(), name="T", slug="t-" + uuid.uuid4().hex[:6])
    with Session(sync, expire_on_commit=False) as s:
        s.add(tenant)
        s.commit()
    factory = async_sessionmaker(create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool), expire_on_commit=False)
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(tenants.router)

    async def session():
        async with factory() as s:
            yield s

    app.dependency_overrides[deps.get_db] = session
    yield type("World", (), {"client": TestClient(app), "factory": factory, "tenant": tenant})
    sync.dispose()


def run(world, fn):
    async def main():
        async with world.factory() as s:
            out = await fn(s)
            await s.commit()
            return out

    return asyncio.run(main())


def person(world, name, role, custom_perms=None):
    """A person; with custom_perms (a list) they hold role "custom" and ONE new custom role granting exactly those permissions."""

    async def go(s):
        u = User(id=uuid.uuid4(), tenant_id=world.tenant.id, account_name=name, email=f"{name}@example.com", username=name, hashed_password=get_password_hash(PW), role=role)
        s.add(u)
        if custom_perms is not None:
            r = Role(id=uuid.uuid4(), tenant_id=world.tenant.id, name=f"role-of-{name}", is_system=False)
            s.add(r)
            await s.flush()
            for p in custom_perms:
                perm = (await s.execute(select(Permission).where(Permission.name == p))).scalar_one_or_none()
                if perm is None:
                    perm = Permission(id=uuid.uuid4(), name=p, description=p, category=p.split(":")[0])
                    s.add(perm)
                    await s.flush()
                s.add(RolePermission(role_id=r.id, permission_id=perm.id))
            s.add(UserRole(user_id=u.id, role_id=r.id))
        await s.flush()
        return u.id

    return run(world, go)


def sign_in(world, name):
    r = world.client.post("/auth/login", json={"account_name": name, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_a_custom_role_grants_exactly_what_it_lists(world):
    person(world, "boss", "tenant_admin")
    person(world, "cara", "custom", ["users:read"])
    h = sign_in(world, "cara")
    assert world.client.get("/tenants/me/users", headers=h).status_code == 200  # users:read is in her role
    assert world.client.get("/tenants/me", headers=h).status_code == 403  # settings:read is not


def test_nothing_from_viewer_is_added_to_a_custom_role(world):
    person(world, "vic", "viewer")
    person(world, "cara", "custom", ["users:read"])
    # alerts:read is part of Viewer; the tenant picker needs it. Viewer gets in, the custom-role person (who was not given it) does not.
    assert world.client.get("/tenants/selectable", headers=sign_in(world, "vic")).status_code == 200
    assert world.client.get("/tenants/selectable", headers=sign_in(world, "cara")).status_code == 403


def test_a_custom_role_with_no_permissions_holds_nothing(world):
    person(world, "nora", "custom", [])
    h = sign_in(world, "nora")
    assert world.client.get("/tenants/me/users", headers=h).status_code == 403


def test_a_custom_person_whose_role_was_deleted_holds_nothing(world):
    uid = person(world, "orphan", "custom", ["users:read"])

    async def drop(s):
        await s.execute(UserRole.__table__.delete().where(UserRole.user_id == uid))

    run(world, drop)
    assert world.client.get("/tenants/me/users", headers=sign_in(world, "orphan")).status_code == 403


def test_what_the_console_shows_follows_the_custom_role(world):
    person(world, "mgr", "custom", ["users:read", "users:write"])
    person(world, "cara", "custom", ["users:read"])
    assert "manage_users" in world.client.get("/auth/me", headers=sign_in(world, "mgr")).json()["capabilities"]
    assert world.client.get("/auth/me", headers=sign_in(world, "cara")).json()["capabilities"] == []


def test_nobody_manages_a_custom_role_person_who_holds_more_than_they_do(world):
    person(world, "boss", "tenant_admin")
    person(world, "dave", "custom", ["users:read", "users:write"])
    power = person(world, "pam", "custom", ["users:read", "users:write", "alerts:write", "cases:write"])
    dave, boss = sign_in(world, "dave"), sign_in(world, "boss")
    assert world.client.patch(f"/tenants/me/users/{power}", json={"username": "P"}, headers=dave).status_code == 403
    assert world.client.post(f"/tenants/me/users/{power}/reset-mfa", headers=dave).status_code == 403
    assert world.client.delete(f"/tenants/me/users/{power}", headers=dave).status_code == 403
    assert world.client.patch(f"/tenants/me/users/{power}", json={"username": "P"}, headers=boss).status_code == 200  # the administrator holds all of it


def test_a_custom_role_person_cannot_hand_out_a_role_that_grants_more_than_their_own(world):
    person(world, "dave", "custom", ["users:read", "users:write"])
    h = sign_in(world, "dave")
    r = world.client.post("/tenants/me/users", json={"account_name": "newbie", "password": "a long enough passphrase", "role": "tenant_admin"}, headers=h)
    assert r.status_code == 403

"""Managing members: custom roles when adding and editing, deleting a person, removing their passkeys (reset MFA), and never locking out the last administrator.

Real routers and a real (SQLite) database, the fake Redis from conftest, real sign-in tokens."""

import asyncio
import uuid
from datetime import UTC, datetime

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


def make_user(tenant, name, role):
    return User(id=uuid.uuid4(), tenant_id=tenant.id, account_name=name, email=f"{name}@example.com", username=name, hashed_password=get_password_hash(PW), role=role)


@pytest.fixture
def world(tmp_path):
    path = tmp_path / "members.db"
    sync = create_engine(f"sqlite:///{path}")
    # roles.hidden_nav's default is Postgres-only SQL; SQLite cannot create it, so drop the default for this test database only.
    column = Role.__table__.c.hidden_nav
    saved, column.server_default = column.server_default, None
    try:
        Base.metadata.create_all(sync, tables=TABLES)
    finally:
        column.server_default = saved
    tenant = Tenant(id=uuid.uuid4(), name="T", slug="t-" + uuid.uuid4().hex[:6])
    other = Tenant(id=uuid.uuid4(), name="U", slug="u-" + uuid.uuid4().hex[:6])
    boss, second, ann, eve = make_user(tenant, "boss", "tenant_admin"), make_user(tenant, "second", "tenant_admin"), make_user(tenant, "ann", "soc_analyst"), make_user(other, "eve", "soc_analyst")
    perm = Permission(id=uuid.uuid4(), name="alerts:read", description="read alerts", category="alerts")
    mine = Role(id=uuid.uuid4(), tenant_id=tenant.id, name="Client reviewer", is_system=False)
    theirs = Role(id=uuid.uuid4(), tenant_id=other.id, name="Their role", is_system=False)
    with Session(sync, expire_on_commit=False) as s:
        s.add_all([tenant, other, boss, second, ann, eve, perm, mine, theirs])
        s.flush()
        s.add_all([RolePermission(role_id=mine.id, permission_id=perm.id), RolePermission(role_id=theirs.id, permission_id=perm.id)])
        s.add(PasskeyCredential(tenant_id=tenant.id, user_id=ann.id, credential_id="c1", public_key="k", device_name="Ann phone", created_at=datetime.now(UTC)))
        s.commit()
    factory = async_sessionmaker(create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool), expire_on_commit=False)
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(tenants.router)

    async def session():
        async with factory() as s:
            yield s

    app.dependency_overrides[deps.get_db] = session
    yield type("World", (), {"client": TestClient(app), "factory": factory, "boss": boss, "second": second, "ann": ann, "eve": eve, "mine": mine, "theirs": theirs, "tenant": tenant})
    sync.dispose()


def login(world, name):
    r = world.client.post("/auth/login", json={"account_name": name, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def run(world, coro_fn):
    async def main():
        async with world.factory() as s:
            return await coro_fn(s)

    return asyncio.run(main())


def new_member(world, h, **over):
    body = {"account_name": "newbie", "password": "a long enough passphrase", "role": "viewer", **over}
    return world.client.post("/tenants/me/users", json=body, headers=h)


class TestCustomRoles:
    def test_adding_a_member_with_a_custom_role_gives_them_it_and_the_list_shows_it(self, world):
        h = login(world, "boss")
        r = new_member(world, h, custom_role_ids=[str(world.mine.id)])
        assert r.status_code == 201, r.text
        assert [c["name"] for c in r.json()["custom_roles"]] == ["Client reviewer"]
        listed = {u["account_name"]: u for u in world.client.get("/tenants/me/users", headers=h).json()}
        assert [c["name"] for c in listed["newbie"]["custom_roles"]] == ["Client reviewer"]
        assert listed["ann"]["custom_roles"] == []

    def test_a_role_of_another_workspace_is_refused_and_nobody_is_created(self, world):
        h = login(world, "boss")
        r = new_member(world, h, custom_role_ids=[str(world.theirs.id)])
        assert r.status_code == 404
        assert all(u["account_name"] != "newbie" for u in world.client.get("/tenants/me/users", headers=h).json())

    def test_editing_replaces_the_set_of_custom_roles_and_leaves_them_alone_when_not_mentioned(self, world):
        h = login(world, "boss")
        r = world.client.patch(f"/tenants/me/users/{world.ann.id}", json={"custom_role_ids": [str(world.mine.id)]}, headers=h)
        assert r.status_code == 200 and [c["name"] for c in r.json()["custom_roles"]] == ["Client reviewer"]
        r = world.client.patch(f"/tenants/me/users/{world.ann.id}", json={"username": "Ann A."}, headers=h)
        assert r.json()["username"] == "Ann A." and len(r.json()["custom_roles"]) == 1
        r = world.client.patch(f"/tenants/me/users/{world.ann.id}", json={"custom_role_ids": []}, headers=h)
        assert r.json()["custom_roles"] == []


class TestDisablingAndRoles:
    def test_nobody_disables_their_own_account(self, world):
        h = login(world, "boss")
        r = world.client.patch(f"/tenants/me/users/{world.boss.id}", json={"is_active": False}, headers=h)
        assert r.status_code == 403

    def test_an_administrator_can_be_disabled_while_another_remains_but_not_the_last(self, world):
        h = login(world, "boss")
        assert world.client.patch(f"/tenants/me/users/{world.second.id}", json={"is_active": False}, headers=h).status_code == 200
        # `second` is now disabled, so `boss` is the only active administrator: another admin cannot be created to disable boss here, and the helper refuses on its own.

        async def body(s):
            boss = await s.get(User, world.boss.id)
            with pytest.raises(Exception) as e:
                await tenants._refuse_if_last_admin(s, world.tenant.id, boss, "Disabling this account")
            return getattr(e.value, "status_code", None)

        assert run(world, body) == 409

    def test_demoting_the_only_active_administrator_is_refused(self, world):
        async def body(s):
            second = await s.get(User, world.second.id)
            second.is_active = False
            await s.commit()

        run(world, body)
        # boss cannot change their own role (403 first); the rule that protects the last admin also covers someone else demoting them:
        async def check(s):
            boss = await s.get(User, world.boss.id)
            with pytest.raises(Exception) as e:
                await tenants._refuse_if_last_admin(s, world.tenant.id, boss, "Changing this role")
            return e.value.status_code

        assert run(world, check) == 409


class TestDeleting:
    def test_deleting_a_person_removes_them_their_roles_and_passkeys_and_they_can_no_longer_sign_in(self, world):
        h = login(world, "boss")
        world.client.patch(f"/tenants/me/users/{world.ann.id}", json={"custom_role_ids": [str(world.mine.id)]}, headers=h)
        r = world.client.delete(f"/tenants/me/users/{world.ann.id}", headers=h)
        assert r.status_code == 200 and "ann" in r.json()["detail"]
        assert all(u["account_name"] != "ann" for u in world.client.get("/tenants/me/users", headers=h).json())

        async def left(s):
            roles = (await s.execute(select(UserRole).where(UserRole.user_id == world.ann.id))).all()
            keys = (await s.execute(select(PasskeyCredential).where(PasskeyCredential.user_id == world.ann.id))).all()
            return len(roles), len(keys)

        assert run(world, left) == (0, 0)
        assert world.client.post("/auth/login", json={"account_name": "ann", "password": PW}).status_code in (400, 401)

    def test_nobody_deletes_themselves_or_a_person_of_another_workspace(self, world):
        h = login(world, "boss")
        assert world.client.delete(f"/tenants/me/users/{world.boss.id}", headers=h).status_code == 403
        assert world.client.delete(f"/tenants/me/users/{world.eve.id}", headers=h).status_code == 404

    def test_an_analyst_cannot_delete_anyone(self, world):
        h = login(world, "ann")
        assert world.client.delete(f"/tenants/me/users/{world.second.id}", headers=h).status_code == 403


class TestResetMfa:
    def test_it_removes_every_passkey_and_ends_their_sessions(self, world):
        analyst_h = login(world, "ann")
        assert world.client.get("/auth/me", headers=analyst_h).status_code == 200
        h = login(world, "boss")
        r = world.client.post(f"/tenants/me/users/{world.ann.id}/reset-mfa", headers=h)
        assert r.status_code == 200 and "1 passkey" in r.json()["detail"]

        async def live(s):
            return len((await s.execute(select(PasskeyCredential).where(PasskeyCredential.user_id == world.ann.id, PasskeyCredential.revoked_at.is_(None)))).all())

        assert run(world, live) == 0
        assert world.client.get("/auth/me", headers=analyst_h).status_code == 401  # their old session no longer works

    def test_only_a_manager_of_the_same_workspace_may_do_it(self, world):
        h = login(world, "boss")
        assert world.client.post(f"/tenants/me/users/{world.eve.id}/reset-mfa", headers=h).status_code == 404
        assert world.client.post(f"/tenants/me/users/{world.second.id}/reset-mfa", headers=login(world, "ann")).status_code == 403

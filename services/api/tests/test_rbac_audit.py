"""Every change to a custom role, and to who holds one, leaves an audit entry naming what changed (permission names, never a secret). Real router, a real (SQLite) database and real sign-in tokens;
only the audit writer is replaced by a recorder (the audit table is Postgres-side)."""

import uuid
from unittest.mock import AsyncMock

import pytest
from app.api.v1 import deps
from app.api.v1.endpoints import auth, rbac
from app.core.security import get_password_hash
from app.db.database import Base
from app.db.rls import get_tenant_db
from app.models.login_failure import LoginFailure
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.responder import PasskeyCredential
from app.models.tenant import ApiKey, Tenant, User
from app.models.user_totp import UserTotp
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

PW = "correct horse battery staple"
TABLES = [m.__table__ for m in (Tenant, User, ApiKey, LoginFailure, UserTotp, Role, Permission, RolePermission, UserRole, PasskeyCredential)]


@pytest.fixture
def world(tmp_path, monkeypatch):
    path = tmp_path / "rbac.db"
    sync = create_engine(f"sqlite:///{path}")
    column = Role.__table__.c.hidden_nav  # a Postgres-only default; SQLite cannot create it
    saved, column.server_default = column.server_default, None
    try:
        Base.metadata.create_all(sync, tables=TABLES)
    finally:
        column.server_default = saved
    tenant = Tenant(id=uuid.uuid4(), name="T", slug="t-" + uuid.uuid4().hex[:6])
    perms = {n: Permission(id=uuid.uuid4(), name=n, description=n, category=n.split(":")[0]) for n in ("alerts:read", "cases:read", "users:read")}
    boss = User(id=uuid.uuid4(), tenant_id=tenant.id, account_name="boss", email="boss@example.com", username="boss", hashed_password=get_password_hash(PW), role="tenant_admin")
    ann = User(id=uuid.uuid4(), tenant_id=tenant.id, account_name="ann", email="ann@example.com", username="ann", hashed_password=get_password_hash(PW), role="custom")
    with Session(sync, expire_on_commit=False) as s:
        s.add(tenant)
        s.flush()
        s.add_all([*perms.values(), boss, ann])
        s.commit()
    audit = AsyncMock()
    monkeypatch.setattr(rbac, "emit_audit", audit)
    factory = async_sessionmaker(create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool), expire_on_commit=False)
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(rbac.router)

    async def session():
        async with factory() as s:
            yield s

    app.dependency_overrides[deps.get_db] = session
    app.dependency_overrides[get_tenant_db] = session
    yield type("World", (), {"client": TestClient(app), "audit": audit, "perms": perms, "ann": ann})
    sync.dispose()


def headers(world):
    r = world.client.post("/auth/login", json={"account_name": "boss", "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def entries(world, action):
    return [c.kwargs for c in world.audit.await_args_list if c.kwargs.get("action") == action]


def test_creating_changing_assigning_revoking_and_deleting_a_role_each_leave_an_entry_with_permission_names(world):
    h = headers(world)
    ids = {n: str(p.id) for n, p in world.perms.items()}
    made = world.client.post("/rbac/roles", json={"name": "Reader", "permission_ids": [ids["alerts:read"], ids["cases:read"]]}, headers=h)
    assert made.status_code == 201, made.text
    role_id = made.json()["id"]
    created = entries(world, "role:created")
    assert len(created) == 1 and created[0]["changes"] == {"name": "Reader", "permissions": ["alerts:read", "cases:read"]}
    assert created[0]["resource_id"] == role_id and created[0]["actor_email"] == "boss@example.com"

    changed = world.client.patch(f"/rbac/roles/{role_id}", json={"name": "Reader+", "permission_ids": [ids["alerts:read"], ids["users:read"]]}, headers=h)
    assert changed.status_code == 200, changed.text
    updated = entries(world, "role:updated")
    assert len(updated) == 1
    assert updated[0]["changes"] == {"name": {"before": "Reader", "after": "Reader+"}, "permissions_added": ["users:read"], "permissions_removed": ["cases:read"]}

    assigned = world.client.post(f"/rbac/users/{world.ann.id}/roles", json={"user_id": str(world.ann.id), "role_id": role_id}, headers=h)
    assert assigned.status_code == 201, assigned.text
    assert entries(world, "role:assigned")[0]["changes"] == {"user_id": str(world.ann.id), "role_name": "Reader+"}

    assert world.client.delete(f"/rbac/users/{world.ann.id}/roles/{role_id}", headers=h).status_code == 204
    assert entries(world, "role:revoked")[0]["changes"] == {"user_id": str(world.ann.id), "role_name": "Reader+"}

    assert world.client.delete(f"/rbac/roles/{role_id}", headers=h).status_code == 204
    assert entries(world, "role:deleted")[0]["changes"] == {"name": "Reader+", "permissions": ["alerts:read", "users:read"]}


def test_a_rename_alone_records_no_permission_change_and_a_refused_change_records_nothing(world):
    h = headers(world)
    ids = {n: str(p.id) for n, p in world.perms.items()}
    role_id = world.client.post("/rbac/roles", json={"name": "A", "permission_ids": [ids["alerts:read"]]}, headers=h).json()["id"]
    world.audit.reset_mock()
    assert world.client.patch(f"/rbac/roles/{role_id}", json={"name": "B"}, headers=h).status_code == 200
    assert entries(world, "role:updated")[0]["changes"] == {"name": {"before": "A", "after": "B"}, "permissions_added": [], "permissions_removed": []}
    world.audit.reset_mock()
    assert world.client.patch(f"/rbac/roles/{uuid.uuid4()}", json={"name": "C"}, headers=h).status_code == 404
    assert world.client.delete(f"/rbac/roles/{uuid.uuid4()}", headers=h).status_code == 404
    assert world.audit.await_count == 0


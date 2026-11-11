"""The role a new Microsoft sign-in gets: chosen under Roles & Permissions, applied when the person is created, never an administrator."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.api.v1.endpoints import rbac, sso_microsoft
from app.db.database import Base
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.tenant import Tenant, User
from app.services import sso_default_role as sdr
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TABLES = [m.__table__ for m in (Tenant, User, Role, Permission, RolePermission, UserRole)]


def run(coro_fn):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        column = Role.__table__.c.hidden_nav  # a Postgres-only default; SQLite cannot create it
        saved, column.server_default = column.server_default, None
        try:
            async with engine.begin() as c:
                await c.run_sync(lambda conn: Base.metadata.create_all(conn, tables=TABLES))
        finally:
            column.server_default = saved
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            try:
                return await coro_fn(s)
            finally:
                await engine.dispose()

    return asyncio.run(main())


def sso_env(home):
    return {
        "MS_SSO_TENANT_ID": "tid",
        "MS_SSO_CLIENT_ID": "cid",
        "MS_SSO_CLIENT_SECRET": "secret",
        "MS_SSO_REDIRECT_URI": "https://acorn.example/api/v1/auth/sso/microsoft/callback",
        "MS_SSO_ACORN_TENANT_ID": str(home),
    }


class TestEffective:
    def test_nothing_stored_means_the_server_setting(self):
        assert sdr.effective(None, "viewer") == ("viewer", None, "server")
        assert sdr.effective({}, "soc_analyst") == ("soc_analyst", None, "server")

    def test_a_stored_choice_wins_and_may_carry_a_custom_role(self):
        cid = uuid.uuid4()
        assert sdr.effective({sdr.KEY: sdr.stored("soc_analyst", None)}, "viewer") == ("soc_analyst", None, "setting")
        assert sdr.effective({sdr.KEY: sdr.stored("custom", cid)}, "viewer") == ("custom", cid, "setting")
        # an older saved value of Viewer plus a custom role means the same thing: the custom role alone
        assert sdr.effective({sdr.KEY: sdr.stored("viewer", cid)}, "viewer") == ("custom", cid, "setting")

    @pytest.mark.parametrize(
        "bad",
        [
            {"role": "tenant_admin"},
            {"role": "platform_admin"},
            {"role": "nonsense"},
            {"role": "viewer", "custom_role_id": "not-a-uuid"},
            "text",
            5,
        ],
    )
    def test_an_unusable_stored_value_falls_back_to_the_server_setting(self, bad):
        assert sdr.effective({sdr.KEY: bad}, "viewer")[2] == "server"


class TestTheNewPersonIsCreatedWithIt:
    def make(self, s, settings=None, custom=True):
        async def go():
            home = Tenant(id=uuid.uuid4(), name="Home", slug="home-" + uuid.uuid4().hex[:6], settings=settings or {})
            s.add(home)
            role = Role(id=uuid.uuid4(), tenant_id=home.id, name="Client reviewer", is_system=False)
            if custom:
                s.add(role)
            await s.commit()
            return home, role

        return go()

    def claims(self, n="new"):
        return {"tid": "tid", "oid": f"oid-{n}", "preferred_username": f"{n}@client.example", "name": n.title()}

    def test_a_custom_role_choice_makes_it_the_persons_one_role(self):
        async def body(s):
            home, role = await self.make(s)
            home.settings = {sdr.KEY: sdr.stored("custom", role.id)}
            await s.commit()
            cfg = sso_microsoft.load_config(sso_env(home.id))
            user, outcome = await sso_microsoft.resolve_user(s, cfg, self.claims())
            await s.commit()
            held = (await s.execute(select(UserRole.role_id).where(UserRole.user_id == user.id))).scalars().all()
            return outcome, user.role, held, role.id

        outcome, base, held, rid = run(body)
        assert (outcome, base, held) == ("created", "custom", [rid])

    def test_a_built_in_choice_is_used_and_no_custom_role_is_given(self):
        async def body(s):
            home, _ = await self.make(s, {sdr.KEY: sdr.stored("soc_lead", None)})
            user, _o = await sso_microsoft.resolve_user(s, sso_microsoft.load_config(sso_env(home.id)), self.claims())
            return user.role, (await s.execute(select(UserRole))).all()

        assert run(body) == ("soc_lead", [])

    def test_with_no_choice_the_server_setting_still_applies(self):
        async def body(s):
            home, _ = await self.make(s)
            env = {**sso_env(home.id), "MS_SSO_NEW_USER_ROLE": "soc_analyst"}
            user, _o = await sso_microsoft.resolve_user(s, sso_microsoft.load_config(env), self.claims())
            return user.role

        assert run(body) == "soc_analyst"

    def test_a_stored_administrator_role_is_never_used(self):
        async def body(s):
            home, _ = await self.make(s, {sdr.KEY: {"role": "tenant_admin", "custom_role_id": None}})
            user, _o = await sso_microsoft.resolve_user(s, sso_microsoft.load_config(sso_env(home.id)), self.claims())
            return user.role

        assert run(body) == "viewer"

    def test_a_custom_role_that_was_deleted_is_simply_not_given(self):
        async def body(s):
            home, _ = await self.make(s, custom=False)
            home.settings = {sdr.KEY: sdr.stored("custom", uuid.uuid4())}
            await s.commit()
            user, _o = await sso_microsoft.resolve_user(s, sso_microsoft.load_config(sso_env(home.id)), self.claims())
            return user.role, (await s.execute(select(UserRole))).all()

        assert run(body) == ("custom", [])


class TestChoosingIt:
    def caller(self, tenant_id, can_grant=lambda role: True, holds=lambda name: True):
        return SimpleNamespace(
            tenant_id=tenant_id,
            user_id=uuid.uuid4(),
            email="boss@example.test",
            can_grant_role=can_grant,
            holds=holds,
            holds_wildcard=lambda: True,
        )

    def put(self, s, home, body, caller=None, env=None, monkeypatch=None):
        for k, v in (env if env is not None else sso_env(home.id)).items():
            monkeypatch.setenv(k, v)
        return rbac.set_sso_default(body, current_user=caller or self.caller(home.id), db=s)

    def world(self, s):
        async def go():
            home = Tenant(id=uuid.uuid4(), name="Home", slug="home-" + uuid.uuid4().hex[:6], settings={"other": 1})
            role = Role(id=uuid.uuid4(), tenant_id=home.id, name="Client reviewer", is_system=False)
            s.add_all([home, role])
            await s.commit()
            return home, role

        return go()

    def test_a_built_in_role_is_saved_next_to_the_other_settings_and_audited(self, monkeypatch):
        audit = AsyncMock()
        monkeypatch.setattr(rbac, "emit_audit", audit)

        async def body(s):
            home, _ = await self.world(s)
            out = await self.put(s, home, rbac.SsoDefaultIn(role="soc_analyst"), monkeypatch=monkeypatch)
            await s.refresh(home)
            return out, home.settings

        out, settings = run(body)
        assert (
            (out.role, out.source) == ("soc_analyst", "setting") and settings["other"] == 1 and settings[sdr.KEY]["role"] == "soc_analyst"
        )
        assert audit.await_args.kwargs["action"] == "sso:default_role_changed"
        assert (
            audit.await_args.kwargs["changes"]["after"]["role"] == "soc_analyst"
            and audit.await_args.kwargs["changes"]["before"]["role"] == "viewer"
        )

    def test_a_custom_role_is_saved_as_the_one_role(self, monkeypatch):
        monkeypatch.setattr(rbac, "emit_audit", AsyncMock())

        async def body(s):
            home, role = await self.world(s)
            out = await self.put(s, home, rbac.SsoDefaultIn(role="soc_lead", custom_role_id=role.id), monkeypatch=monkeypatch)
            return out, role.id

        out, rid = run(body)
        assert (out.role, out.custom_role_id) == ("custom", rid)

    @pytest.mark.parametrize("role", ["tenant_admin", "platform_admin", "admin", "nonsense"])
    def test_an_administrator_or_unknown_role_is_refused(self, role, monkeypatch):
        async def body(s):
            home, _ = await self.world(s)
            with pytest.raises(HTTPException) as e:
                await self.put(s, home, rbac.SsoDefaultIn(role=role), monkeypatch=monkeypatch)
            return e.value.status_code

        assert run(body) == 422

    def test_you_cannot_choose_more_than_you_hold(self, monkeypatch):
        monkeypatch.setattr(rbac, "emit_audit", AsyncMock())

        async def body(s):
            home, role = await self.world(s)
            perm = Permission(id=uuid.uuid4(), name="users:write", description="x", category="users")
            s.add(perm)
            await s.flush()
            s.add(RolePermission(role_id=role.id, permission_id=perm.id))
            await s.commit()
            with pytest.raises(HTTPException) as built_in:  # a built-in role above the caller's own
                await self.put(
                    s,
                    home,
                    rbac.SsoDefaultIn(role="soc_lead"),
                    caller=self.caller(home.id, can_grant=lambda r: False),
                    monkeypatch=monkeypatch,
                )
            with pytest.raises(HTTPException) as custom:  # a custom role holding a permission the caller does not have
                await self.put(
                    s,
                    home,
                    rbac.SsoDefaultIn(role="viewer", custom_role_id=role.id),
                    caller=self.caller(home.id, holds=lambda n: False),
                    monkeypatch=monkeypatch,
                )
            return built_in.value.status_code, custom.value.status_code

        assert run(body) == (403, 403)

    def test_a_role_of_another_workspace_and_a_missing_setup_are_refused(self, monkeypatch):
        async def body(s):
            home, _ = await self.world(s)
            other = Tenant(id=uuid.uuid4(), name="Other", slug="o-" + uuid.uuid4().hex[:6])
            theirs = Role(id=uuid.uuid4(), tenant_id=other.id, name="Theirs", is_system=False)
            s.add_all([other, theirs])
            await s.commit()
            with pytest.raises(HTTPException) as e1:
                await self.put(s, home, rbac.SsoDefaultIn(role="viewer", custom_role_id=theirs.id), monkeypatch=monkeypatch)
            with pytest.raises(HTTPException) as e2:  # SSO creates people in a different workspace
                await self.put(s, home, rbac.SsoDefaultIn(role="viewer"), env=sso_env(other.id), monkeypatch=monkeypatch)
            for k in sso_env(home.id):
                monkeypatch.delenv(k, raising=False)
            with pytest.raises(HTTPException) as e3:  # SSO not set up at all
                await rbac.set_sso_default(rbac.SsoDefaultIn(role="viewer"), current_user=self.caller(home.id), db=s)
            return e1.value.status_code, e2.value.status_code, e3.value.status_code

        assert run(body) == (404, 409, 409)

    def test_reading_it_reports_whether_it_applies_to_this_workspace(self, monkeypatch):
        async def body(s):
            home, _ = await self.world(s)
            for k, v in sso_env(home.id).items():
                monkeypatch.setenv(k, v)
            mine = await rbac.get_sso_default(current_user=self.caller(home.id), db=s)
            elsewhere = await rbac.get_sso_default(current_user=self.caller(uuid.uuid4()), db=s)
            return mine, elsewhere

        mine, elsewhere = run(body)
        assert (mine.sso_configured, mine.applies_here, mine.role, mine.source) == (True, True, "viewer", "server")
        assert elsewhere.applies_here is False

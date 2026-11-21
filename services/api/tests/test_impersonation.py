"""Impersonation: an administrator signs in as another person and sees the console as they do.

The token names the real administrator (``imp``); the session it makes cannot impersonate again, cannot change the person's own password or passkeys, and the target must not hold more power than the caller.
"""

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.v1.deps import CurrentUser, _authenticate, require_signed_in_session
from app.api.v1.endpoints.auth import impersonate, may_impersonate_perms
from app.core.security import ROLE_PERMISSIONS, create_access_token, has_permission, capabilities_for_role

TENANT = uuid.uuid4()


def _admin(role: str = "tenant_admin") -> CurrentUser:
    return CurrentUser(user_id=uuid.uuid4(), tenant_id=TENANT, role=role, email="boss@example.com")


def test_tenant_admins_hold_the_permission_and_analysts_do_not():
    assert has_permission("tenant_admin", "users:impersonate")
    assert not has_permission("soc_lead", "users:impersonate")
    assert "impersonate" in capabilities_for_role("tenant_admin")
    assert "impersonate" not in capabilities_for_role("soc_lead")


def test_nobody_impersonates_more_power_than_they_hold():
    tenant_admin = _admin("tenant_admin")
    assert may_impersonate_perms(tenant_admin, ROLE_PERMISSIONS["soc_lead"])
    assert not may_impersonate_perms(tenant_admin, ["*"])  # the wildcard of a platform admin
    assert not may_impersonate_perms(tenant_admin, ["plugins:admin"])
    platform = _admin("platform_admin")
    assert may_impersonate_perms(platform, ["*", "plugins:admin"])


def _db_returning(user):
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


def _target(role: str = "soc_lead", tenant=TENANT):
    return MagicMock(id=uuid.uuid4(), tenant_id=tenant, role=role, email="analyst@example.com", account_name="analyst", is_active=True)


@pytest.mark.asyncio
async def test_impersonation_token_names_the_administrator_and_cannot_impersonate_again():
    admin = _admin()
    target = _target()
    with patch("app.api.v1.endpoints.auth.custom_role_grants", AsyncMock(return_value=None)), patch("app.api.v1.endpoints.auth.emit_audit", AsyncMock()) as audit:
        out = await impersonate(target.id, admin, _db_returning(target), None)
    assert out.user_id == str(target.id) and out.expires_in_minutes == 60
    assert audit.await_args.kwargs["action"] == "auth:impersonation_started"
    assert audit.await_args.kwargs["actor_id"] == admin.user_id

    # The token resolves to the TARGET, with the real administrator recorded.
    with patch("app.api.v1.deps.is_revoked", AsyncMock(return_value=False)), patch("app.api.v1.deps.signed_out_everywhere", AsyncMock(return_value=False)), patch(
        "app.api.v1.deps.custom_role_grants", AsyncMock(return_value=None)
    ):
        user = await _authenticate(HTTPAuthorizationCredentials(scheme="Bearer", credentials=out.access_token), _db_returning(target))
    assert user.user_id == target.id and user.role == "soc_lead"
    assert user.impersonator_id == admin.user_id and user.impersonator_email == "boss@example.com"

    # An impersonated session never holds the permission, even if the target's role did, and cannot touch the person's own sign-in settings.
    with_perm = CurrentUser(user_id=target.id, tenant_id=TENANT, role="tenant_admin", email="x", impersonator_id=admin.user_id)
    assert not with_perm.holds("users:impersonate")
    with pytest.raises(HTTPException) as e:
        await require_signed_in_session(with_perm)
    assert e.value.status_code == 403
    assert await require_signed_in_session(_admin()) is not None


@pytest.mark.asyncio
async def test_refuses_yourself_other_tenants_unknown_people_and_stronger_people():
    admin = _admin()
    with patch("app.api.v1.endpoints.auth.custom_role_grants", AsyncMock(return_value=None)), patch("app.api.v1.endpoints.auth.emit_audit", AsyncMock()) as audit:
        with pytest.raises(HTTPException) as e:
            await impersonate(admin.user_id, admin, _db_returning(None), None)
        assert e.value.status_code == 400
        with pytest.raises(HTTPException) as e:
            await impersonate(uuid.uuid4(), admin, _db_returning(None), None)  # not found in this organization
        assert e.value.status_code == 404
        with pytest.raises(HTTPException) as e:
            stronger = _target("platform_admin")
            await impersonate(stronger.id, admin, _db_returning(stronger), None)
        assert e.value.status_code == 403
        with pytest.raises(HTTPException) as e:
            await impersonate(uuid.uuid4(), CurrentUser(user_id=uuid.uuid4(), tenant_id=TENANT, role="tenant_admin", email="b", impersonator_id=uuid.uuid4()), _db_returning(_target()), None)
        assert e.value.status_code == 403
        with pytest.raises(HTTPException) as e:
            await impersonate(uuid.uuid4(), CurrentUser(user_id=uuid.uuid4(), tenant_id=TENANT, role="tenant_admin", email="b", scopes=["*"]), _db_returning(_target()), None)
        assert e.value.status_code == 403
        audit.assert_not_awaited()


def test_a_token_with_a_broken_imp_claim_is_refused():
    token = create_access_token({"sub": str(uuid.uuid4()), "tenant_id": str(TENANT), "imp": {"id": "not-a-uuid"}}, expires_delta=timedelta(minutes=5))
    import asyncio

    async def run():
        with patch("app.api.v1.deps.is_revoked", AsyncMock(return_value=False)), patch("app.api.v1.deps.signed_out_everywhere", AsyncMock(return_value=False)), patch(
            "app.api.v1.deps.custom_role_grants", AsyncMock(return_value=None)
        ):
            await _authenticate(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), _db_returning(_target()))

    with pytest.raises(HTTPException) as e:
        asyncio.run(run())
    assert e.value.status_code == 401

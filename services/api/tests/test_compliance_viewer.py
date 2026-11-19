"""The read-only compliance sign-in for a client's people: it reads the Compliance routes, writes nothing, reaches nothing else, and needs an authenticator app."""

import uuid
from types import SimpleNamespace

import pytest
from app.api.v1 import deps
from app.core.security import ROLE_PERMISSIONS, has_permission
from app.main import app
from app.services import client_portal as cp
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from route_introspect import walk_routes

ALL_ROUTES = list(walk_routes(app.routes))
ALL_METHOD_PATHS = sorted({(m, p) for p, r in ALL_ROUTES for m in r.methods if m not in {"HEAD", "OPTIONS"}})


def fake_request(method, path, headers=None):
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path), headers=headers or {}, cookies={}, state=SimpleNamespace())


def test_the_role_holds_only_report_reading_and_no_staff_role_gains_anything_from_it():
    assert ROLE_PERMISSIONS["compliance_viewer"] == ["reports:read"]
    assert not has_permission("compliance_viewer", "reports:write")
    assert not has_permission("compliance_viewer", "alerts:read")


@pytest.mark.parametrize("method,path", ALL_METHOD_PATHS)
def test_only_a_get_on_the_compliance_routes_and_the_sign_in_routes_are_open_to_the_role(method, path):
    rel = cp.relative_path(path)
    full = "/api/v1" + rel if not path.startswith("/api/") else path
    reads = method == "GET" and any(rel == p.rstrip("/") or rel.startswith(p if p.endswith("/") else p + "/") for p in cp.COMPLIANCE_READ_PREFIXES)
    open_ = reads or (method, rel) in (cp.ALLOWED_PATHS - {("GET", "/client-portal/summary")})
    if open_:
        cp.enforce_reach("compliance_viewer", fake_request(method, full))
    else:
        with pytest.raises(HTTPException) as e:
            cp.enforce_reach("compliance_viewer", fake_request(method, full))
        assert e.value.status_code == 403
    cp.enforce_reach("tenant_admin", fake_request(method, full))


def test_it_never_writes_to_compliance_and_cannot_view_another_tenant_or_use_the_dashboard_or_audit_routes():
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(HTTPException):
            cp.enforce_reach("compliance_viewer", fake_request(method, "/api/v1/compliance/audits"))
    with pytest.raises(HTTPException):
        cp.enforce_reach("compliance_viewer", fake_request("GET", "/api/v1/compliance/audits", {"x-view-as-tenant": str(uuid.uuid4())}))
    for path in ("/api/v1/client-portal/summary", "/api/v1/audit-portal/audits", "/api/v1/alerts", "/api/v1/reports/ticket-metrics", "/api/v1/auth/totp/disable"):
        with pytest.raises(HTTPException):
            cp.enforce_reach("compliance_viewer", fake_request("GET", path))
    with pytest.raises(HTTPException):
        cp.enforce_reach("compliance_viewer", fake_request("GET", "/api/v1/compliancex/audits"))


def test_the_dashboard_and_audit_roles_cannot_read_compliance_with_their_own_reach():
    for role in ("client_viewer", "auditor"):
        with pytest.raises(HTTPException):
            cp.enforce_reach(role, fake_request("GET", "/api/v1/compliance/audits"))


async def test_without_an_authenticator_app_a_compliance_page_is_refused_but_setting_one_up_is_not(monkeypatch):
    user = deps.CurrentUser(uuid.uuid4(), uuid.uuid4(), "compliance_viewer", "c@x")

    async def fake_authenticate(credentials, db):
        return user

    async def no_tag(db, tenant):
        return None

    async def not_enabled(db, user_id, tenant_id):
        return False

    monkeypatch.setattr(deps, "_authenticate", fake_authenticate)
    monkeypatch.setattr(deps, "tag_session", no_tag)
    from app.services import totp_store

    monkeypatch.setattr(totp_store, "is_enabled", not_enabled)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="x")
    with pytest.raises(HTTPException) as e:
        await deps.get_current_user(creds, db=None, request=fake_request("GET", "/api/v1/compliance/audits"))
    assert e.value.status_code == 403 and "mfa_setup_required" in str(e.value.detail)
    got = await deps.get_current_user(creds, db=None, request=fake_request("POST", "/api/v1/auth/totp/enrol"))
    assert got is user

    async def enabled(db, user_id, tenant_id):
        return True

    monkeypatch.setattr(totp_store, "is_enabled", enabled)
    assert await deps.get_current_user(creds, db=None, request=fake_request("GET", "/api/v1/compliance/audits")) is user

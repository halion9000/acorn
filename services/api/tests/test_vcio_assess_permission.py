"""The Client Risk Score assessments need their own permission, so the vCIO role can run them without holding mssp:manage (the whole MSSP console)."""

from app.core.security import IMPLIED_BY, ROLE_PERMISSIONS, permission_in
from app.main import app
from route_introspect import required_permissions, walk_routes


def _routes():
    for path, route in walk_routes(app.routes):
        if path.startswith("/api/v1/vcio-risk-scoring"):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                yield method, path, set(required_permissions(route))


def test_every_route_that_writes_an_assessment_needs_vcio_assess_and_nothing_wider():
    writes = [(m, p, perms) for m, p, perms in _routes() if m in ("POST", "PUT", "PATCH", "DELETE") and "/settings" not in p]
    assert writes, "no write route found"
    for method, path, perms in writes:
        assert perms == {"vcio:assess"}, (method, path, perms)


def test_a_role_with_only_vcio_assess_can_run_assessments_and_nothing_else_of_the_console():
    granted = ["vcio:assess", "alerts:read"]
    assert permission_in(granted, "vcio:assess")
    for wider in ("mssp:manage", "mssp:read", "inventory:write", "settings:write"):
        assert not permission_in(granted, wider), wider


def test_mssp_manage_still_covers_it_so_nobody_who_could_before_loses_it():
    assert IMPLIED_BY["vcio:assess"] == ("mssp:manage",)
    assert permission_in(["mssp:manage"], "vcio:assess")
    for role in ("admin", "tenant_admin", "platform_admin"):
        assert permission_in(ROLE_PERMISSIONS[role], "vcio:assess"), role


def test_the_scoring_settings_still_need_the_settings_permissions():
    perms = {(m, p): perms for m, p, perms in _routes()}
    assert perms[("PUT", "/api/v1/vcio-risk-scoring/settings")] == {"settings:write"}

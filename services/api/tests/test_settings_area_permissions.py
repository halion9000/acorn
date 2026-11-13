"""Settings is split into areas, each with a View and a Manage permission, so a person can be given some of Settings and not all of it (Hal, 2026-11-13).

Before this, the routes behind eight areas of Settings shared one blanket pair, settings:read and settings:write: Retention, the HaloPSA ticket status, the AI key, standing approvals and the rest
could only be given together. Roles, People, Audit and Connectors already had permissions of their own (roles:*, users:*, audit_log:read, connectors:*) and keep them.

The rule, which these tests pin: settings:read implies every area's View and settings:write implies every area's Manage, so nobody who holds the blanket pair loses anything; Manage implies View of
its own area; nothing else implies either, so a role given one area holds no other.
"""

import re

import pytest
from app.core.security import IMPLIED_BY, ROLE_PERMISSIONS, known_permissions, permission_in
from app.main import app
from route_introspect import required_permissions, walk_routes

AREAS = ("workspace", "deployment", "clients", "automation", "tickets", "data", "reports", "security")

# (method, path under /api/v1) -> the area it belongs to; the read routes need View, the writes Manage.
ROUTES: dict[str, list[tuple[str, str]]] = {
    "workspace": [("GET", "/tenants/me"), ("PATCH", "/tenants/me/name"), ("PATCH", "/tenants/me/settings")],
    "deployment": [
        ("GET", "/airgap/status"),
        ("GET", "/deployment/airgap/status"),
        ("POST", "/deployment/airgap/bundle"),
        ("GET", "/deployment/config"),
        ("PUT", "/deployment/config"),
        ("GET", "/llm/credentials"),
        ("PUT", "/llm/credentials"),
        ("DELETE", "/llm/credentials"),
        ("GET", "/llm/status"),
        ("GET", "/fusion/metrics"),
    ],
    "clients": [
        ("GET", "/client-status-links"),
        ("POST", "/client-status-links"),
        ("DELETE", "/client-status-links/{link_id}"),
        ("GET", "/client-status-links/{link_id}/preview"),
        ("POST", "/client-status-links/{link_id}/review"),
        ("POST", "/client-status-links/{link_id}/revoke"),
        ("GET", "/vcio-risk-scoring/settings"),
        ("PUT", "/vcio-risk-scoring/settings"),
    ],
    "automation": [
        ("GET", "/approvals/agreement"),
        ("GET", "/standing-approvals"),
        ("POST", "/standing-approvals"),
        ("POST", "/standing-approvals/many"),
        ("POST", "/standing-approvals/{standing_id}/revoke"),
        ("GET", "/tenant-settings/auto-close"),
        ("PUT", "/tenant-settings/auto-close"),
        ("DELETE", "/tenant-settings/auto-close"),
    ],
    "tickets": [("GET", "/tenant-settings/tickets"), ("PUT", "/tenant-settings/tickets"), ("DELETE", "/tenant-settings/tickets")],
    "data": [
        ("GET", "/data-lifecycle/parsers"),
        ("POST", "/data-lifecycle/parsers"),
        ("POST", "/data-lifecycle/parsers/test"),
        ("DELETE", "/data-lifecycle/parsers/{parser_id}"),
        ("GET", "/data-lifecycle/retention"),
        ("PUT", "/data-lifecycle/retention"),
    ],
    "reports": [("POST", "/report-builder/render"), ("POST", "/report-builder/validate")],
    "security": [
        ("POST", "/easm/scan"),
        ("DELETE", "/kb/documents/{doc_id}"),
        ("POST", "/kb/ingest"),
        ("POST", "/posture/destinations/preview"),
        ("POST", "/posture/scan"),
        ("POST", "/purple-team/atomics/run"),
        ("POST", "/purple-team/atomics/sync"),
        ("POST", "/purple-team/caldera/run"),
    ],
}
# A few "POST" routes only compute something and change nothing; they keep the View permission, as they needed settings:read before.
READ_ONLY_POSTS = {"/data-lifecycle/parsers/test", "/report-builder/render", "/report-builder/validate", "/posture/destinations/preview"}


def _wanted(area: str, method: str, path: str) -> str:
    return f"settings_{area}:view" if method == "GET" or path in READ_ONLY_POSTS else f"settings_{area}:manage"


def _routes():
    found = {}
    for path, route in walk_routes(app.routes):
        for method in route.methods - {"HEAD", "OPTIONS"}:
            found[(method, path.removeprefix("/api/v1"))] = set(required_permissions(route))
    return found


def test_every_route_of_an_area_needs_exactly_that_areas_permission():
    found = _routes()
    wrong = []
    for area, routes in ROUTES.items():
        for method, path in routes:
            if found.get((method, path)) != {_wanted(area, method, path)}:
                wrong.append(
                    f"{method} {path}: {sorted(found.get((method, path), ['(no such route)']))}, expected {_wanted(area, method, path)}"
                )
    assert wrong == []


def test_no_route_is_left_on_the_blanket_pair_so_every_area_can_be_granted_on_its_own():
    left = sorted(f"{m} {p}" for (m, p), perms in _routes().items() if perms & {"settings:read", "settings:write"})
    assert left == []


def test_the_blanket_pair_implies_every_area_and_nobody_loses_anything():
    for area in AREAS:
        assert permission_in(["settings:read"], f"settings_{area}:view"), area
        assert permission_in(["settings:write"], f"settings_{area}:manage"), area
        assert permission_in(["settings:write"], f"settings_{area}:view"), "Manage implies View, and settings:write implies Manage"
    for role in ("tenant_admin", "admin", "platform_admin"):
        for area in AREAS:
            assert permission_in(ROLE_PERMISSIONS[role], f"settings_{area}:manage"), (role, area)
            assert permission_in(ROLE_PERMISSIONS[role], f"settings_{area}:view"), (role, area)


def test_manage_implies_view_of_the_same_area_only_and_view_implies_nothing():
    for area in AREAS:
        assert permission_in([f"settings_{area}:manage"], f"settings_{area}:view")
        assert not permission_in([f"settings_{area}:view"], f"settings_{area}:manage")
        for other in AREAS:
            if other != area:
                assert not permission_in([f"settings_{area}:manage"], f"settings_{other}:view"), (area, other)
                assert not permission_in([f"settings_{area}:view"], f"settings_{other}:view"), (area, other)
        assert not permission_in([f"settings_{area}:manage"], "settings:read"), "an area is not the whole of Settings"
        assert not permission_in([f"settings_{area}:manage"], "settings:write")


def test_the_sixteen_permissions_are_known_and_named_by_area_and_level():
    names = {f"settings_{a}:{level}" for a in AREAS for level in ("view", "manage")}
    assert len(names) == 16 and names <= known_permissions()
    for name in names:
        assert re.fullmatch(r"[a-z_]{2,}:[a-z_]{2,}", name)
        assert name in IMPLIED_BY, name


@pytest.mark.parametrize("area", AREAS)
def test_a_role_with_only_one_area_cannot_use_the_others(area):
    held = [f"settings_{area}:manage"]
    for other in AREAS:
        if other != area:
            assert not permission_in(held, f"settings_{other}:view"), other

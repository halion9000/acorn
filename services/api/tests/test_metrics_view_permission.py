"""metrics:view: read the ticket metrics and customer satisfaction, split out of reports:read.

1. NOBODY LOSES ACCESS: whatever held reports:read (a role, a database role, a wildcard, a key) still reads the pages, because reports:read implies metrics:view.
2. metrics:view ALONE GRANTS NOTHING ELSE: a key holding only it satisfies exactly the two ticket-metrics reads among every route in the application.
3. CORE's key holds it (so the agents can read the numbers and the customers' written comments) and still does NOT hold reports:read.
"""

import pytest
from app.api.v1.endpoints import api_keys
from app.core.security import IMPLIED_BY, ROLE_PERMISSIONS, has_permission, known_permissions, permission_in
from app.main import app
from app.scripts.bootstrap_production import CORE_KEY_SCOPES
from route_introspect import required_permissions as _required_permissions
from route_introspect import walk_routes

ALL_ROUTES = [(path.replace("/api/v1", "", 1), route) for path, route in walk_routes(app.routes)]


def required(route) -> set[str]:
    return set(_required_permissions(route))


def _satisfied_by(scopes) -> set[tuple[str, str]]:
    out = set()
    for path, route in ALL_ROUTES:
        needed = required(route)
        if needed and all(permission_in(scopes, p) for p in needed):
            out |= {(m, path) for m in route.methods if m not in {"HEAD", "OPTIONS"}}
    return out


@pytest.mark.parametrize(
    "granted,expected",
    [
        (["metrics:view"], True),
        (["reports:read"], True),
        (["metrics:*"], True),
        (["*"], True),
        (["reports:write"], False),
        (["alerts:read"], False),
        ([], False),
    ],
)
def test_who_holds_metrics_view(granted, expected):
    assert permission_in(granted, "metrics:view") is expected


def test_metrics_view_alone_grants_no_other_permission_and_the_implication_is_one_way():
    assert {p for p in known_permissions() if permission_in(["metrics:view"], p)} == {"metrics:view"}
    assert not permission_in(["metrics:view"], "reports:read")
    assert IMPLIED_BY["metrics:view"] == ("reports:read",)
    assert "metrics:view" in known_permissions() and "metrics:view" in api_keys.VALID_SCOPES


def test_every_role_reads_the_metrics_exactly_when_it_could_before():
    for role in ROLE_PERMISSIONS:
        assert has_permission(role, "metrics:view") == has_permission(role, "reports:read"), role


def test_a_key_with_only_metrics_view_reaches_exactly_the_metrics_reads():
    expected = {(m, p) for p, r in ALL_ROUTES if p.startswith(("/reports/ticket-metrics", "/reports/metrics/")) for m in ("GET",)}
    assert {(m, p) for p, r in ALL_ROUTES if required(r) == {"metrics:view"} for m in ("GET",)} == expected
    assert _satisfied_by(["metrics:view"]) == expected


def test_cores_key_can_read_the_metrics_and_still_cannot_read_the_other_reports():
    assert "metrics:view" in CORE_KEY_SCOPES and "reports:read" not in CORE_KEY_SCOPES
    assert permission_in(CORE_KEY_SCOPES, "metrics:view") and not permission_in(CORE_KEY_SCOPES, "reports:read")

"""billing:view: read the licence and count pages, split out of alerts:read.

The GET routes under /billing used to need alerts:read, so the only way to let someone see counts was to let them read alerts. billing:view is exactly those reads.
  1. NOBODY LOSES ACCESS: whatever held alerts:read (a role, a database role, a wildcard, a key) still reads the pages, because alerts:read implies billing:view.
  2. billing:view ALONE GRANTS NOTHING ELSE: a key holding only it satisfies exactly the billing reads among every route in the application.
  3. Changing anything under /billing still needs mssp:manage.
"""

import pytest
from app.api.v1.endpoints import api_keys
from app.core.security import IMPLIED_BY, ROLE_PERMISSIONS, has_permission, known_permissions, permission_in
from app.main import app
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


def _billing_gets() -> set[tuple[str, str]]:
    return {(m, p) for p, r in ALL_ROUTES if p.startswith("/billing") and "GET" in r.methods for m in ("GET",)}


@pytest.mark.parametrize(
    "granted,expected",
    [
        (["billing:view"], True),
        (["alerts:read"], True),
        (["billing:*"], True),
        (["*"], True),
        (["alerts:write"], False),
        (["mssp:manage"], False),
        ([], False),
    ],
)
def test_who_holds_billing_view(granted, expected):
    assert permission_in(granted, "billing:view") is expected


def test_billing_view_alone_grants_no_other_permission_and_the_implication_is_one_way():
    assert {p for p in known_permissions() if permission_in(["billing:view"], p)} == {"billing:view"}
    assert not permission_in(["billing:view"], "alerts:read")
    assert IMPLIED_BY["billing:view"] == ("alerts:read",)
    assert "billing:view" in known_permissions() and "billing:view" in api_keys.VALID_SCOPES


def test_every_role_reads_billing_exactly_when_it_could_before():
    for role in ROLE_PERMISSIONS:
        assert has_permission(role, "billing:view") == has_permission(role, "alerts:read"), role


def test_every_billing_read_needs_billing_view_and_a_key_with_only_it_reaches_exactly_those_routes():
    gets = _billing_gets()
    assert len(gets) >= 8, "the comparison would be empty otherwise"
    assert {(m, p) for p, r in ALL_ROUTES if required(r) == {"billing:view"} for m in ("GET",)} == gets
    assert _satisfied_by(["billing:view"]) == gets


def test_changing_anything_under_billing_still_needs_the_manage_permission_and_billing_view_does_not_reach_it():
    writes = {(m, p) for p, r in ALL_ROUTES if p.startswith("/billing") for m in r.methods if m in {"PUT", "POST", "DELETE"}}
    assert writes, "there are writes under /billing"
    reach = _satisfied_by(["billing:view"])
    for m, p in writes:
        assert (m, p) not in reach, (m, p)

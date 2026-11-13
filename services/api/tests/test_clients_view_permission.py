"""Seeing the organisation's clients is a permission of its own (clients:view), on for every role that exists today and switchable off per role.

Before it, the client list that the pickers read needed mssp:read, which is not in the role editor, so a custom role (the vCIO role) saw only "Own organisation" and nobody could grant it. Hal,
2026-11-13: every user of the organisation sees all clients, and it must still be possible to allow it or not, per role.
"""

from app.core.security import ROLE_PERMISSIONS, known_permissions, permission_in
from app.main import app
from route_introspect import required_permissions, walk_routes

# The roles of people (the API-service role is a key's scope, and the wildcard roles hold everything).
PEOPLE_ROLES = ("tenant_admin", "soc_lead", "soc_analyst", "threat_hunter", "viewer")


def _needs(method, path):
    for p, route in walk_routes(app.routes):
        if p == path and method in route.methods:
            return set(required_permissions(route))
    raise AssertionError((method, path))


def test_both_client_lists_need_exactly_clients_view():
    assert _needs("GET", "/api/v1/mssp/children") == {"clients:view"}
    assert _needs("GET", "/api/v1/vcio-risk-scoring/clients") == {"clients:view"}


def test_every_role_that_exists_holds_it_and_the_wildcard_still_covers_it():
    for role in PEOPLE_ROLES:
        assert permission_in(ROLE_PERMISSIONS[role], "clients:view"), role
    assert permission_in(ROLE_PERMISSIONS["admin"], "clients:view")
    assert permission_in(ROLE_PERMISSIONS["platform_admin"], "clients:view")
    assert "clients:view" in known_permissions()


def test_a_role_without_it_does_not_see_the_clients_whatever_else_it_holds():
    # The switch has to be able to say no: nothing else implies it (mssp:read, alerts:read and the rest do not).
    for held in (["alerts:read"], ["mssp:read", "alerts:read", "vcio:assess"], ["mssp:manage"]):
        assert not permission_in(held, "clients:view"), held
    assert permission_in(["clients:view"], "clients:view")
    assert not permission_in(["clients:view"], "mssp:read"), "seeing the list is not the rest of the console"

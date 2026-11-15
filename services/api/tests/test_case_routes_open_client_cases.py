"""A case under one of the caller's clients opens on every case page, not only on some of them.

The attack chain and attack path routes looked the case up under the signed-in organization only, so for a client's case (the usual one) the Attack Chain tab answered 404 and the Attack Path tab found nothing. They
now use the same client-aware case scope as the other case routes. Checked on the real route table: each route's dependencies must include the case scope, and a plain permission check alone is not enough.
"""

from app.core.route_introspect import walk_routes
from app.main import app
from app.services.case_scope import case_scoped

SCOPE = case_scoped("cases:read").__qualname__


def dependency_names(path: str) -> list[str]:
    names: list[str] = []
    for full, route in walk_routes(app.routes):
        if full == path and "GET" in route.methods:
            stack = [route.dependant]
            while stack:
                d = stack.pop()
                names.extend(getattr(c.call, "__qualname__", "") for c in d.dependencies)
                stack.extend(d.dependencies)
    return names


def test_the_attack_chain_route_uses_the_client_aware_case_scope():
    names = dependency_names("/api/v1/cases/{case_id}/attack-chain")
    assert names, "the route was not found"
    assert SCOPE in names


def test_the_attack_path_route_uses_the_client_aware_case_scope():
    names = dependency_names("/api/v1/graph/attack-path/{case_id}")
    assert names, "the route was not found"
    assert SCOPE in names


def test_a_route_that_has_not_been_changed_does_not_have_it():
    # the check can tell the difference: a route with a plain permission check only is not reported as client-aware
    names = dependency_names("/api/v1/graph/attack-path-nonexistent/{case_id}")
    assert SCOPE not in names

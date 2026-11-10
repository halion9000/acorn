"""Checking a device out and back in is a technician task: soc_lead and soc_analyst can do it, and it does not give them the rest of inventory (add, change, delete, bulk edit, sync, import)."""

from app.main import app
from app.core.security import ROLE_PERMISSIONS, permission_in
from route_introspect import required_permissions, walk_routes


def _perms(method, suffix):
    for path, route in walk_routes(app.routes):
        if path.startswith("/api/v1/inventory/") and path.endswith(suffix) and method in route.methods:
            return set(required_permissions(route))
    raise AssertionError((method, suffix))


def test_the_two_check_routes_need_only_the_narrow_permission():
    assert _perms("POST", "/check-out") == {"inventory:checkout"}
    assert _perms("POST", "/check-in") == {"inventory:checkout"}


def test_technicians_and_administrators_hold_it_and_viewers_do_not():
    for role in ("soc_lead", "soc_analyst", "admin", "tenant_admin", "platform_admin"):
        assert permission_in(ROLE_PERMISSIONS[role], "inventory:checkout"), role
    for role in ("viewer", "threat_hunter"):
        assert not permission_in(ROLE_PERMISSIONS[role], "inventory:checkout"), role


def test_a_technician_still_cannot_add_change_delete_or_import_inventory():
    for role in ("soc_lead", "soc_analyst"):
        assert not permission_in(ROLE_PERMISSIONS[role], "inventory:write"), role
    assert _perms("POST", "/import") == {"inventory:write"}
    assert _perms("POST", "/bulk") == {"inventory:write"}


def test_inventory_write_implies_checkout_one_way_only():
    assert permission_in(["inventory:write"], "inventory:checkout")
    assert not permission_in(["inventory:checkout"], "inventory:write")

"""The built-in roles are listed with exactly what they grant."""

import asyncio

from app.api.v1.endpoints import rbac
from app.core.security import ROLE_PERMISSIONS


def listed():
    return asyncio.run(rbac.list_builtin_roles(current_user=None))


def test_the_five_roles_an_administrator_can_hand_out_are_listed_in_order():
    assert [r.key for r in listed()] == ["viewer", "soc_analyst", "threat_hunter", "soc_lead", "tenant_admin"]
    assert [r.label for r in listed()][-1] == "Administrator"


def test_each_role_lists_exactly_what_the_access_checks_grant_it():
    for r in listed():
        assert r.permissions == sorted(ROLE_PERMISSIONS[r.key]), r.key
        assert r.permissions, r.key


def test_platform_and_legacy_admin_roles_are_never_offered():
    keys = {r.key for r in listed()}
    assert not keys & {"platform_admin", "admin"}
    assert all("*" not in r.permissions for r in listed())


def test_every_role_has_a_plain_description():
    assert all(len(r.description) > 10 for r in listed())

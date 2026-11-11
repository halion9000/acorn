"""Account actions on the Identities page: what a click queues for CORE, who may click, and what is refused before anything is queued."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import identity_actions as ep
from app.core.security import ROLE_PERMISSIONS, permission_in
from fastapi import HTTPException

OWNER, CLIENT = uuid.uuid4(), uuid.uuid4()
USER = NS(tenant_id=OWNER, user_id=uuid.uuid4(), email="hal@liveoak.example")


def run(coro):
    return asyncio.run(coro)


def body(**over):
    base = {"client_id": CLIENT, "email": "pat@acme.com", "action": "disable_user", "confirm": True}
    return ep.ActionBody(**{**base, **over})


class Fake:
    """A database that answers 'is one already waiting' with the rows it is given, and records what is added."""

    def __init__(self, waiting=()):
        self.waiting = list(waiting)
        self.added = []
        self.commits = 0
        result = MagicMock()
        result.scalars.return_value.all.side_effect = lambda: list(self.waiting)
        self.execute = AsyncMock(return_value=result)

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


@pytest.fixture
def wired(monkeypatch):
    audit = AsyncMock()
    monkeypatch.setattr(ep, "emit_audit", audit)
    monkeypatch.setattr(ep, "_scope", AsyncMock(return_value=([CLIENT], {CLIENT: "Acme"})))
    monkeypatch.setattr(ep, "_as", lambda db, owner, tid: contextlib.nullcontext())
    monkeypatch.setattr(ep, "cipp_customer", AsyncMock(return_value="cipp-customer-1"))
    return audit


def ask(db, **over):
    return run(ep.request_identity_action(body(**over), MagicMock(), USER, db))


def test_a_confirmed_request_queues_one_row_for_core_with_the_cipp_customer_and_the_sign_in_name(wired):
    db = Fake()
    item = ask(db)
    assert item.status == "pending" and item.action == "disable_user" and item.email == "pat@acme.com"
    row = db.added[0]
    assert (row.vendor, row.status, row.alert_id, row.tenant_id) == ("core", "pending", None, CLIENT)
    assert row.params["client_id"] == "cipp-customer-1" and row.params["user"] == "pat@acme.com"
    assert row.requested_by == USER.user_id and db.commits == 1


def test_every_request_is_written_to_the_audit_log_with_who_asked_and_what(wired):
    ask(Fake(), action="revoke_sessions")
    kwargs = wired.await_args.kwargs
    assert kwargs["actor_id"] == USER.user_id and kwargs["action"] == "identities:account_action_requested"
    assert kwargs["changes"]["action"] == "revoke_sessions" and kwargs["changes"]["email"] == "pat@acme.com"


def test_nothing_is_queued_without_the_confirmation(wired):
    db = Fake()
    with pytest.raises(HTTPException) as e:
        ask(db, confirm=False)
    assert e.value.status_code == 422 and db.added == [] and db.commits == 0


@pytest.mark.parametrize(
    "bad", ["", "pat", "pat@acme", "pat@acme.com, ceo@acme.com", "pat@acme.com\nx", "a b@acme.com", "pat@acme.com'; drop"]
)
def test_an_address_that_is_not_one_plain_mailbox_is_refused_before_it_can_reach_core(wired, bad):
    db = Fake()
    with pytest.raises(HTTPException) as e:
        ask(db, email=bad)
    assert e.value.status_code == 422 and db.added == []


def test_a_client_that_is_not_linked_to_cipp_gets_a_clear_refusal_not_a_queued_row(wired, monkeypatch):
    monkeypatch.setattr(ep, "cipp_customer", AsyncMock(return_value=None))
    db = Fake()
    with pytest.raises(HTTPException) as e:
        ask(db)
    assert e.value.status_code == 409 and "CIPP" in e.value.detail and db.added == []


def test_the_owners_own_tenant_is_not_a_client_to_act_on(wired):
    with pytest.raises(HTTPException) as e:
        ask(Fake(), client_id=OWNER)
    assert e.value.status_code == 422


def test_the_same_request_twice_while_one_is_waiting_is_refused(wired):
    waiting = [NS(id=uuid.uuid4())]
    db = Fake(waiting=waiting)
    with pytest.raises(HTTPException) as e:
        ask(db)
    assert e.value.status_code == 409 and db.added == []


def test_a_client_that_is_not_this_companys_is_refused_by_the_scope_check(wired, monkeypatch):
    monkeypatch.setattr(ep, "_scope", AsyncMock(side_effect=HTTPException(status_code=404, detail="Client not found")))
    db = Fake()
    with pytest.raises(HTTPException) as e:
        ask(db)
    assert e.value.status_code == 404 and db.added == []


def test_the_page_says_running_for_a_row_core_has_collected_and_shows_core_s_own_words():
    row = ep.build_row(
        tenant_id=CLIENT,
        cipp_client="c",
        email="Pat@Acme.com",
        action="enable_user",
        requested_by=None,
        requested_by_name="Hal",
        now=datetime.now(UTC),
    )
    row.status, row.result_message, row.finished_at = "claimed", None, None
    assert ep.item_of(row).status == "running"
    row.status, row.result_message = "failed", "Refused by CORE: this account is protected."
    got = ep.item_of(row)
    assert got.status == "failed" and got.message == "Refused by CORE: this account is protected." and got.requested_by == "Hal"
    assert row.incident_uid == "identity:pat@acme.com"


def test_only_an_administrator_or_a_role_that_ticks_the_permission_may_use_it():
    assert permission_in(ROLE_PERMISSIONS["admin"], "identities:respond")
    assert permission_in(ROLE_PERMISSIONS["platform_admin"], "identities:respond")
    for role in ("tenant_admin", "analyst", "viewer", "custom"):
        assert not permission_in(ROLE_PERMISSIONS.get(role, []), "identities:respond"), role
    assert permission_in(["identities:respond"], "identities:respond")
    # reading alerts or writing them never carries it
    assert not permission_in(["alerts:write", "alerts:read", "connectors:write"], "identities:respond")


def test_the_route_is_guarded_by_the_permission_and_the_status_read_by_alert_read():
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    assert set(required_permissions(found[("POST", "/identities/actions")])) == {"identities:respond"}
    assert set(required_permissions(found[("GET", "/identities/actions")])) == {"alerts:read"}


def test_the_core_key_cannot_ask_for_account_actions():
    """CORE's own key must never be able to queue an account action: only a signed-in person with the permission."""
    from app.scripts import bootstrap_production as bp

    assert not permission_in(bp.CORE_KEY_SCOPES, "identities:respond")

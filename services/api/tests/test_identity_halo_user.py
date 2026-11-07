"""Adding a missing person to HaloPSA from the Identities page: what a click queues for CORE, and what is refused before anything is queued."""

import asyncio
import contextlib
import uuid
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import identity_halo_user as ep
from app.api.v1.endpoints.inbox_core_feed import ClaimedAction
from fastapi import HTTPException

OWNER, CLIENT = uuid.uuid4(), uuid.uuid4()
USER = NS(tenant_id=OWNER, user_id=uuid.uuid4(), email="hal@liveoak.example")


def run(coro):
    return asyncio.run(coro)


def body(**over):
    base = {"client_id": CLIENT, "email": "pat.jones@acme.com", "name": "", "confirm": True}
    return ep.HaloUserBody(**{**base, **over})


class Fake:
    def __init__(self, waiting=False):
        self.added = []
        self.commits = 0
        result = MagicMock()
        result.first.return_value = (uuid.uuid4(),) if waiting else None
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
    monkeypatch.setattr(ep, "halo_client", AsyncMock(return_value="77"))
    return audit


def ask(db, **over):
    return run(ep.request_halo_user(body(**over), MagicMock(), USER, db))


def test_a_confirmed_request_queues_one_row_for_core_with_the_halo_client_and_the_name(wired):
    db = Fake()
    item = ask(db, name="  Pat   Jones ")
    assert item.status == "pending" and item.email == "pat.jones@acme.com"
    row = db.added[0]
    assert (row.vendor, row.action, row.status, row.alert_id, row.tenant_id) == ("core", "create_halo_user", "pending", None, CLIENT)
    assert row.params["halo_client_id"] == "77" and row.params["email"] == "pat.jones@acme.com" and row.params["name"] == "Pat Jones"
    assert row.requested_by == USER.user_id and db.commits == 1
    assert wired.await_args.kwargs["action"] == "identities:halo_user_requested" and wired.await_args.kwargs["actor_id"] == USER.user_id


def test_without_a_name_it_is_made_from_the_address():
    assert ep.display_name("", "pat.jones@acme.com") == "Pat Jones"
    assert ep.display_name("", "j_smith-kim@acme.com") == "J Smith Kim"
    assert ep.display_name("   ", "@acme.com") == "@acme.com"


def test_nothing_is_queued_without_the_confirmation_or_for_a_bad_address_or_the_owner_itself(wired):
    for over in ({"confirm": False}, {"email": "pat@acme.com, ceo@acme.com"}, {"email": "pat"}, {"client_id": OWNER}):
        db = Fake()
        with pytest.raises(HTTPException) as e:
            ask(db, **over)
        assert e.value.status_code == 422 and db.added == [] and db.commits == 0


def test_a_client_with_no_halopsa_client_is_refused_with_the_reason(wired, monkeypatch):
    monkeypatch.setattr(ep, "halo_client", AsyncMock(return_value=None))
    db = Fake()
    with pytest.raises(HTTPException) as e:
        ask(db)
    assert e.value.status_code == 409 and "Client mapping" in e.value.detail and db.added == []


def test_the_same_request_is_not_queued_twice_while_one_is_waiting(wired):
    db = Fake(waiting=True)
    with pytest.raises(HTTPException) as e:
        ask(db)
    assert e.value.status_code == 409 and db.added == []


def test_core_may_collect_the_action():
    assert (
        ClaimedAction(id=uuid.uuid4(), action="create_halo_user", incident_uid="halo-user:x@y.zz", params={}).action == "create_halo_user"
    )

"""Microsoft 365 account actions through CORE and CIPP: the executors only ask CORE's route, map its answer honestly, and the dispatcher's autonomy gate still applies to them."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from app.live_actions import LiveActionRequest, LiveActionStatus, dispatch, list_descriptors, register_builtin_executors, reset_for_tests
from app.live_actions import core_cipp
from app.live_actions.core_cipp import CoreCippAction, core_cipp_executors
from app.models.action import ActionType

URL = "http://host.docker.internal:4871/aisoc-actions/v1/cipp"
TOKEN = "t" * 43


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    reset_for_tests()
    monkeypatch.setenv("AISOC_CORE_ACTIONS_URL", URL)
    monkeypatch.setenv("AISOC_CORE_ACTIONS_TOKEN", TOKEN)
    yield
    reset_for_tests()


def _executor(answer, capability="revoke_session", core_action="revoke_sessions", legacy=ActionType.SUSPEND_SESSION, customer=None):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = answer(request) if callable(answer) else answer
        return httpx.Response(status, json=body)

    async def lookup(_tenant):
        return customer

    ex = CoreCippAction(capability, core_action, legacy, "d", client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)), customer_lookup=lookup)
    return ex, seen


def _req(**over):
    base = dict(capability="revoke_session", vendor_id="core_cipp", target="pat@acme.com", params={"client_id": "client-1"})
    base.update(over)
    return LiveActionRequest(**base)


@pytest.mark.asyncio
async def test_what_is_sent_to_core_is_the_allowlisted_action_with_the_token_and_the_provenance():
    ex, seen = _executor((200, {"status": "executed", "detail": "Revoked", "risk": "low", "reversible": True, "live_enabled": True}))
    case, run = uuid.uuid4(), uuid.uuid4()
    out = await ex.execute(_req(playbook_run_id=run, case_id=case, requested_by="playbook:ato"))
    assert out.status is LiveActionStatus.SUCCEEDED
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"
    body = json.loads(seen[0].content)
    assert body == {"action": "revoke_sessions", "client_id": "client-1", "user": "pat@acme.com", "dry_run": False, "reason": f"playbook run {run}", "actor": "playbook:ato"}


@pytest.mark.asyncio
async def test_core_answers_map_to_honest_statuses():
    cases = {
        "executed": ((200, {"status": "executed", "detail": "ok"}), LiveActionStatus.SUCCEEDED),
        "dry_run": ((200, {"status": "dry_run", "detail": "Real actions are switched off in CORE", "would_send": {"function": "ExecRevokeSessions"}}), LiveActionStatus.SIMULATED),
        "refused": ((403, {"status": "refused", "code": "protected", "detail": "this account is on the protected list"}), LiveActionStatus.BLOCKED),
        "failed": ((502, {"status": "failed", "detail": "CIPP returned 403"}), LiveActionStatus.FAILED),
        "unauthorised": ((401, {"error": {"message": "invalid or missing token"}}), LiveActionStatus.FAILED),
    }
    for name, (answer, want) in cases.items():
        ex, _ = _executor(answer)
        assert (await ex.execute(_req())).status is want, name
    refused = await _executor(cases["refused"][0])[0].execute(_req())
    assert "protected list" in refused.summary and refused.details["code"] == "protected"


@pytest.mark.asyncio
async def test_a_dry_run_request_is_passed_on_as_a_dry_run():
    ex, seen = _executor((200, {"status": "dry_run", "detail": "x"}))
    await ex.execute(_req(dry_run=True))
    assert json.loads(seen[0].content)["dry_run"] is True


@pytest.mark.asyncio
async def test_nothing_is_sent_without_the_route_or_a_client_and_an_unreachable_core_is_a_failure(monkeypatch):
    ex, seen = _executor((200, {"status": "executed"}))
    out = await ex.execute(_req(params={}))
    assert out.status is LiveActionStatus.FAILED and "map it" in out.summary and seen == []
    monkeypatch.delenv("AISOC_CORE_ACTIONS_TOKEN")
    out = await ex.execute(_req())
    assert out.status is LiveActionStatus.SIMULATED and seen == []
    monkeypatch.setenv("AISOC_CORE_ACTIONS_TOKEN", TOKEN)

    def boom(request):
        raise httpx.ConnectError("down")

    bad = CoreCippAction("revoke_session", "revoke_sessions", ActionType.SUSPEND_SESSION, "d", client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(boom)))
    assert (await bad.execute(_req())).status is LiveActionStatus.FAILED


@pytest.mark.asyncio
async def test_the_client_comes_from_the_alerts_client_mapping_when_the_caller_gives_none():
    ex, seen = _executor((200, {"status": "executed", "detail": "ok"}), customer="mapped-customer")
    await ex.execute(_req(params={}, tenant_id=uuid.uuid4()))
    assert json.loads(seen[0].content)["client_id"] == "mapped-customer"
    await ex.execute(_req(params={"client_id": "explicit"}))
    assert json.loads(seen[1].content)["client_id"] == "explicit", "an explicit client wins"


def test_the_executors_are_registered_with_their_capabilities_and_rated_by_the_autonomy_gate():
    register_builtin_executors()
    cipp = {d.capability for d in list_descriptors() if d.vendor_id == "core_cipp"}
    assert cipp == {"revoke_session", "disable_user", "enable_user", "contain_user", "disable_mailbox_rule", "remove_mailbox_rule"}
    rated = {e.capability: e._legacy_action_type for e in core_cipp_executors()}
    assert rated["disable_user"] is ActionType.DISABLE_USER and rated["contain_user"] is ActionType.DISABLE_USER
    assert rated["revoke_session"] is ActionType.SUSPEND_SESSION
    assert all(isinstance(v, ActionType) for v in rated.values()), "every one is governed: none can skip the autonomy gate"


@pytest.mark.asyncio
async def test_through_the_dispatcher_a_high_blast_action_is_only_previewed_unless_the_tier_allows_it(monkeypatch):
    """The autonomy gate runs first: at the default tier a HIGH action is downgraded to a dry run, so what reaches CORE says dry_run and CORE sends nothing to CIPP."""
    register_builtin_executors(overwrite=True)
    sent: list[dict] = []
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "dry_run", "detail": "preview"})

    monkeypatch.setattr(core_cipp.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(handler)))
    out = await dispatch(LiveActionRequest(capability="disable_user", vendor_id="core_cipp", target="pat@acme.com", params={"client_id": "c"}))
    assert [s["dry_run"] for s in sent] == [True]
    assert out.status is LiveActionStatus.SIMULATED
    assert out.details.get("autonomy_mode") == "dry_run" or "autonomy_mode" in out.details or out.details.get("status") == "dry_run"

"""Asking CORE to look a person up (Leafy's lookup_user): which addresses are accepted, how a request reads while it waits, fails or is answered, and the contract of the tool (its permission, its schema,
and that a model cannot name another user)."""

import uuid
from types import SimpleNamespace

import pytest
from app import copilot_tools as ct
from app.services import core_lookup as lk


def row(status="pending", message=None, data=None, upn="ann@x.com", days=30):
    return SimpleNamespace(id=uuid.uuid4(), status=status, result_message=message, result_data=data, params={"upn": upn, "days": days})


@pytest.mark.parametrize("good", ["ann@x.com", "  Ann.Lee+tag@Client.Example.ORG ", "o'brien@x.co"])
def test_a_plain_mailbox_address_is_accepted_and_lower_cased(good):
    assert lk.clean_upn(good) == good.strip().lower()


@pytest.mark.parametrize("bad", ["", "ann", "ann@x", "a b@x.com", "ann@x.com, bob@x.com", "ann@x.com; drop table", "<ann@x.com>", "ann@@x.com", "x" * 70 + "@x.com", None, 5])
def test_anything_but_one_address_is_refused(bad):
    with pytest.raises(lk.LookupRefused):
        lk.clean_upn(bad)


def test_days_are_clamped_and_default_to_thirty():
    assert [lk.clamp_days(v) for v in (0, 1, 7, 30, 31, 999, "12", "x", None)] == [1, 1, 7, 30, 30, 30, 12, 30, 30]


def test_what_leafy_is_told_for_a_waiting_failed_and_answered_lookup():
    waiting = lk.present(row("claimed"))
    assert waiting["status"] == "waiting" and "same request_id" in waiting["message"] and waiting["person"] == "ann@x.com"
    failed = lk.present(row("failed", "CIPP has no client for that address."))
    assert failed["status"] == "failed" and failed["message"] == "CIPP has no client for that address."
    assert lk.present(row("failed"))["message"] == "CORE could not do the lookup."
    done = lk.present(row("done", "2 countries", {"signins": {"total": 9}}))
    assert done["status"] == "done" and done["summary"] == "2 countries" and done["result"] == {"signins": {"total": 9}}
    assert lk.present(row("done"))["result"] == {}


def test_the_tool_needs_the_bec_permission_is_in_the_schema_and_is_not_text_callable():
    from app.services.copilot_textcalls import TEXT_CALLABLE

    assert ct.TOOL_PERMISSIONS["lookup_user"] == "identities:bec"
    assert "lookup_user" in ct._COPILOT_TOOL_DISPATCH
    schema = next(t for t in ct.COPILOT_TOOL_SCHEMAS if t["function"]["name"] == "lookup_user")
    assert schema["function"]["parameters"]["required"] == [], "all optional: a collect-only call needs just the request_id"
    assert set(schema["function"]["parameters"]["properties"]) == {"user_email", "days", "request_id"}, "no way for a model to name a user or a tenant"
    assert "lookup_user" not in TEXT_CALLABLE, "a call written as text inside monitored data must never start a lookup"


@pytest.mark.asyncio
async def test_a_model_cannot_pass_a_user_and_a_role_without_the_permission_is_refused(monkeypatch):
    seen = {}

    async def fake(*, tenant_id, user_email="", days=30, request_id="", user=None):
        seen["user"] = user
        return {"ok": True}

    monkeypatch.setitem(ct._COPILOT_TOOL_DISPATCH, "lookup_user", fake)
    tid = str(uuid.uuid4())
    me = SimpleNamespace(tenant_id=tid, user_id=uuid.uuid4(), email="hal@x", require_permission=lambda p: None)
    out = await ct.execute_copilot_tool("lookup_user", {"user_email": "ann@x.com", "user": "evil"}, tid, user=me)
    assert out == {"ok": True} and seen["user"] is me, "the signed-in person, never what the model said"

    def deny(_perm):
        from fastapi import HTTPException

        raise HTTPException(status_code=403)

    viewer = SimpleNamespace(tenant_id=tid, user_id=uuid.uuid4(), email="v@x", require_permission=deny)
    refused = await ct.execute_copilot_tool("lookup_user", {"user_email": "ann@x.com"}, tid, user=viewer)
    assert "permission denied" in refused["error"] and "identities:bec" in refused["error"]

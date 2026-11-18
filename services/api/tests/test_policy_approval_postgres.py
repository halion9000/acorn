"""Approval of a policy version on a REAL Postgres: a request names another person, only that person decides (once), a rejection needs a reason, a re-request after a rejection works, an API key does
neither, and another owner sees nothing. Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database, migration 210 applied)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import governance as ep
from app.api.v1.endpoints.governance import ApprovalDecisionIn, ApprovalRequestIn, ItemIn, VersionIn
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    async def noop(**_kw):
        return None

    monkeypatch.setattr(ep, "emit_audit", noop)


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    a, b = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (a, b):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"ap-{t.hex[:10]}"})
        await s.commit()
        s.info.update(a=a, b=b)
        yield s
        await off(s)
        for tbl in ("policy_approvals", "governance_versions", "governance_items"):
            await s.execute(text(f"delete from {tbl} where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine.dispose()


def person(t, email):
    return SimpleNamespace(tenant_id=t, user_id=None, email=email, scopes=None)


def key(t):
    return SimpleNamespace(tenant_id=t, user_id=None, email="core@x", scopes=["alerts:write"])


async def refuse(s, coro, code):
    with pytest.raises(HTTPException) as e:
        await coro
    assert e.value.status_code == code, e.value.detail
    await off(s)


async def test_request_decide_reject_and_ask_again(world):
    s, a = world, world.info["a"]
    amy, bob, eve = person(a, "Amy@x.com"), person(a, "bob@x.com"), person(a, "eve@x.com")
    await off(s)
    item = await ep.create_item(a, ItemIn(kind="policy", title="Acceptable use"), None, amy, s)
    await off(s)
    await refuse(s, ep.request_approval(a, item.id, ApprovalRequestIn(approver_email="bob@x.com"), None, amy, s), 422)  # nothing to approve yet
    await ep.add_version(a, item.id, VersionIn(body="v1 text"), None, amy, s)
    await off(s)
    assert (await ep.list_versions(a, item.id, amy, s))[0].approval == "none"
    await refuse(s, ep.request_approval(a, item.id, ApprovalRequestIn(approver_email="amy@x.com"), None, amy, s), 422)  # not herself
    req = await ep.request_approval(a, item.id, ApprovalRequestIn(approver_email="Bob@x.com", note="please check section 3"), None, amy, s)
    assert (req.version, req.approver, req.requested_by, req.decision) == (1, "bob@x.com", "amy@x.com", "pending")
    await off(s)
    await refuse(s, ep.request_approval(a, item.id, ApprovalRequestIn(approver_email="eve@x.com"), None, amy, s), 422)  # one waiting request per version
    assert (await ep.list_versions(a, item.id, amy, s))[0].approval == "pending"
    await off(s)
    await refuse(s, ep.decide_approval(a, item.id, req.id, ApprovalDecisionIn(decision="approved"), None, eve, s), 403)  # not the approver
    await refuse(s, ep.decide_approval(a, item.id, req.id, ApprovalDecisionIn(decision="approved"), None, amy, s), 403)  # not the requester either
    await refuse(s, ep.decide_approval(a, item.id, req.id, ApprovalDecisionIn(decision="rejected", comment=" "), None, bob, s), 422)  # a reason is needed
    rejected = await ep.decide_approval(a, item.id, req.id, ApprovalDecisionIn(decision="rejected", comment="backups are not covered"), None, bob, s)
    assert (rejected.decision, rejected.decided_by, rejected.comment) == ("rejected", "bob@x.com", "backups are not covered") and rejected.decided_at is not None
    await off(s)
    await refuse(s, ep.decide_approval(a, item.id, req.id, ApprovalDecisionIn(decision="approved"), None, bob, s), 422)  # decided once
    again = await ep.request_approval(a, item.id, ApprovalRequestIn(approver_email="bob@x.com"), None, amy, s)  # fine after a rejection
    await off(s)
    ok = await ep.decide_approval(a, item.id, again.id, ApprovalDecisionIn(decision="approved"), None, bob, s)
    assert ok.decision == "approved"
    await off(s)
    assert (await ep.list_versions(a, item.id, amy, s))[0].approval == "approved"
    await off(s)
    history = await ep.list_approvals(a, item.id, s)
    assert [h.decision for h in history] == ["approved", "rejected"], "both stay on file, newest first"


async def test_a_new_version_starts_with_no_approval_and_an_api_key_neither_asks_nor_decides(world):
    s, a = world, world.info["a"]
    amy, bob = person(a, "amy@x.com"), person(a, "bob@x.com")
    await off(s)
    item = await ep.create_item(a, ItemIn(kind="policy", title="Backup"), None, amy, s)
    await off(s)
    await ep.add_version(a, item.id, VersionIn(body="v1"), None, amy, s)
    await off(s)
    req = await ep.request_approval(a, item.id, ApprovalRequestIn(approver_email="bob@x.com"), None, amy, s)
    await off(s)
    await ep.decide_approval(a, item.id, req.id, ApprovalDecisionIn(decision="approved"), None, bob, s)
    await off(s)
    await ep.add_version(a, item.id, VersionIn(body="v2"), None, amy, s)
    await off(s)
    versions = {v.version: v.approval for v in await ep.list_versions(a, item.id, amy, s)}
    assert versions == {1: "approved", 2: "none"}, "approving v1 says nothing about v2"
    await off(s)
    await refuse(s, ep.request_approval(a, item.id, ApprovalRequestIn(approver_email="bob@x.com"), None, key(a), s), 403)
    req2 = await ep.request_approval(a, item.id, ApprovalRequestIn(approver_email="bob@x.com"), None, amy, s)
    await off(s)
    await refuse(s, ep.decide_approval(a, item.id, req2.id, ApprovalDecisionIn(decision="approved"), None, key(a), s), 403)
    await refuse(s, ep.request_approval(a, item.id, ApprovalRequestIn(approver_email="eve@x.com", version=9), None, amy, s), 422)


async def test_another_owner_sees_and_decides_nothing(world):
    s, a, b = world, world.info["a"], world.info["b"]
    amy = person(a, "amy@x.com")
    await off(s)
    item = await ep.create_item(a, ItemIn(kind="policy", title="Access"), None, amy, s)
    await off(s)
    await ep.add_version(a, item.id, VersionIn(body="v1"), None, amy, s)
    await off(s)
    req = await ep.request_approval(a, item.id, ApprovalRequestIn(approver_email="bob@x.com"), None, amy, s)
    await off(s)
    await refuse(s, ep.list_approvals(b, item.id, s), 404)
    await refuse(s, ep.decide_approval(b, item.id, req.id, ApprovalDecisionIn(decision="approved"), None, person(b, "bob@x.com"), s), 404)

"""Leafy's lookup_user on a REAL Postgres, with a stand-in for CORE: the request is queued once, CORE collects it through the real claim, answers through the real result route, and Leafy's tool returns the
structured answer; a lookup nobody answers returns a request_id to collect later; the hourly limit holds; another owner cannot read the request. Opt in with AISOC_TEST_PG_URL (migration 208 applied)."""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app import copilot_tools as ct
from app.api.v1.endpoints import inbox_core_feed as feed
from app.models.vendor_action import VendorAction
from app.services import core_lookup as lk
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


@pytest.fixture
async def world(monkeypatch):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    a, b = uuid.uuid4(), uuid.uuid4()
    async with factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        for t in (a, b):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"lk-{t.hex[:10]}"})
        await s.commit()

    async def session(_tid):
        s = factory()
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        return s

    async def no_audit(**_kw):
        return None

    import app.services.audit as audit

    monkeypatch.setattr(ct, "_get_session", session)
    monkeypatch.setattr(audit, "emit_audit", no_audit)
    monkeypatch.setattr(ct, "LOOKUP_POLL_SECONDS", 0.05)
    monkeypatch.setattr(ct, "LOOKUP_WAIT_SECONDS", 1.0)
    yield factory, a, b
    async with factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await s.execute(text("delete from vendor_actions where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine.dispose()


def me(t):
    return SimpleNamespace(tenant_id=t, user_id=uuid.uuid4(), email="hal@x.com")


async def core_answers(factory, tenant, data, message="2 countries", status="done"):
    """What CORE does: collect the queued lookup (the real claim), then report the result (the real SQL the result route runs)."""
    for _ in range(100):
        async with factory() as s:
            await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            claimed = await feed.claim_actions(s, tenant, "core")
            await s.commit()
        if claimed:
            row = claimed[0]
            assert row.action == "user_lookup" and row.params == {"upn": "ann@x.com", "days": 7} and row.alert_id is None
            async with factory() as s:
                await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
                body = feed.ActionResult(status=status, message=message, data=data)
                await s.execute(
                    VendorAction.__table__.update().where(VendorAction.id == row.id).values(status=body.status, result_message=body.message, result_data=body.data, finished_at=datetime.now(UTC))
                )
                await s.commit()
            return
        await asyncio.sleep(0.02)


async def test_leafy_asks_core_gets_the_structured_answer_and_a_repeat_reuses_the_request(world):
    factory, a, _b = world
    answered = asyncio.create_task(core_answers(factory, a, {"signins": {"by_country": [{"country": "US", "count": 4}]}}))
    out = await ct.execute_copilot_tool("lookup_user", {"user_email": "Ann@X.com", "days": 7}, str(a), user=_allowed(a))
    await answered
    assert out["status"] == "done" and out["summary"] == "2 countries" and out["result"]["signins"]["by_country"][0]["country"] == "US"
    again = await ct.lookup_user(tenant_id=str(a), user_email="ann@x.com", days=7, user=me(a))
    assert again["request_id"] == out["request_id"] and again["status"] == "done", "the same question within two minutes is the same request"
    async with factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        assert len((await s.execute(select(VendorAction).where(VendorAction.tenant_id == a))).scalars().all()) == 1


def _allowed(t):
    return SimpleNamespace(tenant_id=str(t), user_id=uuid.uuid4(), email="hal@x.com", require_permission=lambda p: None)


async def test_an_unanswered_lookup_returns_a_request_id_that_collects_the_answer_later(world):
    factory, a, b = world
    waiting = await ct.lookup_user(tenant_id=str(a), user_email="bob@x.com", days=7, user=me(a))
    assert waiting["status"] == "waiting" and waiting["request_id"]
    await ct.lookup_user(tenant_id=str(a), user_email="x@x.com", user=me(a))  # a second, separate request
    async with factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await s.execute(VendorAction.__table__.update().where(VendorAction.id == uuid.UUID(waiting["request_id"])).values(status="failed", result_message="CIPP has no client for that address.", finished_at=datetime.now(UTC)))
        await s.commit()
    collected = await ct.lookup_user(tenant_id=str(a), request_id=waiting["request_id"], user=me(a))
    assert collected["status"] == "failed" and "no client" in collected["message"]
    other = await ct.lookup_user(tenant_id=str(b), request_id=waiting["request_id"], user=me(b))
    assert other == {"error": "No such lookup request."}, "another owner cannot read it"
    assert (await ct.lookup_user(tenant_id=str(a), user_email="not an address", user=me(a)))["error"].startswith("Give one e-mail address")
    assert (await ct.lookup_user(tenant_id=str(a), request_id="nope", user=me(a))) == {"error": "No such lookup request."}


async def test_the_hourly_limit_holds_and_a_failed_request_may_be_asked_again(world):
    factory, a, _b = world
    now = datetime.now(UTC)
    async with factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        for i in range(lk.MAX_PER_HOUR):
            s.add(VendorAction(id=uuid.uuid4(), tenant_id=a, alert_id=None, vendor="core", incident_uid=f"lookup:{i}", action="user_lookup", params={"upn": f"p{i}@x.com", "days": 30}, status="done", created_at=now - timedelta(minutes=10)))
        await s.commit()
    refused = await ct.lookup_user(tenant_id=str(a), user_email="one.more@x.com", user=me(a))
    assert "lookups have already been made" in refused["error"]
    async with factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await s.execute(text("delete from vendor_actions where tenant_id = :a"), {"a": a})
        s.add(VendorAction(id=uuid.uuid4(), tenant_id=a, alert_id=None, vendor="core", incident_uid="lookup:f", action="user_lookup", params={"upn": "ann@x.com", "days": 30}, status="failed", result_message="x", created_at=now))
        await s.commit()
        fresh = await lk.queue_user_lookup(s, a, None, "ann@x.com", 30)
        assert fresh.status == "pending", "a failed lookup is not reused"


async def test_the_result_data_is_capped(world):
    with pytest.raises(ValueError):
        feed.ActionResult(status="done", message="x", data={"blob": "x" * (feed.MAX_RESULT_DATA_CHARS + 1)})
    assert feed.ActionResult(status="done", message="x", data={"ok": 1}).data == {"ok": 1}

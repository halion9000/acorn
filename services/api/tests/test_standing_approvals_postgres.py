"""Standing approvals on a REAL Postgres: the table and the new approval columns exist, a matching card finds its approval, and another tenant's, a revoked or an expired one never does.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.api.v1.endpoints.approvals import _matching_standing_approval
from app.models.responder import AgentApproval
from app.models.standing_approval import StandingApproval
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
NOW = datetime.now(UTC)
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")]


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    a, b = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (a, b):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"t-{t.hex[:10]}"})
        await s.commit()
        s.info.update(a=a, b=b)
        yield s
        await off(s)
        await s.execute(text("delete from agent_approvals where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from agent_standing_approvals where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine.dispose()


def row(tenant, **over):
    base = {"tenant_id": tenant, "action_type": "add_case_comment", "client_id": None, "expires_at": NOW + timedelta(days=30), "created_at": NOW}
    return StandingApproval(**{**base, **over})


async def test_a_card_finds_only_an_active_approval_of_its_own_tenant(world):
    s = world
    a, b = s.info["a"], s.info["b"]
    s.add_all([row(b), row(a, revoked_at=NOW), row(a, expires_at=NOW - timedelta(days=1)), row(a, action_type="close_alert")])
    await s.commit()
    await off(s)
    assert await _matching_standing_approval(s, a, {"type": "add_case_comment"}, "t") is None, "another tenant's, revoked, expired and other-kind approvals do not match"
    good = row(a)
    s.add(good)
    await s.commit()
    await off(s)
    found = await _matching_standing_approval(s, a, {"type": "add_case_comment"}, "t")
    assert found is not None and found.id == good.id
    assert await _matching_standing_approval(s, a, {"type": "isolate_host"}, "t") is None


async def test_the_new_approval_columns_are_stored_and_read_back(world):
    s = world
    a = s.info["a"]
    sid = uuid.uuid4()
    ap = AgentApproval(tenant_id=a, title="t", summary="s", action={"type": "add_case_comment"}, undo={"how": "delete the comment"}, standing_approval_id=sid, status="approved", decided_at=NOW)
    s.add(ap)
    await s.commit()
    await off(s)
    got = (await s.execute(text("select standing_approval_id, undo, undone_at from agent_approvals where id = :i"), {"i": ap.id})).one()
    assert got[0] == sid and got[1] == {"how": "delete the comment"} and got[2] is None

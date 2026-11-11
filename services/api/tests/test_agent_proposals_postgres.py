"""The proposal log on a REAL Postgres: a proposal is stored under the caller's tenant with its evidence, one with no evidence is refused and nothing is stored, the database refuses a made-up rung or outcome,
an outcome can be set once, and another tenant's proposal is not found. Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import agent_proposals as ep
from app.api.v1.endpoints.agent_proposals import OutcomeIn, ProposalIn, list_proposals, record_proposal, set_outcome
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
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
def _no_audit(monkeypatch):
    async def noop(**_kw):
        return None

    monkeypatch.setattr(ep, "emit_audit", noop)


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    mine, other = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (mine, other):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"n-{t.hex[:10]}"})
        await s.commit()
        s.info.update(mine=mine, other=other)
        yield s
        await s.rollback()
        await off(s)
        await s.execute(text("delete from agent_proposals where tenant_id in (:a, :b)"), {"a": mine, "b": other})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": mine, "b": other})
        await s.commit()
    await engine.dispose()


def user(tenant):
    return SimpleNamespace(tenant_id=tenant, user_id=None, email="hal@example.com")


def body(**over):
    base = {
        "agent": "cipher",
        "action_type": "Close-As-False-Positive",
        "target": "alert 42",
        "summary": "Looks benign",
        "rung": "shadow",
        "evidence": [{"label": "the alert", "url": "https://x/a/42"}],
        "confidence": 0.8,
    }
    base.update(over)
    return ProposalIn(**base)


async def test_a_proposal_is_stored_under_the_callers_tenant_with_its_evidence_and_listed(world):
    s = world
    await off(s)
    out = await record_proposal(body(), None, user(s.info["mine"]), s)
    assert (
        out.action_type == "close-as-false-positive"
        and out.outcome == "none"
        and out.evidence == [{"label": "the alert", "url": "https://x/a/42"}]
    )
    await off(s)
    got = await list_proposals(user(s.info["mine"]), s, agent=None, rung=None, action_type=None, outcome=None, since_hours=None, limit=50)
    assert [p.id for p in got.items] == [out.id]
    assert got.summary["shadow_unreviewed"] == 1 and got.summary["by_rung"]["shadow"] == 1
    await off(s)
    theirs = await list_proposals(
        user(s.info["other"]), s, agent=None, rung=None, action_type=None, outcome=None, since_hours=None, limit=50
    )
    assert theirs.items == []


async def test_a_proposal_with_no_evidence_is_refused_and_nothing_is_stored(world):
    s = world
    await off(s)
    with pytest.raises(HTTPException) as err:
        await record_proposal(body(evidence=[{"label": "  "}]), None, user(s.info["mine"]), s)
    assert err.value.status_code == 422
    await off(s)
    n = (await s.execute(text("select count(*) from agent_proposals where tenant_id = :t"), {"t": s.info["mine"]})).scalar_one()
    assert n == 0


async def test_the_database_itself_refuses_a_made_up_rung_or_outcome(world):
    s = world
    await off(s)
    for col, val in (("rung", "yolo"), ("outcome", "maybe")):
        row = {"rung": "shadow", "outcome": "none", col: val}
        with pytest.raises(IntegrityError):
            await s.execute(
                text(
                    "insert into agent_proposals (tenant_id, agent, action_type, summary, rung, outcome) values (:t, 'a', 'x', 's', :rung, :outcome)"
                ),
                {"t": s.info["mine"], **row},
            )
        await s.rollback()
        await off(s)


async def test_the_list_can_be_narrowed_to_one_kind_of_action_and_one_verdict(world):
    s = world
    await off(s)
    a = await record_proposal(body(action_type="snooze-alert"), None, user(s.info["mine"]), s)
    await off(s)
    await record_proposal(body(action_type="comment-case"), None, user(s.info["mine"]), s)
    await off(s)
    await set_outcome(a.id, OutcomeIn(outcome="rejected", note="a script does this on purpose"), None, user(s.info["mine"]), s)
    await off(s)
    only_snooze = await list_proposals(
        user(s.info["mine"]), s, agent=None, rung=None, action_type="Snooze-Alert", outcome=None, since_hours=None, limit=50
    )
    assert [p.action_type for p in only_snooze.items] == ["snooze-alert"]
    await off(s)
    rejected = await list_proposals(
        user(s.info["mine"]), s, agent=None, rung=None, action_type=None, outcome="rejected", since_hours=None, limit=50
    )
    assert [(p.action_type, p.outcome_note) for p in rejected.items] == [("snooze-alert", "a script does this on purpose")]
    await off(s)
    nothing = await list_proposals(
        user(s.info["mine"]), s, agent=None, rung=None, action_type="snooze-alert", outcome="accepted", since_hours=None, limit=50
    )
    assert nothing.items == []


async def test_the_list_can_be_limited_to_the_last_hours(world):
    s = world
    await off(s)
    await record_proposal(body(), None, user(s.info["mine"]), s)
    await off(s)
    await s.execute(
        text(
            "insert into agent_proposals (tenant_id, agent, action_type, summary, rung, created_at) values (:t, 'a', 'old-one', 's', 'shadow', now() - interval '3 days')"
        ),
        {"t": s.info["mine"]},
    )
    await off(s)
    everything = await list_proposals(
        user(s.info["mine"]), s, agent=None, rung=None, action_type=None, outcome=None, since_hours=None, limit=50
    )
    assert len(everything.items) == 2
    await off(s)
    today = await list_proposals(user(s.info["mine"]), s, agent=None, rung=None, action_type=None, outcome=None, since_hours=24, limit=50)
    assert [p.action_type for p in today.items] == ["close-as-false-positive"]


async def test_an_outcome_is_set_once_and_another_tenants_proposal_is_not_found(world):
    s = world
    await off(s)
    out = await record_proposal(body(), None, user(s.info["mine"]), s)
    await off(s)
    done = await set_outcome(out.id, OutcomeIn(outcome="rejected", note="a script does this on purpose"), None, user(s.info["mine"]), s)
    assert done.outcome == "rejected" and done.outcome_note == "a script does this on purpose" and done.outcome_at is not None
    await off(s)
    with pytest.raises(HTTPException) as again:
        await set_outcome(out.id, OutcomeIn(outcome="accepted"), None, user(s.info["mine"]), s)
    assert again.value.status_code == 409
    await off(s)
    with pytest.raises(HTTPException) as foreign:
        await set_outcome(out.id, OutcomeIn(outcome="accepted"), None, user(s.info["other"]), s)
    assert foreign.value.status_code == 404

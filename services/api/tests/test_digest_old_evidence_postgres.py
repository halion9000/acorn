"""Old compliance evidence in the digest: the lines and the recommendation as pure functions, and on a REAL Postgres that only this tenant's ACCEPTED evidence is read, newest piece per control.
The Postgres test opts in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.services import executive_digest as ed
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
needs_pg = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


def ago(days):
    return NOW - timedelta(days=days)


def test_one_line_per_framework_with_old_evidence_the_one_with_most_controls_first():
    lines = ed._old_evidence(
        {
            "SOC2": {"CC1.1": ago(400), "CC1.2": ago(10)},
            "HIPAA": {"a": ago(500), "b": ago(700), "c": ago(366)},
            "ISO27001": {"A.5.1": ago(20)},
        },
        NOW,
    )
    assert [(line.framework, line.controls, line.oldest_days) for line in lines] == [("HIPAA", 3, 700), ("SOC2", 1, 400)]
    assert ed._old_evidence({}, NOW) == []
    assert ed._old_evidence({"SOC2": {"CC1.1": ago(365)}}, NOW) == [], "exactly a year is not yet old"


def test_the_digest_recommends_fresh_evidence_and_carries_the_lines_and_says_nothing_when_all_is_fresh():
    inputs = ed.DigestInputs(
        tenant_id=uuid.uuid4(),
        period_start=NOW - timedelta(days=7),
        period_end=NOW,
        evidence_newest={"SOC2": {"CC1.1": ago(400), "CC1.2": ago(900)}},
    )
    digest = ed.build_digest_from_rows(inputs)
    assert [(line.framework, line.controls) for line in digest.old_evidence] == [("SOC2", 2)]
    rec = next(r for r in digest.recommendations if r.title == "Compliance evidence is more than a year old")
    assert rec.severity == "warning"
    assert rec.body == "2 controls rest on accepted evidence older than a year: SOC2 (2). Collect fresh evidence before the next audit."
    assert not any(r.title == "No significant deviations" for r in digest.recommendations)

    fresh = ed.build_digest_from_rows(
        ed.DigestInputs(
            tenant_id=uuid.uuid4(), period_start=NOW - timedelta(days=7), period_end=NOW, evidence_newest={"SOC2": {"CC1.1": ago(5)}}
        )
    )
    assert fresh.old_evidence == []
    assert not any("evidence" in r.title.lower() for r in fresh.recommendations)


def test_one_old_control_is_said_in_the_singular():
    digest = ed.build_digest_from_rows(
        ed.DigestInputs(
            tenant_id=uuid.uuid4(), period_start=NOW - timedelta(days=7), period_end=NOW, evidence_newest={"SOC2": {"CC1.1": ago(400)}}
        )
    )
    rec = next(r for r in digest.recommendations if "evidence" in r.title.lower())
    assert rec.body.startswith("1 control rests on accepted evidence")


class _BrokenDb:
    async def execute(self, *_a, **_k):
        raise RuntimeError("the table is gone")


@pytest.mark.asyncio
async def test_a_failed_read_gives_no_ages_and_does_not_raise():
    assert await ed._fetch_evidence_newest(_BrokenDb(), uuid.uuid4()) == {}


@needs_pg
@pytest.mark.asyncio
async def test_only_this_tenants_accepted_evidence_is_read_newest_per_control():
    tag = uuid.uuid4().hex[:8]
    mine, other = uuid.uuid4(), uuid.uuid4()
    real_now = datetime.now(UTC)
    engine = create_async_engine(PG_URL, poolclass=NullPool)

    async def add(conn, tenant, control, status, days_ago, framework="SOC2"):
        when = real_now - timedelta(days=days_ago)
        await conn.execute(
            text(
                "insert into aisoc_compliance_evidence (id, tenant_id, framework, control_id, evidence_kind, summary, raw_payload, collected_at, status, created_at) "
                "values (:i, :t, :fw, :c, 'policy', 'x', '{}'::jsonb, :w, :st, :w)"
            ),
            {"i": uuid.uuid4(), "t": tenant, "fw": framework, "c": control, "st": status, "w": when},
        )

    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for t in (mine, other):
                await conn.execute(
                    text("insert into tenants (id, name, slug) values (:i, 'x', :s)"), {"i": t, "s": f"oe-{tag}-{str(t)[:4]}"}
                )
            await add(conn, mine, "CC1.1", "accepted", 500)
            await add(conn, mine, "CC1.1", "accepted", 20)
            await add(conn, mine, "CC1.2", "accepted", 400)
            await add(conn, mine, "CC1.2", "pending", 1)
            await add(conn, mine, "CC1.3", "rejected", 900)
            await add(conn, mine, "A.5.1", "accepted", 600, framework="ISO27001")
            await add(conn, other, "CC1.4", "accepted", 2000)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await db.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            newest = await ed._fetch_evidence_newest(db, mine)
        assert set(newest) == {"SOC2", "ISO27001"}
        assert set(newest["SOC2"]) == {"CC1.1", "CC1.2"}, "never-accepted CC1.3 and another tenant's CC1.4 are not read"
        lines = ed._old_evidence(newest, real_now)
        assert [(line.framework, line.controls, line.oldest_days) for line in lines] == [("ISO27001", 1, 600), ("SOC2", 1, 400)]
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from aisoc_compliance_evidence where tenant_id in (:a, :b)"), {"a": mine, "b": other})
            await conn.execute(text("delete from tenants where id in (:a, :b)"), {"a": mine, "b": other})
        await engine.dispose()

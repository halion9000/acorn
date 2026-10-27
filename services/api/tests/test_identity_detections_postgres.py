"""The identity rules, end to end against a REAL Postgres: stored sign-ins and audits in, one alert per finding out, and a second run raises nothing.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.db.rls import set_rls_context
from app.models.signin import DirectoryAuditEvent, SigninEvent
from app.services.identity_detections import run_audit_detections, run_signin_detections
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")

NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture
async def world():
    tid = uuid.uuid4()
    tag = uuid.uuid4().hex[:10]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(
                text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"),
                {"i": tid, "n": f"idd-{tag}", "s": f"idd-{tag}"},
            )
        yield tid, engine
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for table in ("alerts", "signin_events", "directory_audit_events"):
                await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": tid})
            await conn.execute(text("delete from tenants where id = :t"), {"t": tid})
        await engine.dispose()


async def session(engine, tenant):
    db = async_sessionmaker(engine, expire_on_commit=False)()
    await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
    await set_rls_context(db, tenant)
    return db


def signin(tid, i, *, user="a@x.com", country="US", at=NOW, success=True):
    return SigninEvent(
        tenant_id=tid, source="cipp", source_id=f"s{i}-{uuid.uuid4().hex[:6]}", user_principal=user, ip_address="1.2.3.4", country=country, city="X", app="Outlook",
        success=success, interactive=True, mfa=True, occurred_at=at,
    )


def audit(tid, i, activity, *, target="u@x.com", at=NOW):
    return DirectoryAuditEvent(
        tenant_id=tid, source="cipp", source_id=f"a{i}-{uuid.uuid4().hex[:6]}", actor="admin@x.com", actor_is_app=False, activity=activity, category="UserManagement", success=True,
        target=target, target_type="User", sensitivity=1, occurred_at=at,
    )


async def alerts(engine, tid):
    db = await session(engine, tid)
    rows = (await db.execute(text("select title, severity, mitre_tactics, rule_id from alerts where tenant_id = :t order by title"), {"t": tid})).all()
    await db.close()
    return rows


@pytest.mark.asyncio
async def test_a_rare_country_and_impossible_travel_raise_one_alert_each_and_a_repeat_raises_none(world):
    tid, engine = world
    db = await session(engine, tid)
    history = [signin(tid, i, user=f"u{i % 5}@x.com", at=NOW - timedelta(days=2, minutes=i)) for i in range(60)]
    db.add_all(history)
    new = [signin(tid, 100, user="a@x.com", country="US", at=NOW - timedelta(minutes=30)), signin(tid, 101, user="a@x.com", country="RO", at=NOW - timedelta(minutes=5))]
    db.add_all(new)
    await db.flush()
    assert await run_signin_detections(db, tid, new, NOW) == 2
    assert await run_signin_detections(db, tid, new, NOW) == 0, "the same batch again raises nothing"
    await db.commit()
    await db.close()
    got = await alerts(engine, tid)
    assert [(r[0], r[1], r[2], r[3]) for r in got] == [
        ("Impossible travel - US to RO", "high", ["Initial Access"], "aisoc-id-impossible-travel"),
        ("Sign-in from an unusual country - RO", "medium", ["Initial Access"], "aisoc-id-rare-country"),
    ]


@pytest.mark.asyncio
async def test_a_thin_history_judges_no_country_and_the_audit_rules_raise_mass_deletion_and_a_role_change(world):
    tid, engine = world
    db = await session(engine, tid)
    thin = [signin(tid, 1, country="US", at=NOW - timedelta(days=1)), signin(tid, 2, country="RO", at=NOW)]
    db.add_all(thin)
    audits = [audit(tid, i, "Delete user", at=NOW - timedelta(minutes=i)) for i in range(10)] + [audit(tid, 50, "Add member to role", target="boss@x.com")]
    db.add_all(audits)
    await db.flush()
    assert await run_signin_detections(db, tid, [thin[1]], NOW) == 0
    assert await run_audit_detections(db, tid, audits, NOW) == 2
    assert await run_audit_detections(db, tid, audits, NOW) == 0
    await db.commit()
    await db.close()
    assert sorted(r[3] for r in await alerts(engine, tid)) == ["aisoc-id-mass-deletion", "aisoc-id-role-change"]

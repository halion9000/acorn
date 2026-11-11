"""The administrator rules end to end against a REAL Postgres: the multi-factor snapshot and the stored sign-in history in, one alert per finding out, a second run raising nothing.

``run_mfa_detections`` catches every error and returns 0 (it must never break the snapshot that triggered it), so a broken query would look exactly like "nothing to report". Only a real database run shows the
queries work: this checks the unused-administrator rule (a long-quiet admin, a recently active one, a guest, a disabled one, and a history too short to judge) and the registered-but-not-required rule.
Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.db.rls import set_rls_context
from app.models.signin import IdentityMfaUser, SigninEvent
from app.services.identity_detections import STALE_ADMIN_DAYS, run_mfa_detections
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")

NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture
async def tenant():
    tid = uuid.uuid4()
    tag = uuid.uuid4().hex[:10]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(
                text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"),
                {"i": tid, "n": f"adm-{tag}", "s": f"adm-{tag}"},
            )
        yield tid, engine
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for table in ("alerts", "signin_events", "identity_mfa_users"):
                await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": tid})
            await conn.execute(text("delete from tenants where id = :t"), {"t": tid})
        await engine.dispose()


async def session(engine, tenant_id):
    db = async_sessionmaker(engine, expire_on_commit=False)()
    await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
    await set_rls_context(db, tenant_id)
    return db


def person(tid, upn, *, admin=True, enabled=True, user_type="Member", registered=True, required=True):
    return IdentityMfaUser(
        tenant_id=tid,
        source="cipp",
        user_id=upn,
        upn=upn,
        enabled=enabled,
        user_type=user_type,
        admin=admin,
        licensed=True,
        registered=registered,
        capable=registered,
        per_user="enforced" if required else None,
        ca_enforced=False,
        security_defaults=False,
        snapshot_id=uuid.uuid4(),
    )


def signin(tid, upn, days_ago, success=True):
    return SigninEvent(
        tenant_id=tid,
        source="cipp",
        source_id=f"{upn}-{days_ago}-{uuid.uuid4().hex[:6]}",
        user_principal=upn,
        ip_address="1.2.3.4",
        country="US",
        city="X",
        app="Portal",
        success=success,
        interactive=True,
        mfa=True,
        occurred_at=NOW - timedelta(days=days_ago),
    )


async def titles(engine, tid):
    db = await session(engine, tid)
    rows = (await db.execute(text("select title, severity, rule_id from alerts where tenant_id = :t order by title"), {"t": tid})).all()
    await db.close()
    return rows


@pytest.mark.asyncio
async def test_only_the_long_quiet_enabled_member_administrator_is_raised_and_a_repeat_raises_nothing(tenant):
    tid, engine = tenant
    db = await session(engine, tid)
    db.add_all(
        [
            person(tid, "quiet@x.com"),
            person(tid, "active@x.com"),
            person(tid, "guest@x.com", user_type="Guest"),
            person(tid, "off@x.com", enabled=False),
            person(tid, "plain@x.com", admin=False),
            signin(tid, "quiet@x.com", STALE_ADMIN_DAYS + 20),
            signin(tid, "active@x.com", 2),
            signin(tid, "active@x.com", STALE_ADMIN_DAYS + 40),  # the history reaches back far enough to judge
        ]
    )
    await db.commit()
    assert await run_mfa_detections(db, tid, NOW) == 1
    await db.commit()
    assert await run_mfa_detections(db, tid, NOW) == 0, "the same finding is not raised twice in the quarter"
    await db.close()
    rows = await titles(engine, tid)
    assert [r[2] for r in rows] == ["aisoc-id-admin-stale"] and "quiet@x.com" in rows[0][0] and rows[0][1] == "medium"


@pytest.mark.asyncio
async def test_a_history_too_short_to_judge_raises_nothing(tenant):
    tid, engine = tenant
    db = await session(engine, tid)
    db.add_all([person(tid, "quiet@x.com"), signin(tid, "someone@x.com", 5)])  # only five days of history: "no sign-in seen" proves nothing
    await db.commit()
    assert await run_mfa_detections(db, tid, NOW) == 0
    await db.commit()
    await db.close()
    assert await titles(engine, tid) == []


@pytest.mark.asyncio
async def test_registered_but_not_required_is_a_medium_alert_and_missing_entirely_is_high(tenant):
    tid, engine = tenant
    db = await session(engine, tid)
    db.add_all([person(tid, "reg@x.com", registered=True, required=False), person(tid, "none@x.com", registered=False, required=False)])
    await db.commit()
    assert await run_mfa_detections(db, tid, NOW) == 2
    await db.commit()
    await db.close()
    by_person = {("reg" if "reg@" in r[0] else "none"): r[1] for r in await titles(engine, tid)}
    assert by_person == {"reg": "medium", "none": "high"}

"""A person's own sign-in history: how each sign-in is worded, and on a REAL Postgres that a sign-in is recorded with its method and address, that the history is the caller's own only, newest
first and capped, and that a failure to record never stops the sign-in. The Postgres tests opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.auth import my_signins
from app.services import signin_history as sh
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
needs_pg = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


def test_the_method_is_a_plain_word_and_an_entry_that_does_not_say_is_unknown():
    assert sh.method_of("auth:login", {"method": "password"}) == "Password"
    assert sh.method_of("auth:login", {"method": "passkey"}) == "Passkey"
    for action in sh.MICROSOFT_ACTIONS:
        assert sh.method_of(action, {"provider": "microsoft"}) == "Microsoft"
    assert sh.method_of("auth:login", None) == "Unknown"
    assert sh.method_of("auth:login", {"method": "carrier pigeon"}) == "Unknown"
    assert sh.method_of("auth:login", "not a dict") == "Unknown"


def test_rows_keep_the_newest_twenty_with_when_how_and_where():
    at = datetime(2026, 11, 11, 9, 30, tzinfo=UTC)
    entries = [
        {"created_at": at, "action": "auth:login", "changes": {"method": "password"}, "actor_ip": f"203.0.113.{i}"} for i in range(25)
    ]
    out = sh.rows(entries)
    assert len(out) == sh.SHOWN == 20
    assert out[0] == {"at": "2026-11-11T09:30:00+00:00", "method": "Password", "ip": "203.0.113.0"}
    assert sh.rows([{"created_at": None, "action": "auth:sso_login", "changes": None, "actor_ip": None}]) == [
        {"at": None, "method": "Microsoft", "ip": None}
    ]


class _BrokenSession:
    def begin_nested(self):
        raise RuntimeError("the database went away")


@pytest.mark.asyncio
async def test_a_failure_to_record_is_swallowed_and_reported_as_not_written():
    written = await sh.record(_BrokenSession(), user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), label="x", method="password")
    assert written is False


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


def fake_request(ip):
    return SimpleNamespace(client=SimpleNamespace(host=ip), headers={"user-agent": "pytest"}, scope={"type": "http"})


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    tenant, other_tenant = uuid.uuid4(), uuid.uuid4()
    me, colleague, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (tenant, other_tenant):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"si-{t.hex[:10]}"})
        for uid, tid in ((me, tenant), (colleague, tenant), (stranger, other_tenant)):
            tag = uid.hex[:10]
            await s.execute(
                text(
                    "insert into users (id, tenant_id, email, username, account_name, hashed_password, role, is_active) "
                    "values (:i, :t, :e, :u, :a, 'x', 'analyst', true)"
                ),
                {"i": uid, "t": tid, "e": f"{tag}@x.test", "u": tag, "a": f"s{tag}"},
            )
        await s.commit()
        s.info.update(tenant=tenant, other=other_tenant, me=me, colleague=colleague, stranger=stranger)
        yield s
        await s.rollback()
        await off(s)
        await s.execute(text("set local session_replication_role = replica"))  # audit rows refuse deletion; for this clean-up only
        await s.execute(text("delete from audit_log where tenant_id in (:a, :b)"), {"a": tenant, "b": other_tenant})
        await s.execute(text("delete from users where id in (:a, :b, :c)"), {"a": me, "b": colleague, "c": stranger})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": tenant, "b": other_tenant})
        await s.commit()
    await engine.dispose()


@needs_pg
@pytest.mark.asyncio
async def test_a_sign_in_is_recorded_and_the_history_is_the_callers_own_newest_first(world):
    s = world
    info = s.info
    await off(s)
    assert (
        await sh.record(s, user_id=info["me"], tenant_id=info["tenant"], label="me", method="password", request=fake_request("203.0.113.7"))
        is True
    )
    assert await sh.record(s, user_id=info["me"], tenant_id=info["tenant"], label="me", method="passkey") is True
    await sh.record(s, user_id=info["colleague"], tenant_id=info["tenant"], label="colleague", method="password")
    await sh.record(s, user_id=info["stranger"], tenant_id=info["other"], label="stranger", method="password")
    # A Microsoft sign-in (written by the Microsoft route) and an entry that is not a sign-in at all.
    for action in ("auth:sso_login", "role:updated"):
        await s.execute(
            text(
                "insert into audit_log (id, tenant_id, actor_id, action, resource, changes, created_at) "
                "values (gen_random_uuid(), :t, :u, :a, 'user', '{}'::jsonb, now() + interval '1 minute')"
            ),
            {"t": info["tenant"], "u": info["me"], "a": action},
        )
    await s.commit()
    await off(s)
    out = await my_signins(SimpleNamespace(tenant_id=info["tenant"], user_id=info["me"]), s)
    assert [r.method for r in out] == ["Microsoft", "Passkey", "Password"], "mine only, newest first, and not the role change"
    assert out[2].ip == "203.0.113.7" and out[1].ip is None
    assert all(r.at for r in out)


@needs_pg
@pytest.mark.asyncio
async def test_someone_with_no_sign_ins_recorded_gets_an_empty_list(world):
    s = world
    await off(s)
    assert await my_signins(SimpleNamespace(tenant_id=s.info["tenant"], user_id=s.info["colleague"]), s) == []

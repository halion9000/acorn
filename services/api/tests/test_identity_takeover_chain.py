"""Likely account takeover: an entry sign and a foothold sign on one person within a day are ONE critical alert."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.models.signin import DirectoryAuditEvent, SigninEvent
from app.services.identity_detections import ChainSign, detect_takeover_chain, run_audit_detections, run_signin_detections

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def sign(rule, who="a@x.com", minutes=0, alert="x"):
    return ChainSign(rule_id=rule, title=rule, at=T0 + timedelta(minutes=minutes), user=who, alert_id=alert + rule)


def test_an_entry_sign_then_a_foothold_within_a_day_is_one_critical_finding():
    found = detect_takeover_chain([sign("aisoc-id-guessed-password"), sign("aisoc-id-admin-security-info", minutes=90), sign("aisoc-id-app-credentials", minutes=120)])
    assert len(found) == 1
    f = found[0]
    assert (f.severity, f.rule_id, f.title) == ("critical", "aisoc-id-takeover-chain", "Likely account takeover - a@x.com")
    assert ("Alerts joined", "3") in f.fields and f.users == ["a@x.com"]
    assert "password guessed" in f.summary and "sign-in methods changed" in f.summary


def test_the_order_the_window_and_the_person_all_matter():
    # The foothold BEFORE the entry is not a takeover chain (an administrator doing admin work, then signing in from abroad).
    assert detect_takeover_chain([sign("aisoc-id-app-consent"), sign("aisoc-id-rare-country", minutes=10)]) == []
    # More than a day apart.
    assert detect_takeover_chain([sign("aisoc-id-rare-country"), sign("aisoc-id-role-change", minutes=25 * 60)]) == []
    # Two different people.
    assert detect_takeover_chain([sign("aisoc-id-rare-country"), sign("aisoc-id-role-change", who="b@x.com", minutes=5)]) == []
    # An entry sign alone, a foothold alone, and kinds that are neither.
    assert detect_takeover_chain([sign("aisoc-id-rare-country")]) == []
    assert detect_takeover_chain([sign("aisoc-id-role-change")]) == []
    assert detect_takeover_chain([sign("aisoc-id-legacy-protocol"), sign("aisoc-id-mass-deletion", minutes=5)]) == []


def test_names_match_without_regard_to_case_and_the_finding_has_one_key_per_person_and_day():
    a = detect_takeover_chain([sign("aisoc-id-device-code", who="A@X.com"), sign("aisoc-id-ca-policy-change", who="a@x.com", minutes=5)])
    b = detect_takeover_chain([sign("aisoc-id-device-code", who="a@x.com"), sign("aisoc-id-bec-findings", who="a@x.com", minutes=50)])
    assert len(a) == 1 and len(b) == 1 and a[0].key == b[0].key


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")


@pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")
@pytest.mark.asyncio
async def test_against_postgres_the_second_alert_of_a_chain_raises_one_critical_alert_once():
    from app.db.rls import set_rls_context
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    now = datetime.now(UTC).replace(microsecond=0)
    tid, tag = uuid.uuid4(), uuid.uuid4().hex[:10]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as c:
            await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await c.execute(text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"), {"i": tid, "n": f"chain-{tag}", "s": f"chain-{tag}"})
        db = async_sessionmaker(engine, expire_on_commit=False)()
        await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
        await set_rls_context(db, tid)

        def si(i, **kw):
            return SigninEvent(tenant_id=tid, source="cipp", source_id=f"s{i}-{tag}", user_principal="a@x.com", ip_address=kw.get("ip", "9.9.9.9"), country="US", city="X", app="Outlook",
                               success=kw["success"], error_code=kw.get("code"), interactive=True, mfa=True, occurred_at=now - timedelta(minutes=kw["m"]))

        rows = [si(i, success=False, code=50126, m=40 - i, ip="1.1.1.1") for i in range(6)] + [si(9, success=True, m=20, ip="2.2.2.2")]
        db.add_all(rows)
        await db.flush()
        assert await run_signin_detections(db, tid, rows, now) == 1  # the guessed password alone: no chain yet

        change = DirectoryAuditEvent(tenant_id=tid, source="cipp", source_id=f"a1-{tag}", activity="Admin deleted security info", actor="a@x.com", actor_is_app=False, target="a@x.com", target_type="User", category="UserManagement", success=True, actor_ip="2.2.2.2", occurred_at=now - timedelta(minutes=5))
        db.add(change)
        await db.flush()
        assert await run_audit_detections(db, tid, [change], now) == 2  # the foothold alert and the chain
        assert await run_audit_detections(db, tid, [change], now) == 0
        await db.commit()
        await db.close()
        async with engine.begin() as c:
            await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            got = (await c.execute(text("select title, severity from alerts where tenant_id = :t and rule_id = 'aisoc-id-takeover-chain'"), {"t": tid})).all()
        assert [tuple(r) for r in got] == [("Likely account takeover - a@x.com", "critical")]
    finally:
        async with engine.begin() as c:
            await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for table in ("alerts", "signin_events", "directory_audit_events"):
                await c.execute(text(f"delete from {table} where tenant_id = :t"), {"t": tid})
            await c.execute(text("delete from tenants where id = :t"), {"t": tid})
        await engine.dispose()

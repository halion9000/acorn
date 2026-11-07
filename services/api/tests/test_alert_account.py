"""The Microsoft 365 picture on an alert: only e-mail addresses are looked up, and the summary counts what the sign-ins really say."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.alert_account import alert_account, emails_of, summarise
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

NOW = datetime.now(UTC)


def row(minutes_ago, success=True, country="US", app="Outlook", mfa=True, risk=None, interactive=True):
    return SimpleNamespace(
        occurred_at=NOW - timedelta(minutes=minutes_ago),
        success=success,
        country=country,
        city=None,
        app=app,
        ip_address="1.2.3.4",
        mfa=mfa,
        risk=risk,
        interactive=interactive,
    )


def test_only_email_addresses_are_looked_up_once_each_and_at_most_three():
    names = ["Alice@Corp.com", "alice@corp.com", "DOMAIN\bob", "carol smith@x.com", "d@x.com", "e@x.com", "f@x.com", 7, ""]
    assert emails_of(names) == ["alice@corp.com", "d@x.com", "e@x.com"]
    assert emails_of(None) == [] and emails_of("a@b.c") == []


def test_the_summary_counts_failures_risky_sign_ins_and_successes_without_a_second_factor():
    rows = [
        row(5, country="RU", mfa=False, risk="high"),
        row(30, success=False, country="RU"),
        row(60, country="US"),
        row(90, country="US", app="Teams", mfa=False, interactive=False),
    ]
    p = summarise("a@x.com", rows)
    assert (p.signins, p.failed, p.risky, p.without_mfa) == (4, 1, 1, 1), "a non-interactive sign-in without MFA is not counted"
    assert dict(p.countries) == {"RU": 2, "US": 2}
    assert p.last_success == rows[0].occurred_at
    assert len(p.recent) == 4 and p.recent[0].country == "RU"


def test_a_person_with_only_failures_has_no_last_success():
    assert summarise("a@x.com", [row(5, success=False)]).last_success is None


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")


@pytest.mark.asyncio
@pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")
async def test_the_alert_shows_the_named_persons_recent_sign_ins_and_account_and_never_anothers():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    tenant, other, alert = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        for t in (tenant, other):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"ac-{t.hex[:10]}"})
        await s.execute(
            text(
                "insert into alerts (id, tenant_id, title, severity, status, priority, affected_users, raw_event, created_at, updated_at) "
                "values (:i, :t, 'x', 'low', 'new', 50, cast(:u as jsonb), '{}'::jsonb, now(), now())"
            ),
            {"i": alert, "t": tenant, "u": json.dumps(["Alice@Corp.com", "ghost@corp.com"])},
        )

        async def signin(t, who, minutes_ago, ok=True):
            await s.execute(
                text(
                    "insert into signin_events (id, tenant_id, source, source_id, user_principal, country, app, success, interactive, mfa, occurred_at, received_at) "
                    "values (gen_random_uuid(), :t, 'cipp', :sid, :u, 'US', 'Outlook', :ok, true, true, now() - make_interval(mins => :m), now())"
                ),
                {"t": t, "sid": str(uuid.uuid4()), "u": who, "ok": ok, "m": minutes_ago},
            )

        await signin(tenant, "alice@corp.com", 10)
        await signin(tenant, "ALICE@corp.com", 20, ok=False)
        await signin(tenant, "alice@corp.com", 60 * 24 * 10)  # outside the window
        await signin(other, "ghost@corp.com", 5)  # another organization's, never shown
        await s.execute(
            text(
                "insert into identity_mfa_users (tenant_id, source, user_id, upn, enabled, admin, licensed, registered, capable, ca_enforced, security_defaults, methods, snapshot_id) "
                "values (:t, 'cipp', 'u1', 'Alice@Corp.com', true, true, true, true, true, false, false, 'Authenticator', gen_random_uuid())"
            ),
            {"t": tenant},
        )
        await s.commit()
        try:
            out = await alert_account(alert, SimpleNamespace(tenant_id=tenant), s)
        finally:
            await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for t in (tenant, other):
                await s.execute(text("delete from signin_events where tenant_id = :t"), {"t": t})
                await s.execute(text("delete from identity_mfa_users where tenant_id = :t"), {"t": t})
                await s.execute(text("delete from alerts where tenant_id = :t"), {"t": t})
                await s.execute(text("delete from tenants where id = :t"), {"t": t})
            await s.commit()
    await engine.dispose()
    alice, ghost = out.people
    assert (alice.user, alice.found, alice.signins, alice.failed) == (
        "alice@corp.com",
        True,
        2,
        1,
    ), "case does not matter; the 10-day-old one is outside the window"
    assert alice.account is not None and alice.account.admin and alice.account.methods == "Authenticator"
    assert (ghost.user, ghost.found, ghost.signins) == ("ghost@corp.com", False, 0), "another organization's sign-ins are not this one's"

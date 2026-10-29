"""CORE's report about its CIPP actions on a REAL Postgres, as the application's own (row-level-security) role: kept per organization, replaced by the next report, shown with client names from the mapping.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database) and AISOC_TEST_PG_APP_URL (the application role on it).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import cipp_actions as ep
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)

NOW = datetime.now(UTC)


def report(**over):
    base = {
        "live": False,
        "all_clients": False,
        "clients": ["cipp-1"],
        "protected_users": 2,
        "protected_domains": 1,
        "max_per_hour": 5,
        "actions": [{"action": "revoke_sessions", "risk": "low", "reversible": True, "summary": "Sign the person out everywhere"}],
        "audit": [
            {
                "at": (NOW - timedelta(minutes=5)).isoformat(),
                "action": "revoke_sessions",
                "client_id": "cipp-1",
                "user": "amy@acme.com",
                "actor": "playbook",
                "reason": "alert a1",
                "result": "dry_run",
                "would_refuse": None,
            },
            {
                "at": (NOW - timedelta(minutes=9)).isoformat(),
                "action": "disable_user",
                "client_id": "cipp-2",
                "result": "refused",
                "code": "client_not_opted_in",
            },
        ],
    }
    return ep.ActionsReport(**{**base, **over})


@pytest.fixture
async def world(monkeypatch):
    parent, other = uuid.uuid4(), uuid.uuid4()
    tag = parent.hex[:8]
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    app = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for tid, name in ((parent, f"Parent {tag}"), (other, f"Other {tag}")):
                await conn.execute(
                    text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :n, 'parent')"), {"i": tid, "n": name}
                )
            await conn.execute(
                text(
                    "insert into client_aliases (tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name) values (:t, 'cipp', 'cipp-1', 'Pirkey Barber', 'pirkey barber')"
                ),
                {"t": parent},
            )

        owner_of = {"tok-parent": parent, "tok-other": other}

        async def verify(db, token):
            return owner_of[token]

        monkeypatch.setattr(ep, "_verify_core_feed_token", verify)
        yield app, SimpleNamespace(parent=parent, other=other)
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from cipp_actions_reports where tenant_id in (:a, :b)"), {"a": parent, "b": other})
            await conn.execute(text("delete from client_aliases where tenant_id in (:a, :b)"), {"a": parent, "b": other})
            await conn.execute(text("delete from tenants where id in (:a, :b)"), {"a": parent, "b": other})
        await owner.dispose()
        await app.dispose()


async def send(app, token, body):
    async with AsyncSession(app) as db:
        return await ep.report_core_feed_cipp_actions(token, body, db)


async def view(app, tenant):
    async with AsyncSession(app) as db:
        from app.db.rls_sessions import adopt_tenant

        await adopt_tenant(db, tenant)
        return await ep.cipp_actions_view(SimpleNamespace(tenant_id=tenant), db)


@pytest.mark.asyncio
async def test_nothing_is_shown_until_core_has_reported(world):
    app, w = world
    got = await view(app, w.parent)
    assert (got.report, got.received_at, got.client_names) == (None, None, {})


@pytest.mark.asyncio
async def test_a_report_is_kept_shown_with_client_names_and_replaced_by_the_next_one(world):
    app, w = world
    await send(app, "tok-parent", report())
    got = await view(app, w.parent)
    assert got.report is not None and got.report.live is False and got.report.max_per_hour == 5
    assert got.report.audit[0].result == "dry_run" and got.report.audit[1].code == "client_not_opted_in"
    assert got.client_names == {"cipp-1": "Pirkey Barber"}, "only ids the client mapping knows get a name"
    first_at = got.received_at
    await send(app, "tok-parent", report(live=True, clients=["cipp-1", "cipp-2"], audit=[]))
    again = await view(app, w.parent)
    assert again.report.live is True and again.report.clients == ["cipp-1", "cipp-2"] and again.report.audit == []
    assert again.received_at >= first_at


@pytest.mark.asyncio
async def test_one_organizations_report_is_never_shown_to_another(world):
    app, w = world
    await send(app, "tok-parent", report())
    assert (await view(app, w.other)).report is None
    await send(app, "tok-other", report(live=True, clients=[]))
    assert (await view(app, w.parent)).report.live is False
    assert (await view(app, w.other)).report.live is True


def test_a_report_with_an_unknown_outcome_or_risk_or_too_many_lines_is_refused():
    with pytest.raises(ValidationError):
        report(audit=[{"at": NOW.isoformat(), "action": "x", "client_id": "c", "result": "exploded"}])
    with pytest.raises(ValidationError):
        report(actions=[{"action": "x", "risk": "extreme", "reversible": True, "summary": "s"}])
    with pytest.raises(ValidationError):
        report(audit=[{"at": NOW.isoformat(), "action": "x", "client_id": "c", "result": "refused"}] * (ep.MAX_AUDIT + 1))
    with pytest.raises(ValidationError):
        report(max_per_hour=0)

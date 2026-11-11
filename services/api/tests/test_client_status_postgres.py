"""The client status page on a REAL Postgres: a link is found by the hash of its secret, only while live and reviewed, and the page carries only the client-safe summary.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.api.v1.endpoints.client_status import public_status
from app.models.client_status_link import ClientStatusLink
from app.services import client_status as cs
from fastapi import HTTPException, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
NOW = datetime.now(UTC)
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    owner, client = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        await s.execute(text("insert into tenants (id, name, slug) values (:t, 'owner', :s)"), {"t": owner, "s": f"own-{owner.hex[:10]}"})
        await s.execute(
            text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, 'Acme Test', :s, :p)"),
            {"t": client, "s": f"cl-{client.hex[:10]}", "p": owner},
        )
        await s.commit()
        s.info.update(owner=owner, client=client)
        yield s
        await off(s)
        await s.execute(text("delete from client_status_links where tenant_id = :o"), {"o": owner})
        await s.execute(text("delete from tenants where parent_tenant_id = :o"), {"o": owner})
        await s.execute(text("delete from tenants where id = :o"), {"o": owner})
        await s.commit()
    await engine.dispose()


def link(s, token, **over):
    base = {
        "tenant_id": s.info["owner"],
        "client_id": s.info["client"],
        "token_hash": cs.hash_token(token),
        "expires_at": NOW + timedelta(days=30),
        "reviewed_at": NOW,
    }
    return ClientStatusLink(**{**base, **over})


async def test_a_live_reviewed_link_returns_the_safe_page_and_every_other_state_is_the_same_404(world):
    s = world
    live, unreviewed, revoked, expired = (cs.new_token() for _ in range(4))
    s.add_all(
        [
            link(s, live),
            link(s, unreviewed, reviewed_at=None),
            link(s, revoked, revoked_at=NOW),
            link(s, expired, expires_at=NOW - timedelta(days=1)),
        ]
    )
    await s.commit()
    await off(s)
    page = await public_status(live, Response(), s)
    assert page["client_name"] == "Acme Test"
    assert set(page) == {"client_name", "generated_at", "devices", "people", "alerts", "tools", "copy"}
    assert page["devices"]["total"] == 0 and page["people"] is None
    for bad in (unreviewed, revoked, expired, cs.new_token(), "short"):
        await off(s)
        with pytest.raises(HTTPException) as err:
            await public_status(bad, Response(), s)
        assert err.value.status_code == 404 and err.value.detail == "This link is not available."


async def test_the_last_opened_time_is_recorded_and_only_a_hash_is_stored(world):
    s = world
    token = cs.new_token()
    s.add(link(s, token))
    await s.commit()
    await off(s)
    await public_status(token, Response(), s)
    await off(s)
    row = (
        await s.execute(text("select token_hash, last_opened_at from client_status_links where tenant_id = :o"), {"o": s.info["owner"]})
    ).one()
    assert row[0] == cs.hash_token(token) and token not in row[0]
    assert row[1] is not None


async def test_only_a_revoked_or_expired_link_can_be_deleted_and_a_live_one_is_refused(world, monkeypatch):
    from types import SimpleNamespace

    from app.api.v1.endpoints import client_status as ep

    async def no_audit(**_kw):
        return None

    monkeypatch.setattr(ep, "emit_audit", no_audit)
    s = world
    live, revoked, expired = (cs.new_token() for _ in range(3))
    rows = [link(s, live), link(s, revoked, revoked_at=NOW), link(s, expired, expires_at=NOW - timedelta(days=1))]
    s.add_all(rows)
    await s.commit()
    user = SimpleNamespace(tenant_id=s.info["owner"], user_id=None)
    await off(s)
    with pytest.raises(HTTPException) as err:
        await ep.delete_link(rows[0].id, None, user, s)
    assert err.value.status_code == 409
    for gone in (rows[1], rows[2]):
        await off(s)
        assert (await ep.delete_link(gone.id, None, user, s)).status_code == 204
    await off(s)
    left = (await s.execute(text("select count(*) from client_status_links where tenant_id = :o"), {"o": s.info["owner"]})).scalar_one()
    assert left == 1, "only the live link remains"
    await off(s)
    with pytest.raises(HTTPException) as missing:
        await ep.delete_link(uuid.uuid4(), None, user, s)
    assert missing.value.status_code == 404

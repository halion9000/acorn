"""Web push for a critical alert on a REAL Postgres: a new critical alert of the organization's own clients is pushed once, readable by the subscribed browser, a gone browser is dropped, and another
organization's alert is never pushed. Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database with migration 228 applied)."""

import json
import os
import uuid
from types import SimpleNamespace

import pytest
from app.services import push_notify as pn
from app.services import web_push as wp
from app.workers import push_alert_worker as w
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")]


class FakePushService:
    def __init__(self, status=201):
        self.status = status
        self.bodies: list[bytes] = []

    async def post(self, endpoint, content=None, headers=None, timeout=None):
        assert headers["Content-Encoding"] == "aes128gcm" and headers["Authorization"].startswith("vapid t=")
        self.bodies.append(content)
        return SimpleNamespace(status_code=self.status)


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    owner, acme, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    browser = ec.generate_private_key(ec.SECP256R1())
    auth = wp.b64u(b"0123456789abcdef")
    async with factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await s.execute(text("insert into tenants (id, name, slug) values (:i, 'owner', :s)"), {"i": owner, "s": f"po-{tag}"})
        await s.execute(text("insert into tenants (id, name, slug, parent_tenant_id) values (:i, 'Acme', :s, :p)"), {"i": acme, "s": f"pa-{tag}", "p": owner})
        await s.execute(text("insert into tenants (id, name, slug) values (:i, 'Stranger', :s)"), {"i": stranger, "s": f"ps-{tag}"})
        await pn.ensure_key(s, owner)
        await s.execute(
            text("insert into push_subscriptions (id, tenant_id, user_id, endpoint, p256dh, auth) values (gen_random_uuid(), :t, gen_random_uuid(), 'https://push.example.net/abc', :p, :a)"),
            {"t": owner, "p": wp.b64u(wp._public_bytes(browser)), "a": auth},
        )
        await s.commit()
    yield SimpleNamespace(factory=factory, owner=owner, acme=acme, stranger=stranger, browser=browser, auth=auth)
    async with factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        ids = [owner, acme, stranger]
        for table in ("alerts", "push_subscriptions", "push_keys"):
            await s.execute(text(f"delete from {table} where tenant_id = any(cast(:t as uuid[]))"), {"t": [str(i) for i in ids]})
        await s.execute(text("delete from tenants where parent_tenant_id = :o"), {"o": owner})
        await s.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [str(i) for i in (owner, stranger)]})
        await s.commit()
    await engine.dispose()


async def alert(world, tenant, severity, title):
    async with world.factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await s.execute(
            text(
                "insert into alerts (id, tenant_id, title, severity, status, priority, affected_hosts, affected_users, created_at, updated_at) "
                "values (gen_random_uuid(), :t, :title, :sev, 'new', 50, cast('[]' as jsonb), cast('[]' as jsonb), now() + interval '1 second', now())"
            ),
            {"t": tenant, "title": title, "sev": severity},
        )
        await s.commit()


async def subscriptions(world):
    async with world.factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        return (await s.execute(text("select count(*) from push_subscriptions where tenant_id = :t"), {"t": world.owner})).scalar_one()


async def test_a_new_critical_alert_of_a_client_is_pushed_once_and_only_to_its_own_organization(world):
    await alert(world, world.acme, "critical", "Ransomware behaviour on PC-1")
    await alert(world, world.acme, "high", "A high one")
    await alert(world, world.stranger, "critical", "Someone else's")
    service = FakePushService()
    out = await w.push_once(factory=world.factory, client=service)
    assert out == {"pushed": 1, "failed": 0}
    assert len(service.bodies) == 1
    message = json.loads(wp.decrypt_payload(service.bodies[0], world.browser, world.auth))
    assert message["title"] == "Critical alert: Acme" and message["body"] == "Ransomware behaviour on PC-1"
    again = await w.push_once(factory=world.factory, client=service)
    assert again == {"pushed": 0, "failed": 0} and len(service.bodies) == 1, "the same alert is not pushed twice"


async def test_a_browser_the_push_service_has_forgotten_is_dropped(world):
    await alert(world, world.acme, "critical", "x")
    await w.push_once(factory=world.factory, client=FakePushService(status=410))
    assert await subscriptions(world) == 0


async def test_a_push_service_that_errors_keeps_the_subscription(world):
    await alert(world, world.acme, "critical", "x")
    await w.push_once(factory=world.factory, client=FakePushService(status=500))
    assert await subscriptions(world) == 1

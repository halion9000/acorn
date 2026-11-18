"""The fleet reports on a REAL Postgres (AISOC_TEST_PG_URL, a disposable, fully migrated database): Huntress agent versions and Auvik firmware across the organization's own clients, and nobody else's."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import device_reports as ep
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    owner, acme, birch, stranger = (uuid.uuid4() for _ in range(4))
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t, name, parent in ((owner, "Owner", None), (acme, "Acme Dental", owner), (birch, "Birch Law", owner), (stranger, "Stranger", None)):
            await s.execute(text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, :n, :s, :p)"), {"t": t, "n": name, "s": f"dr-{t.hex[:10]}", "p": parent})

        async def device(tenant, host, vendor, details, maker=None, model=None):
            did = uuid.uuid4()
            await s.execute(text("insert into devices (id, tenant_id, hostname, manufacturer, model, last_seen, first_seen, created_at, updated_at) values (:i, :t, :h, :ma, :mo, now(), now(), now(), now())"), {"i": did, "t": tenant, "h": host, "ma": maker, "mo": model})
            await s.execute(
                text("insert into device_sources (id, tenant_id, device_id, vendor, external_id, name, details, last_seen, created_at) values (gen_random_uuid(), :t, :d, :v, :e, :n, cast(:x as jsonb), now(), now())"),
                {"t": tenant, "d": did, "v": vendor, "e": f"{vendor}-{host}", "n": host, "x": __import__("json").dumps(details)},
            )

        w = SimpleNamespace(owner=owner, acme=acme, birch=birch, device=device, s=s, user=SimpleNamespace(tenant_id=owner, user_id=None), stranger=stranger)
        yield w
        await off(s)
        await s.rollback()
        await off(s)
        for table in ("device_sources", "devices"):
            await s.execute(text(f"delete from {table} where tenant_id = any(:ids)"), {"ids": [owner, acme, birch, stranger]})
        await s.execute(text("delete from tenants where id = any(:ids)"), {"ids": [acme, birch, stranger, owner]})
        await s.commit()
    await engine.dispose()


async def test_huntress_versions_cover_the_organizations_clients_and_mark_agents_three_or_more_releases_behind(world):
    w = world
    for host, tenant, ver in (("a", w.acme, "0.14.10"), ("b", w.acme, "0.14.9"), ("c", w.birch, "0.14.8"), ("d", w.birch, "0.14.7"), ("e", w.stranger, "9.9.9")):
        await w.device(tenant, host, "huntress", {"agent_version": ver})
    await w.s.commit()
    await off(w.s)
    out = await ep.huntress_versions(w.user, w.s, None)
    assert out["newest"] == "0.14.10" and out["agents"] == 4, "another organization's agent is not counted"
    assert [(o["client"], o["hostname"], o["releases_behind"]) for o in out["old"]] == [("Birch Law", "d", 3)]
    await off(w.s)
    one = await ep.huntress_versions(w.user, w.s, w.acme)
    assert one["agents"] == 2 and one["old"] == [], "one client only when asked for"


async def test_network_firmware_behind_is_found_per_make_and_model_across_clients(world):
    w = world
    await w.device(w.acme, "sw1", "auvik", {"firmware_version": "17.9.4", "device_type": "switch"}, "Cisco", "C9200")
    await w.device(w.birch, "sw2", "auvik", {"firmware_version": "17.12.1", "device_type": "switch"}, "Cisco", "C9200")
    await w.device(w.acme, "fw1", "auvik", {"firmware_version": "9.1", "device_type": "firewall"}, "Fortinet", "60F")
    await w.s.commit()
    await off(w.s)
    out = await ep.network_firmware(w.user, w.s, None)
    assert [(d["client"], d["hostname"], d["firmware"], d["newest"]) for d in out["devices"]] == [("Acme Dental", "sw1", "17.9.4", "17.12.1")]
    assert [(m["model"], m["behind"]) for m in out["models"]] == [("C9200", 1)]

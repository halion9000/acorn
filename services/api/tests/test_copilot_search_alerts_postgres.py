"""The Copilot's alert search reads the tenant AND its clients, filters by severity, age and openness, and ranks worst first, against a REAL Postgres.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database).
"""

import os
import uuid

import pytest
from app import copilot_tools as ct
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world(monkeypatch):
    tag = uuid.uuid4().hex[:8]
    w = {k: uuid.uuid4() for k in ("parent", "acme", "birch", "outsider")}
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    monkeypatch.setattr(ct, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, parent, name in (("parent", None, "msp"), ("acme", w["parent"], "Acme Dental"), ("birch", w["parent"], "Birch Law"), ("outsider", None, "other-msp")):
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {"i": w[key], "n": f"{name}-{tag}", "s": f"s-{key}-{tag}", "p": parent, "r": "child" if parent else "parent"},
                )

            async def alert(tenant, title, severity, status, hours_ago):
                await conn.execute(
                    text(
                        "insert into alerts (id, tenant_id, title, severity, status, raw_event, dedup_hash, created_at, event_time, first_seen, last_seen) "
                        "values (:id, :t, :ti, :sev, :st, '{}'::jsonb, :h, now() - make_interval(hours => :ago), now(), now(), now())"
                    ),
                    {"id": uuid.uuid4(), "t": tenant, "ti": title, "sev": severity, "st": status, "h": uuid.uuid4().hex, "ago": hours_ago},
                )

            await alert(w["parent"], "own: medium", "medium", "new", 2)
            await alert(w["acme"], "acme: critical ransomware", "critical", "new", 3)
            await alert(w["acme"], "acme: critical old", "critical", "new", 72)
            await alert(w["acme"], "acme: high resolved", "high", "resolved", 1)
            await alert(w["birch"], "birch: critical", "critical", "new", 5)
            await alert(w["birch"], "birch: low", "low", "new", 1)
            await alert(w["outsider"], "OTHER MSP critical", "critical", "new", 1)
        yield w
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            ids = [str(v) for v in w.values()]
            await conn.execute(text("delete from alerts where tenant_id = any(cast(:t as uuid[]))"), {"t": ids})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [ids[1], ids[2]]})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [ids[0], ids[3]]})
        await engine.dispose()


async def test_the_search_covers_the_tenant_and_its_clients_worst_first_and_never_another_msp(world):
    out = await ct.search_alerts(tenant_id=str(world["parent"]), limit=20)
    titles = [a["title"] for a in out["alerts"]]
    assert "OTHER MSP critical" not in titles
    assert len(titles) == 6
    severities = [a["severity"] for a in out["alerts"]]
    assert severities == sorted(severities, key=lambda s: ["critical", "high", "medium", "low", "info"].index(s))
    by_title = {a["title"]: a for a in out["alerts"]}
    assert by_title["acme: critical ransomware"]["client"].startswith("Acme Dental") and "client" not in by_title["own: medium"]


async def test_severity_hours_and_open_only_narrow_it(world):
    crit = await ct.search_alerts(tenant_id=str(world["parent"]), severity="critical", hours=24, only_open=True)
    assert {a["title"] for a in crit["alerts"]} == {"acme: critical ransomware", "birch: critical"}, "the 72-hour-old one and the other MSP's are out"
    open_only = await ct.search_alerts(tenant_id=str(world["parent"]), only_open=True, limit=20)
    assert "acme: high resolved" not in {a["title"] for a in open_only["alerts"]}
    keyword = await ct.search_alerts(tenant_id=str(world["parent"]), query="ransomware")
    assert [a["title"] for a in keyword["alerts"]] == ["acme: critical ransomware"]


async def test_a_client_only_sees_its_own_alerts(world):
    out = await ct.search_alerts(tenant_id=str(world["acme"]), limit=20)
    assert {a["title"] for a in out["alerts"]} == {"acme: critical ransomware", "acme: critical old", "acme: high resolved"}

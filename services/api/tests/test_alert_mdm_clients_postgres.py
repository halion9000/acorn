"""Clients whose MDM is managed by another tool, on a REAL Postgres (AISOC_TEST_PG_URL, a disposable, fully migrated database).

Ticking a client hides Addigy's "MDM is disabled on <device>" alerts for it, the ones open now and the ones that arrive later (the sweep); nothing else of that client, and no other client, is touched; un-ticking brings them back.
"""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import alert_suppressions as ep
from app.services import alert_suppression as sup
from fastapi import HTTPException
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


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    async def noop(**_kw):
        return None

    monkeypatch.setattr(ep, "emit_audit", noop)


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    owner, acme, birch, stranger = (uuid.uuid4() for _ in range(4))
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t, name, parent in ((owner, "Owner", None), (acme, "Acme Dental", owner), (birch, "Birch Law", owner), (stranger, "Stranger", None)):
            await s.execute(text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, :n, :s, :p)"), {"t": t, "n": name, "s": f"mdm-{t.hex[:10]}", "p": parent})

        async def alert(tenant, title, source="addigy", status="new"):
            i = uuid.uuid4()
            await s.execute(
                text(
                    "insert into alerts (id, tenant_id, title, rule_name, severity, status, priority, affected_hosts, raw_event, enrichment_data, created_at, updated_at, event_time, first_seen, last_seen, connector_type) "
                    "values (:i, :t, :ti, '', 'medium', :st, 50, '[]'::jsonb, cast(:e as jsonb), '{}'::jsonb, now(), now(), now(), now(), now(), 'Generic Generic JSON')"
                ),
                {"i": i, "t": tenant, "ti": title, "st": status, "e": f'{{"source": "{source}"}}'},
            )
            return i

        w = SimpleNamespace(owner=owner, acme=acme, birch=birch, stranger=stranger, alert=alert, s=s, user=SimpleNamespace(tenant_id=owner, user_id=None))
        yield w
        await off(s)
        await s.rollback()
        await off(s)
        for table in ("alerts", "alert_suppressions"):
            await s.execute(text(f"delete from {table} where tenant_id = any(:ids)"), {"ids": [owner, acme, birch, stranger]})
        await s.execute(text("delete from tenants where id = any(:ids)"), {"ids": [acme, birch, stranger, owner]})
        await s.commit()
    await engine.dispose()


async def status_of(w, alert_id):
    await off(w.s)
    return (await w.s.execute(text("select status from alerts where id = :i"), {"i": alert_id})).scalar()


def test_a_prefix_rule_matches_alerts_of_the_tool_with_no_rule_id_whose_title_starts_with_the_text_and_nothing_else():
    r = SimpleNamespace(signature=sup.MDM_SIGNATURE, source="addigy", scope="client", client_tenant_id="c", device_key=None)
    ok = dict(tenant_id="c", rule_id=None, source="addigy", hosts=[])
    assert sup.matches(r, title="MDM is disabled on Brian's MacBook Air", **ok)
    assert not sup.matches(r, title="Something else on Brian's MacBook Air", **ok)
    assert not sup.matches(r, title="MDM is disabled on Mac", **{**ok, "source": "ninjaone"}), "only the tool named"
    assert not sup.matches(r, title="MDM is disabled on Mac", **{**ok, "rule_id": "some-rule"}), "an alert that has a rule id is a different type"
    assert not sup.matches(r, title="MDM is disabled on Mac", **{**ok, "tenant_id": "other"}), "only the client chosen"
    assert not sup.matches(r, title="The MDM is disabled on Mac", **ok), "the title must start with the text"


async def test_choosing_a_client_hides_its_mdm_alerts_now_and_later_and_nothing_else_and_unchoosing_brings_them_back(world):
    w = world
    mine = [await w.alert(w.acme, f"MDM is disabled on Mac {i}") for i in range(3)]
    other_alert = await w.alert(w.acme, "Malware on Mac 1")
    other_tool = await w.alert(w.acme, "MDM is disabled on Mac 9", source="ninjaone")
    birch = await w.alert(w.birch, "MDM is disabled on Mac 5")
    await w.s.commit()
    await off(w.s)
    before = await ep.mdm_clients(w.user, w.s)
    assert {c.client_name: c.elsewhere for c in before.clients} == {"Acme Dental": False, "Birch Law": False}, "another organization's clients are not listed"

    await off(w.s)
    out = await ep.set_mdm_clients(ep.MdmClientsIn(client_ids=[w.acme]), w.user, w.s)
    by = {c.client_name: c for c in out.clients}
    assert by["Acme Dental"].elsewhere is True and by["Acme Dental"].hidden_alerts == 3 and by["Birch Law"].elsewhere is False
    for a in mine:
        assert await status_of(w, a) == "suppressed"
    assert await status_of(w, other_alert) == "new" and await status_of(w, other_tool) == "new" and await status_of(w, birch) == "new"

    later = await w.alert(w.acme, "MDM is disabled on Mac 77")
    await w.s.commit()
    await off(w.s)
    assert (await sup.sweep(w.s))["hidden"] >= 1
    assert await status_of(w, later) == "suppressed", "an alert that arrives later is hidden by the sweep"

    await off(w.s)
    again = await ep.set_mdm_clients(ep.MdmClientsIn(client_ids=[w.acme]), w.user, w.s)
    assert [c.elsewhere for c in again.clients if c.client_name == "Acme Dental"] == [True]
    await off(w.s)
    rules = (await w.s.execute(text("select count(*) from alert_suppressions where tenant_id = :t and revoked_at is null"), {"t": w.owner})).scalar()
    assert rules == 1, "choosing the same client again does not add a second rule"

    await off(w.s)
    cleared = await ep.set_mdm_clients(ep.MdmClientsIn(client_ids=[]), w.user, w.s)
    assert not any(c.elsewhere for c in cleared.clients)
    for a in [*mine, later]:
        assert await status_of(w, a) == "new", "taking the client off the list brings the alerts back as they were"


async def test_only_this_organizations_own_clients_can_be_chosen(world):
    w = world
    await off(w.s)
    with pytest.raises(HTTPException) as e:
        await ep.set_mdm_clients(ep.MdmClientsIn(client_ids=[w.stranger]), w.user, w.s)
    assert e.value.status_code == 422

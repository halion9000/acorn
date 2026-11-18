"""Hide rules proposed from what people always close as noise, on a REAL Postgres (AISOC_TEST_PG_URL, a disposable, fully migrated database).

For each client and alert type: nearly all finished alerts closed as false positives (five or more, nine in ten) proposes a hide rule for that client; mixed outcomes, other clients, open alerts and types a rule already hides do not.
"""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import alert_suppressions as ep
from app.services import alert_suppression as sup
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


def test_a_rule_is_proposed_only_for_five_or_more_false_positives_that_are_nine_in_ten_of_what_was_finished():
    assert sup.should_propose_rule(5, 0)
    assert sup.should_propose_rule(9, 1)
    assert not sup.should_propose_rule(4, 0), "too few"
    assert not sup.should_propose_rule(8, 2), "one in five was real"
    assert not sup.should_propose_rule(0, 0)
    assert sup.should_propose_rule(45, 5)


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    owner, acme, birch = (uuid.uuid4() for _ in range(3))
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t, name, parent in ((owner, "Owner", None), (acme, "Acme Dental", owner), (birch, "Birch Law", owner)):
            await s.execute(text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, :n, :s, :p)"), {"t": t, "n": name, "s": f"sg-{t.hex[:10]}", "p": parent})

        async def alert(tenant, title, status, rule_id=None, source="ninjaone"):
            i = uuid.uuid4()
            await s.execute(
                text(
                    "insert into alerts (id, tenant_id, title, rule_name, rule_id, severity, status, priority, affected_hosts, raw_event, enrichment_data, created_at, updated_at, event_time, first_seen, last_seen, connector_type) "
                    "values (:i, :t, :ti, '', :r, 'low', :st, 50, '[]'::jsonb, cast(:e as jsonb), '{}'::jsonb, now(), now(), now(), now(), now(), 'Generic Generic JSON')"
                ),
                {"i": i, "t": tenant, "ti": title, "r": rule_id, "st": status, "e": f'{{"source": "{source}"}}'},
            )
            return i

        w = SimpleNamespace(owner=owner, acme=acme, birch=birch, alert=alert, s=s, user=SimpleNamespace(tenant_id=owner, user_id=None))
        yield w
        await off(s)
        await s.rollback()
        await off(s)
        for table in ("alerts", "alert_suppressions"):
            await s.execute(text(f"delete from {table} where tenant_id = any(:ids)"), {"ids": [owner, acme, birch]})
        await s.execute(text("delete from tenants where id = any(:ids)"), {"ids": [acme, birch, owner]})
        await s.commit()
    await engine.dispose()


async def test_a_client_and_type_that_people_always_close_as_noise_is_proposed_and_nothing_else_is(world):
    w = world
    for _ in range(6):
        await w.alert(w.acme, "Disk space low", "false_positive")
    await w.alert(w.acme, "Disk space low", "new")
    for _ in range(5):
        await w.alert(w.birch, "Disk space low", "false_positive")
    for _ in range(3):
        await w.alert(w.birch, "Disk space low", "closed")
    for _ in range(7):
        await w.alert(w.acme, "Patch failed", "false_positive", rule_id="patch-rule")
    for _ in range(2):
        await w.alert(w.acme, "Login from new place", "false_positive")
    await w.s.commit()
    await off(w.s)
    out = await ep.suggestions(w.user, w.s, None, 90)
    got = [(s.client_name, s.title, s.false_positives, s.other_finished, s.open_now) for s in out]
    assert got == [("Acme Dental", "Patch failed", 7, 0, 0), ("Acme Dental", "Disk space low", 6, 0, 1)], "Birch closed some as real, and two false positives are too few"
    assert all(s.source == "ninjaone" for s in out)
    # A rule that already hides the type for that client takes the proposal away.
    await off(w.s)
    await w.s.execute(
        text("insert into alert_suppressions (id, tenant_id, scope, client_tenant_id, source, signature, title, created_at) values (gen_random_uuid(), :o, 'client', :c, 'ninjaone', 'title:Disk space low', 'Disk space low', now())"),
        {"o": w.owner, "c": w.acme},
    )
    await w.s.commit()
    await off(w.s)
    after = await ep.suggestions(w.user, w.s, None, 90)
    assert [s.title for s in after] == ["Patch failed"]
    only = await ep.suggestions(w.user, w.s, w.birch, 90)
    assert only == [], "asking for one client shows only that client"

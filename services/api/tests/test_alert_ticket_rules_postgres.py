"""Ticket rules on a REAL Postgres: a rule queues one ticket request per matching alert that has no ticket, only for alerts raised after it (and the one it was made from), never twice, and the ticket CORE
opens is linked to its alert once. Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.models.alert_ticket_rule import AlertTicketRule
from app.services import alert_ticket_rules as svc
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]

NOW = datetime.now(UTC)
TITLE = 'A user asked to release a quarantined message: "Re: Block 2027"'


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    owner, client, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        await s.execute(text("insert into tenants (id, name, slug) values (:t, 'owner', :s)"), {"t": owner, "s": f"own-{owner.hex[:10]}"})
        for t, name in ((client, "client"), (other, "other")):
            await s.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, :n, :s, :p)"),
                {"t": t, "n": name, "s": f"{name}-{t.hex[:10]}", "p": owner},
            )
        await s.execute(
            text(
                "insert into client_aliases (id, tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored) values (gen_random_uuid(), :o, 'halopsa', '77', 'Client', 'client', :c, false)"
            ),
            {"o": owner, "c": client},
        )
        ids: dict[str, uuid.UUID] = {}

        async def alert(key, tenant, title, status="new", minutes_ago=5, source="cipp", enrichment=None):
            ids[key] = uuid.uuid4()
            await s.execute(
                text(
                    "insert into alerts (id, tenant_id, title, severity, status, priority, raw_event, enrichment_data, created_at, updated_at) "
                    "values (:i, :t, :title, 'low', :st, 50, cast(:raw as jsonb), cast(:enr as jsonb), :at, :at)"
                ),
                {
                    "i": ids[key],
                    "t": tenant,
                    "title": title,
                    "st": status,
                    "raw": json.dumps({"source": source}),
                    "enr": json.dumps(enrichment or {}),
                    "at": NOW - timedelta(minutes=minutes_ago),
                },
            )

        await alert("new_a", client, TITLE, minutes_ago=5)
        await alert("new_b", client, TITLE, minutes_ago=3)
        await alert("old_source", client, TITLE, minutes_ago=600)
        await alert("old_other", client, TITLE, minutes_ago=700)
        await alert("has_halo_ticket", client, TITLE, minutes_ago=4, enrichment={"tickets": [{"system": "halopsa", "id": "555"}]})
        await alert("has_manual_ticket", client, TITLE, minutes_ago=4, enrichment={"manual_tickets": [{"system": "halopsa", "id": "556"}]})
        await alert("resolved", client, TITLE, status="resolved", minutes_ago=4)
        await alert("other_title", client, "Something else", minutes_ago=4)
        await alert("other_tool", client, TITLE, minutes_ago=4, source="huntress")
        await alert("other_client", other, TITLE, minutes_ago=4)
        await s.commit()
        s.info.update(owner=owner, client=client, other=other, ids=ids)
        yield s
        await off(s)
        await s.execute(text("delete from vendor_actions where tenant_id in (:a, :b, :c)"), {"a": owner, "b": client, "c": other})
        await s.execute(text("delete from alert_ticket_rules where tenant_id = :o"), {"o": owner})
        await s.execute(text("delete from alerts where tenant_id in (:a, :b, :c)"), {"a": owner, "b": client, "c": other})
        await s.execute(text("delete from client_aliases where tenant_id = :o"), {"o": owner})
        await s.execute(text("delete from tenants where parent_tenant_id = :o"), {"o": owner})
        await s.execute(text("delete from tenants where id = :o"), {"o": owner})
        await s.commit()
    await engine.dispose()


def make_rule(db, scope, created_minutes_ago=60):
    rule = AlertTicketRule(
        id=uuid.uuid4(),
        tenant_id=db.info["owner"],
        scope=scope,
        client_tenant_id=db.info["client"] if scope == "client" else None,
        source="cipp",
        signature=f"title:{TITLE}",
        title=TITLE,
        created_at=NOW - timedelta(minutes=created_minutes_ago),
    )
    db.add(rule)
    return rule


async def queued(db):
    await off(db)
    rows = (
        await db.execute(
            text(
                "select a.title, v.alert_id, v.params, v.status, v.action, v.vendor from vendor_actions v join alerts a on a.id = v.alert_id where v.tenant_id in (:a, :b, :c)"
            ),
            {"a": db.info["owner"], "b": db.info["client"], "c": db.info["other"]},
        )
    ).all()
    by_alert = {r[1]: r for r in rows}
    return {k: by_alert[v] for k, v in db.info["ids"].items() if v in by_alert}


async def test_the_rule_covers_new_alerts_of_the_type_and_the_alert_it_was_made_from_only(world):
    await off(world)
    rule = make_rule(world, "client")
    await world.flush()
    n = await svc.queue_for_rule(world, rule, NOW, source_alert_id=world.info["ids"]["old_source"])
    await world.commit()
    got = await queued(world)
    assert (
        set(got) == {"new_a", "new_b", "old_source"}
    ), "new alerts of the type, and the alert the rule was made from; not older ones, ones with a ticket (Halo's or by hand), finished, other title or tool, or another client"
    assert n == 3
    row = got["new_a"]
    assert (row.action, row.vendor, row.status) == ("create_ticket", "core", "pending")
    assert row.params["summary"] == TITLE[:200] and row.params["halo_client_id"] == "77"
    assert "Opened automatically" in row.params["details"]


async def test_a_second_pass_queues_nothing_more_even_when_the_first_requests_failed(world):
    await off(world)
    rule = make_rule(world, "client")
    await world.flush()
    assert await svc.queue_for_rule(world, rule, NOW) == 2
    await world.commit()
    await off(world)
    await world.execute(
        text("update vendor_actions set status = 'failed', result_message = 'Halo refused' where tenant_id = :c"),
        {"c": world.info["client"]},
    )
    await world.commit()
    assert await svc.queue_for_rule(world, rule, NOW) == 0, "one request per alert, ever: a failure is not retried in a loop"


async def test_a_rule_for_all_clients_reaches_every_client_and_a_client_rule_only_its_own(world):
    await off(world)
    everyone = make_rule(world, "all")
    await world.flush()
    assert await svc.queue_for_rule(world, everyone, NOW) == 3, "two new alerts of the client and one of the other client"
    await world.commit()
    got = await queued(world)
    assert (
        "other_client" in got and "halo_client_id" not in got["other_client"].params
    ), "a client with no Halo client linked is still asked for; CORE says why it cannot"


async def test_the_sweep_queues_for_every_active_rule_and_skips_a_turned_off_one(world):
    await off(world)
    live = make_rule(world, "client")
    dead = make_rule(world, "all")
    dead.revoked_at = NOW
    await world.flush()
    assert await svc.sweep_ticket_rules(world, NOW) == 2
    await world.commit()
    assert "other_client" not in await queued(world)
    assert live.id is not None


async def test_a_ticket_made_for_an_alert_is_linked_once_among_the_hand_entered_ones(world):
    await off(world)
    alert_id, client = world.info["ids"]["new_a"], world.info["client"]
    assert await svc.link_created_ticket(world, client, alert_id, "4521", NOW) is True
    assert await svc.link_created_ticket(world, client, alert_id, "4521", NOW) is False
    await world.commit()
    await off(world)
    manual = (
        await world.execute(text("select enrichment_data -> 'manual_tickets' from alerts where id = :i"), {"i": alert_id})
    ).scalar_one()
    assert [(t["system"], t["id"], t["added_by"]) for t in manual] == [("halopsa", "4521", "ticket rule")]
    assert await svc.link_created_ticket(world, client, uuid.uuid4(), "1", NOW) is False, "an alert that is not there gets nothing"


async def test_a_cipp_closure_for_a_released_message_closes_its_alert_records_who_and_queues_the_ticket_note(world):
    from app.api.v1.endpoints.inbox_core_feed import ClosedItem, ClosedReport, apply_closed

    await off(world)
    client = world.info["client"]
    uids = {k: f"quarantine-release:t1:{k}" for k in ("fresh", "working", "other_kind")}
    ids = {}
    for key, status, uid in (
        ("fresh", "new", uids["fresh"]),
        ("working", "investigating", uids["working"]),
        ("other_kind", "new", "phish-report:t1:x"),
    ):
        ids[key] = uuid.uuid4()
        await world.execute(
            text(
                "insert into alerts (id, tenant_id, title, severity, status, priority, raw_event, enrichment_data, created_at, updated_at) "
                "values (:i, :t, :title, 'low', :st, 50, cast(:raw as jsonb), cast(:enr as jsonb), :at, :at)"
            ),
            {
                "i": ids[key],
                "t": client,
                "title": key,
                "st": status,
                "raw": json.dumps({"source": "cipp", "finding": {"uid": uid}}),
                "enr": json.dumps({"tickets": [{"system": "halopsa", "id": "555"}]}),
                "at": NOW,
            },
        )
    await world.commit()
    await off(world)
    report = ClosedReport(
        vendor="cipp",
        closed=[
            ClosedItem(uid=uids["fresh"], state="released"),
            ClosedItem(uid=uids["working"], state="released"),
            ClosedItem(uid="phish-report:t1:x", state="not junk"),
        ],
    )
    await apply_closed(world, client, report, NOW)
    await world.commit()
    await off(world)
    rows = {
        r[0]: r
        for r in (
            await world.execute(
                text("select title, status, enrichment_data -> 'quarantine_release' ->> 'by' from alerts where id = any(:ids)"),
                {"ids": list(ids.values())},
            )
        ).all()
    }
    assert rows["fresh"][1] == "resolved" and rows["fresh"][2] == "someone else"
    assert (
        rows["working"][1] == "investigating" and rows["working"][2] == "someone else"
    ), "noted, but an analyst's open work is not closed under them"
    assert (
        rows["other_kind"][1] == "resolved" and rows["other_kind"][2] is None
    ), "a different kind of CIPP record is closed on its own state and gets no release record"
    notes = (
        await world.execute(
            text(
                "select alert_id, params ->> 'note', params -> 'ticket_ids' from vendor_actions where action = 'ticket_note' and tenant_id = :t"
            ),
            {"t": client},
        )
    ).all()
    assert {n[0] for n in notes} == {ids["fresh"], ids["working"]}
    assert all("someone else" in n[1] and n[2] == ["555"] for n in notes)

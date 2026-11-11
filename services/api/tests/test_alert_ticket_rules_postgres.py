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
        await s.execute(text("delete from aisoc_cases where tenant_id in (:a, :b, :c)"), {"a": owner, "b": client, "c": other})
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


async def _release_alert(world, key, *, status="new", minutes_ago=5, uid=None, enrichment=None):
    client = world.info["client"]
    alert_id = uuid.uuid4()
    world.info["ids"][key] = alert_id
    raw = {
        "source": "cipp",
        "finding": {"uid": uid or f"quarantine-release:t1:{key}"},
        "unmapped": {
            "context": {
                "cipp_tenant_id": "t1-guid",
                "quarantine_identity": f"id-{key}",
                "username": "kim@acme.com",
                "sender": "x@y.example",
                "quarantine_type": "HighConfPhish",
            }
        },
    }
    await world.execute(
        text(
            "insert into alerts (id, tenant_id, title, severity, status, priority, raw_event, enrichment_data, created_at, updated_at) "
            "values (:i, :t, 'A user asked to release a quarantined message', 'low', :st, 50, cast(:raw as jsonb), cast(:enr as jsonb), :at, :at)"
        ),
        {
            "i": alert_id,
            "t": client,
            "st": status,
            "raw": json.dumps(raw),
            "enr": json.dumps(enrichment or {}),
            "at": NOW - timedelta(minutes=minutes_ago),
        },
    )
    return alert_id


async def test_each_new_release_alert_is_checked_once_as_it_arrives_and_nothing_else_is(world):
    from app.services.quarantine_release import queue_auto_checks

    await off(world)
    fresh = await _release_alert(world, "r_fresh")
    await _release_alert(world, "r_old", minutes_ago=4 * 24 * 60)
    await _release_alert(world, "r_done", status="resolved")
    await _release_alert(world, "r_other_kind", uid="phish-report:t1:x")
    asked_before = await _release_alert(world, "r_asked_before")
    await world.execute(
        text(
            "insert into vendor_actions (id, tenant_id, alert_id, vendor, incident_uid, action, params, status) values (gen_random_uuid(), :t, :a, 'core', 'q', 'quarantine_check', '{}'::jsonb, 'failed')"
        ),
        {"t": world.info["client"], "a": asked_before},
    )
    await world.commit()
    await off(world)
    assert (
        await queue_auto_checks(world, NOW) == 1
    ), "the fresh release alert only: not an old one, a finished one, another kind of alert, or one already checked (even if that check failed)"
    await world.commit()
    await off(world)
    rows = (
        await world.execute(
            text("select alert_id, params, status, vendor from vendor_actions where action = 'quarantine_check' and alert_id = :a"),
            {"a": fresh},
        )
    ).all()
    assert len(rows) == 1 and rows[0][2] == "pending" and rows[0][3] == "core"
    assert rows[0][1] == {
        "client_id": "t1-guid",
        "quarantine_identity": "id-r_fresh",
        "auto": True,
    }, "only which message and which client: a read, never a release"
    assert await queue_auto_checks(world, NOW) == 0, "a second pass asks for nothing more"


async def test_a_finished_check_is_kept_on_the_alert_and_put_on_its_tickets_once_whenever_the_ticket_comes(world):
    from app.services.quarantine_release import store_quarantine_check

    await off(world)
    client = world.info["client"]
    with_ticket = await _release_alert(world, "c_ticket", enrichment={"tickets": [{"system": "halopsa", "id": "555"}]})
    without = await _release_alert(world, "c_none")
    await world.commit()
    await off(world)
    assert await store_quarantine_check(world, client, with_ticket, "Looks malicious or fake: do not release it.", NOW) is True
    assert await store_quarantine_check(world, client, without, "Not clear either way.", NOW) is True
    await world.commit()
    await off(world)
    notes = (
        await world.execute(
            text(
                "select alert_id, params ->> 'note', params -> 'ticket_ids' from vendor_actions where action = 'ticket_note' and tenant_id = :t"
            ),
            {"t": client},
        )
    ).all()
    assert [n[0] for n in notes] == [with_ticket], "a ticket exists: the note is queued; none exists yet: not"
    assert notes[0][2] == ["555"] and "Looks malicious or fake" in notes[0][1] and "read only" in notes[0][1]
    saved = {
        r[0]: r[1]
        for r in (
            await world.execute(
                text("select id, enrichment_data -> 'quarantine_check' from alerts where id = any(:ids)"), {"ids": [with_ticket, without]}
            )
        ).all()
    }
    assert (
        saved[with_ticket]["ticketed"] is True and saved[without]["ticketed"] is False and saved[without]["text"] == "Not clear either way."
    )
    # the ticket for the second alert is made later by a rule: the finished check goes on it then, once
    assert await svc.link_created_ticket(world, client, without, "9001", NOW) is True
    assert await svc.link_created_ticket(world, client, without, "9001", NOW) is False
    await world.commit()
    await off(world)
    late = (
        await world.execute(
            text("select params -> 'ticket_ids', params ->> 'note' from vendor_actions where action = 'ticket_note' and alert_id = :a"),
            {"a": without},
        )
    ).all()
    assert len(late) == 1 and late[0][0] == ["9001"] and "Not clear either way." in late[0][1]


async def test_the_script_runs_of_an_alert_and_the_one_at_a_time_rule_for_scripts_ignore_tickets_releases_and_checks(world):
    from types import SimpleNamespace

    from app.api.v1.endpoints import alert_scripts as sc

    await off(world)
    client, alert_id = world.info["client"], await _release_alert(world, "s_alert")
    for action in ("create_ticket", "release_quarantine", "ticket_note", "quarantine_check", "run_script"):
        await world.execute(
            text(
                "insert into vendor_actions (id, tenant_id, alert_id, vendor, incident_uid, action, params, status) values (gen_random_uuid(), :t, :a, 'core', 'u', :act, cast(:p as jsonb), 'pending')"
            ),
            {
                "t": client,
                "a": alert_id,
                "act": action,
                "p": json.dumps({"script_name": "Clean temp files"} if action == "run_script" else {}),
            },
        )
    await world.commit()
    await off(world)
    import contextlib

    @contextlib.asynccontextmanager
    async def scope(_db, _own, _id):
        yield client

    real = sc.alert_scope
    sc.alert_scope = scope
    try:
        runs = await sc.alert_script_runs(alert_id, SimpleNamespace(tenant_id=world.info["owner"]), world)
    finally:
        sc.alert_scope = real
    assert [r.script_name for r in runs] == [
        "Clean temp files"
    ], "only the script run: the ticket, the release, the note and the check are not scripts"


# ---- catching up the alerts of the type that were already open when the rule was made ----


async def test_a_catch_up_also_covers_older_open_alerts_of_the_type_but_not_ones_with_tickets_finished_or_of_another_type(world):
    await off(world)
    rule = make_rule(world, "client", created_minutes_ago=1)  # made a minute ago: every alert of the type is older than it
    await world.flush()
    assert (
        await svc.queue_for_rule(world, rule, NOW, source_alert_id=world.info["ids"]["old_source"]) == 1
    ), "without a catch-up only the alert it was made from"
    await world.commit()
    await off(world)
    await world.execute(text("delete from vendor_actions where tenant_id = :c"), {"c": world.info["client"]})
    await world.commit()
    n = await svc.queue_for_rule(world, rule, NOW, source_alert_id=world.info["ids"]["old_source"], catch_up=True)
    await world.commit()
    got = await queued(world)
    assert set(got) == {"new_a", "new_b", "old_source", "old_other"}
    assert n == 4
    assert not {"has_halo_ticket", "has_manual_ticket", "resolved", "other_title", "other_tool", "other_client"} & set(got)


async def test_a_catch_up_is_capped_and_the_alert_the_rule_was_made_from_is_never_the_one_left_out(world, monkeypatch):
    await off(world)
    monkeypatch.setattr(svc, "CATCH_UP_MAX", 2)
    rule = make_rule(world, "client", created_minutes_ago=1)
    await world.flush()
    n = await svc.queue_for_rule(world, rule, NOW, source_alert_id=world.info["ids"]["old_other"], catch_up=True)
    await world.commit()
    got = await queued(world)
    assert n == 2 and "old_other" in got, "the oldest alert of the type was the source: it comes first, then the newest"


async def test_the_sweep_after_a_catch_up_asks_for_nothing_it_already_asked_for(world):
    await off(world)
    rule = make_rule(world, "client", created_minutes_ago=1)
    await world.flush()
    assert await svc.queue_for_rule(world, rule, NOW, source_alert_id=world.info["ids"]["old_source"], catch_up=True) == 4
    await world.commit()
    assert await svc.queue_for_rule(world, rule, NOW) == 0


# ---- what the alert page says about its ticket ----


async def status_of(world, key):
    from app.api.v1.deps import CurrentUser
    from app.api.v1.endpoints import alert_ticket_rules as ep

    await off(world)
    user = CurrentUser(user_id=uuid.uuid4(), tenant_id=world.info["owner"], role="admin", email="hal@example.com")
    return await ep.ticket_status_for_alert(world.info["ids"][key], user, world)


async def test_the_status_says_none_when_no_rule_covers_the_alert(world):
    assert (await status_of(world, "new_a")).state == "none"


async def test_the_status_tells_a_rule_that_will_open_one_from_a_rule_that_came_too_late(world):
    make_rule(world, "client", created_minutes_ago=60)
    await world.flush()
    assert (await status_of(world, "new_a")).state == "rule_will_open"
    assert (await status_of(world, "old_source")).state == "older_than_rule", "raised before the rule was made"
    out = await status_of(world, "old_source")
    assert out.rule_title == TITLE and "before the rule was made" in out.message
    assert (await status_of(world, "other_title")).state == "none"


async def test_the_status_follows_the_request_from_waiting_to_failed_with_cores_reason_and_a_ticket_wins_over_all(world):
    rule = make_rule(world, "client")
    await world.flush()
    await svc.queue_for_rule(world, rule, NOW)
    await world.commit()
    assert (await status_of(world, "new_a")).state == "waiting"
    await off(world)
    await world.execute(
        text("update vendor_actions set status = 'failed', result_message = 'No HaloPSA client is linked' where alert_id = :a"),
        {"a": world.info["ids"]["new_a"]},
    )
    await world.commit()
    out = await status_of(world, "new_a")
    assert out.state == "failed" and out.message == "No HaloPSA client is linked"
    assert (await status_of(world, "has_halo_ticket")).state == "has_ticket"


# ---- trying again after a request failed ----


async def fail_requests(world, *keys):
    await off(world)
    for key in keys:
        await world.execute(
            text("update vendor_actions set status = 'failed', result_message = 'Ticket Type not set' where alert_id = :a"),
            {"a": world.info["ids"][key]},
        )
    await world.commit()


async def test_a_catch_up_tries_again_for_a_failed_request_but_the_ordinary_sweep_never_does(world):
    await off(world)
    rule = make_rule(world, "client")
    await world.flush()
    assert await svc.queue_for_rule(world, rule, NOW) == 2
    await world.commit()
    await fail_requests(world, "new_a")
    assert await svc.queue_for_rule(world, rule, NOW) == 0, "the sweep: one request per alert, ever"
    await world.commit()
    assert (
        await svc.queue_for_rule(world, rule, NOW, catch_up=True) == 3
    ), "the one that failed, and the two older open alerts that never had a request; not the one still waiting"
    await world.commit()
    await off(world)
    rows = (
        (
            await world.execute(
                text("select status from vendor_actions where alert_id = :a order by created_at"), {"a": world.info["ids"]["new_a"]}
            )
        )
        .scalars()
        .all()
    )
    assert sorted(rows) == ["failed", "pending"]
    waiting = (
        await world.execute(text("select count(*) from vendor_actions where alert_id = :a"), {"a": world.info["ids"]["new_b"]})
    ).scalar_one()
    assert waiting == 1, "the alert whose request was still waiting got no second one"
    assert await svc.queue_for_rule(world, rule, NOW, catch_up=True) == 0, "and a second catch-up while those wait asks for nothing more"


async def test_try_again_asks_once_after_a_failure_and_never_when_waiting_done_absent_or_ticketed(world):
    from app.models.alert import Alert

    rule = make_rule(world, "client")
    await world.flush()
    await svc.queue_for_rule(world, rule, NOW)
    await world.commit()
    owner, client = world.info["owner"], world.info["client"]

    async def retry(key):
        await off(world)
        alert = await world.get(Alert, world.info["ids"][key])
        return await svc.retry_ticket(world, owner, client, alert, NOW)

    assert await retry("new_a") is False, "its request is still waiting"
    await fail_requests(world, "new_a")
    assert await retry("new_a") is True
    await world.commit()
    assert await retry("new_a") is False, "the new request is waiting: never a second one"
    assert await retry("new_b") is False, "another alert whose request has not failed"
    assert await retry("has_halo_ticket") is False, "an alert with a ticket"
    assert await retry("resolved") is False, "an alert that was never asked for has nothing to retry"
    await off(world)
    row = (
        await world.execute(
            text("select params, status from vendor_actions where alert_id = :a and status = 'pending'"), {"a": world.info["ids"]["new_a"]}
        )
    ).one()
    assert row.params["halo_client_id"] == "77" and row.params["summary"] == TITLE[:200]


async def test_a_rule_opens_one_linked_case_per_alert_it_covers_with_or_without_a_ticket_and_never_a_second(world):
    await off(world)
    ids = world.info["ids"]
    rule = make_rule(world, "client")
    await world.flush()
    await svc.queue_for_rule(world, rule, NOW, source_alert_id=ids["old_source"])
    await world.commit()
    await off(world)

    async def cases():
        rows = (
            await world.execute(
                text(
                    "select a.id, a.case_id, c.alert_ids, c.created_by, c.tags->>'source' from alerts a left join aisoc_cases c on c.id = a.case_id where a.tenant_id in (:a, :b, :c)"
                ),
                {"a": world.info["owner"], "b": world.info["client"], "c": world.info["other"]},
            )
        ).all()
        return {k: next(r for r in rows if r[0] == v) for k, v in ids.items()}

    got = await cases()
    with_case = {k for k, r in got.items() if r[1] is not None}
    assert with_case == {
        "new_a",
        "new_b",
        "old_source",
        "has_halo_ticket",
        "has_manual_ticket",
    }, "a case for each alert the rule covers, even one that already has a ticket; none for the rest"
    row = got["new_a"]
    assert row[2] == [ids["new_a"]] and row[3] == "system" and row[4] == "ticket-rule", "linked both ways"
    first = {k: r[1] for k, r in got.items()}
    await svc.queue_for_rule(world, rule, NOW)
    await world.commit()
    await off(world)
    assert {k: r[1] for k, r in (await cases()).items()} == first, "a second pass opens no second case"

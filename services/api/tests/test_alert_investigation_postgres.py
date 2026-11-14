"""Starting an AI investigation opens a case and asks for a ticket, and the finished report goes onto both, against a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL)."""

import json
import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import alert_investigation as ep
from app.db.rls import set_rls_context
from app.services import alert_ticket_rules as atr
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
    ),
]
SCRIPTS = [{"id": 7, "name": "Disk Space Scan", "one_click": False}]


@pytest.fixture
async def world():
    owner, acme, birch = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    d1, d2, d3, d4 = (uuid.uuid4() for _ in range(4))
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, name, parent, settings in (
            (owner, "Live Oak", None, {"core_scripts": SCRIPTS}),
            (acme, "Acme Dental", owner, {}),
            (birch, "Birch Law", owner, {}),
        ):
            await conn.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id, settings) values (:t, :n, :s, :p, cast(:x as jsonb))"),
                {"t": tid, "n": name, "s": f"ds-{tag}-{str(tid)[:6]}", "p": parent, "x": json.dumps(settings)},
            )
        await conn.execute(
            text(
                "insert into client_aliases (tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored, match_source) "
                "values (:p, 'halopsa', '4242', 'Acme Dental', 'acme dental', :c, false, 'manual')"
            ),
            {"p": owner, "c": acme},
        )
        for did, tid, host in (
            (d1, acme, "FRONT-DESK-PC"),
            (d2, acme, "front-desk-pc"),
            (d3, birch, "BIRCH-SRV1"),
            (d4, acme, "ACME-LAP2"),
        ):
            await conn.execute(
                text("insert into devices (id, tenant_id, hostname, alt_serials) values (:i, :t, :h, '{}')"),
                {"i": did, "t": tid, "h": host},
            )
    w = SimpleNamespace(
        owner=owner,
        acme=acme,
        birch=birch,
        d=(d1, d2, d3, d4),
        user=SimpleNamespace(tenant_id=owner, user_id=None, email="hal@goliveoak.com"),
    )
    yield w
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": [owner, acme, birch]})
    await engine.dispose()


async def as_app(w, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, w.owner)
            return await work(db)
    finally:
        await engine.dispose()


async def owner_rows(sql, params=None):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("set session_replication_role = replica"))
            return (await conn.execute(text(sql), params or {})).all()
    finally:
        await engine.dispose()


# The alert of the test running: a new one each time (deleting a tenant under replica mode skips the cascade).
CUR: dict = {}


async def add_alert(w, enrichment="{}", case=False):
    CUR["id"] = uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(
            text(
                "insert into alerts (id, tenant_id, title, severity, status, priority, affected_hosts, raw_event, enrichment_data, description, created_at, updated_at) "
                "values (:i, :t, 'Password Spray', 'high', 'new', 50, '[]'::jsonb, '{}'::jsonb, cast(:e as jsonb), 'Many failed sign-ins', now(), now())"
            ),
            {"i": CUR["id"], "t": w.acme, "e": enrichment},
        )
    await engine.dispose()


def opened(w):
    request = SimpleNamespace(client=None, headers={})
    return as_app(w, lambda db: ep.open_investigation(CUR["id"], request, w.user, db))


def reported(w, report="# Findings: It was a spray."):
    request = SimpleNamespace(client=None, headers={})
    return as_app(w, lambda db: ep.report_investigation(CUR["id"], ep.ReportIn(report=report, run_id="run-1"), request, w.user, db))


async def test_starting_opens_a_case_for_an_alert_that_has_none_links_it_and_asks_core_for_a_ticket(world):
    w = world
    await add_alert(w)
    out = await opened(w)
    assert out.case_created and out.ticket == "queued"
    cases = await owner_rows("select id, title, alert_ids, tags from aisoc_cases where tenant_id = :t", {"t": w.acme})
    assert len(cases) == 1 and cases[0].id == out.case_id and cases[0].title == "Password Spray"
    assert [str(a) for a in cases[0].alert_ids] == [str(CUR["id"])]
    linked = await owner_rows("select case_id from alerts where id = :a", {"a": CUR["id"]})
    assert linked[0].case_id == out.case_id
    actions = await owner_rows(
        "select vendor, action, params, alert_id from vendor_actions where tenant_id = :t and action = 'create_ticket'", {"t": w.acme}
    )
    assert len(actions) == 1 and actions[0].alert_id == CUR["id"] and actions[0].params["summary"] == "Password Spray"
    assert "AI investigation was started" in actions[0].params["details"]


async def test_starting_again_neither_opens_a_second_case_nor_asks_for_a_second_ticket(world):
    w = world
    await add_alert(w)
    first = await opened(w)
    second = await opened(w)
    assert second.case_id == first.case_id and not second.case_created and second.ticket == "waiting"
    assert len(await owner_rows("select 1 from aisoc_cases where tenant_id = :t", {"t": w.acme})) == 1
    assert len(await owner_rows("select 1 from vendor_actions where tenant_id = :t and action = 'create_ticket'", {"t": w.acme})) == 1


async def test_an_alert_that_already_has_a_ticket_is_not_asked_for_another(world):
    w = world
    await add_alert(w, enrichment='{"manual_tickets": [{"system": "halopsa", "id": "555", "summary": "x"}]}')
    out = await opened(w)
    assert out.ticket == "existing"
    assert await owner_rows("select 1 from vendor_actions where tenant_id = :t and action = 'create_ticket'", {"t": w.acme}) == []


async def test_the_report_goes_on_the_case_and_on_the_ticket_as_a_private_note_once(world):
    w = world
    await add_alert(w, enrichment='{"manual_tickets": [{"system": "halopsa", "id": "555", "summary": "x"}]}')
    out = await opened(w)
    r = await reported(w)
    assert r.case_commented and r.ticket == "queued"
    comments = await owner_rows(
        "select body, is_system from aisoc_case_comments where case_id = :c order by created_at", {"c": out.case_id}
    )
    assert any("AI investigation report" in c.body and "It was a spray" in c.body and c.is_system is False for c in comments)
    notes = await owner_rows("select params from vendor_actions where tenant_id = :t and action = 'ticket_note'", {"t": w.acme})
    assert len(notes) == 1 and notes[0].params["ticket_ids"] == ["555"] and "It was a spray" in notes[0].params["note"]


async def test_a_report_that_finishes_before_the_ticket_exists_is_written_the_moment_the_ticket_is_linked(world):
    w = world
    await add_alert(w)
    await opened(w)
    r = await reported(w)
    assert r.ticket == "waiting"
    assert await owner_rows("select 1 from vendor_actions where tenant_id = :t and action = 'ticket_note'", {"t": w.acme}) == []

    async def link(db):
        from datetime import UTC, datetime

        from app.db.rls_scope import acting_as_tenant

        async with acting_as_tenant(db, w.acme):
            ok = await atr.link_created_ticket(db, w.acme, CUR["id"], "777", datetime.now(UTC))
            await db.commit()
            return ok

    assert await as_app(w, link) is True
    notes = await owner_rows("select params from vendor_actions where tenant_id = :t and action = 'ticket_note'", {"t": w.acme})
    assert len(notes) == 1 and notes[0].params["ticket_ids"] == ["777"] and "It was a spray" in notes[0].params["note"]
    # and only once: linking another ticket does not repeat it
    assert await as_app(w, lambda db: link2(db, w)) is not None
    assert len(await owner_rows("select 1 from vendor_actions where tenant_id = :t and action = 'ticket_note'", {"t": w.acme})) == 1


async def link2(db, w):
    from datetime import UTC, datetime

    from app.db.rls_scope import acting_as_tenant

    async with acting_as_tenant(db, w.acme):
        ok = await atr.link_created_ticket(db, w.acme, CUR["id"], "778", datetime.now(UTC))
        await db.commit()
        return ok


async def test_a_report_for_an_alert_with_no_case_is_refused_and_a_long_report_is_cut_for_the_ticket(world):
    w = world
    await add_alert(w)
    with pytest.raises(HTTPException) as e:
        await reported(w)
    assert e.value.status_code == 409
    note = atr.report_note("x" * 9000)
    assert len(note) <= 3500 and note.startswith("A.C.O.R.N AI investigation:") and "full report is on the case" in note

"""A HaloPSA ticket from a Client Risk Score question, against a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).

The request is queued for CORE (which holds the HaloPSA key); CORE answers with the ticket's number, and the private note is then queued as its own action. The ticket is the client's, so every
write runs in the client's scope and the organisation's audit line outside it (the rule that broke deleting an assessment on 2026-11-12).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import vcio_risk_scoring as ep
from app.db.rls import set_rls_context
from app.services import vcio_risk_scoring as rs
from app.services import vcio_risk_tickets as tk
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
QID = next(iter(rs.questions_by_id()))


@pytest.fixture
async def world():
    owner, acme, birch = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, name, parent in ((owner, "Live Oak", None), (acme, "Acme Dental", owner), (birch, "Birch Law", owner)):
            await conn.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, :n, :s, :p)"),
                {"t": tid, "n": name, "s": f"rt-{tag}-{str(tid)[:6]}", "p": parent},
            )
        # Acme is linked to a HaloPSA client; Birch is not.
        await conn.execute(
            text(
                "insert into client_aliases (tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored, match_source) "
                "values (:p, 'halopsa', '4242', 'Acme Dental', 'acme dental', :c, false, 'manual')"
            ),
            {"p": owner, "c": acme},
        )
    w = SimpleNamespace(owner=owner, acme=acme, birch=birch, user=SimpleNamespace(tenant_id=owner, user_id=None, email="hal@goliveoak.com"))
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


async def an_assessment(w, client):
    return await as_app(w, lambda db: ep.create_assessment(ep.AssessmentIn(client_id=client), w.user, db))


async def ask(w, assessment, summary="Turn on MFA for everyone", note="Start with the owners."):
    return await as_app(w, lambda db: ep.create_ticket(assessment.id, QID, ep.TicketIn(summary=summary, note=note), w.user, db))


async def actions(w):
    return await owner_rows(
        "select action, incident_uid, params, status, tenant_id from vendor_actions where tenant_id = any(:t) order by created_at",
        {"t": [w.acme, w.birch, w.owner]},
    )


async def test_a_ticket_is_queued_for_core_with_the_name_the_client_and_where_it_came_from(world):
    w = world
    made = await an_assessment(w, w.acme)
    out = await ask(w, made)
    assert (out.state, out.ticket_id, out.status, out.summary, out.private_note, out.question_id) == (
        "waiting",
        None,
        None,
        "Turn on MFA for everyone",
        "Start with the owners.",
        QID,
    )
    queued = [a for a in await actions(w) if a.action == "create_ticket"]
    assert len(queued) == 1 and queued[0].tenant_id == w.acme and queued[0].status == "pending"
    assert queued[0].incident_uid == f"{tk.UID_PREFIX}{out.id}"
    params = queued[0].params
    assert params["summary"] == "Turn on MFA for everyone" and params["halo_client_id"] == "4242"
    assert (
        "Acme Dental" in params["details"]
        and QID in params["details"]
        and rs.questions_by_id()[QID]["text"] in params["details"]
        and "hal@goliveoak.com" in params["details"]
    )
    assert (
        "Start with the owners." not in params["details"]
    ), "the private note is not in the description: it is written on the ticket as a private note"
    audited = await owner_rows(
        "select count(*) from audit_log where tenant_id = :t and action = 'vcio:risk_ticket_requested'", {"t": w.owner}
    )
    assert audited[0][0] == 1


async def test_it_is_refused_with_a_reason_for_a_client_with_no_halopsa_link_the_own_organisation_a_blank_name_and_an_unknown_question(
    world,
):
    w = world
    for client in (w.birch, w.owner):
        made = await an_assessment(w, client)
        with pytest.raises(HTTPException) as refused:
            await ask(w, made)
        assert refused.value.status_code == 422 and "not linked to a HaloPSA client" in refused.value.detail
    made = await an_assessment(w, w.acme)
    with pytest.raises(HTTPException) as blank:
        await ask(w, made, summary="   ")
    assert blank.value.status_code == 422
    with pytest.raises(HTTPException) as unknown:
        await as_app(w, lambda db: ep.create_ticket(made.id, "NOPE-999", ep.TicketIn(summary="x"), w.user, db))
    assert unknown.value.status_code == 404
    assert [a for a in await actions(w) if a.action == "create_ticket"] == []


async def test_a_second_request_waits_until_the_first_is_answered_and_a_question_can_have_more_tickets_afterwards(world):
    w = world
    made = await an_assessment(w, w.acme)
    first = await ask(w, made)
    with pytest.raises(HTTPException) as busy:
        await ask(w, made, summary="Again")
    assert busy.value.status_code == 409
    await as_app(w, lambda db: _answer(db, w.acme, f"{tk.UID_PREFIX}{first.id}", "5001"))
    second = await ask(w, made, summary="Follow-up")
    assert second.id != first.id
    listed = await as_app(w, lambda db: ep.list_tickets(made.id, w.user, db))
    assert [(t.summary, t.state, t.ticket_id) for t in listed.items] == [
        ("Turn on MFA for everyone", "opened", "5001"),
        ("Follow-up", "waiting", None),
    ]


async def _answer(db, tenant, uid, ticket_id, failed=None):
    from app.db.rls_scope import acting_as_tenant

    async with acting_as_tenant(db, tenant):
        now = datetime.now(UTC)
        ok = (
            await tk.on_failed(db, tenant, uid, failed, now) if failed is not None else await tk.on_created(db, tenant, uid, ticket_id, now)
        )
        await db.commit()
        return ok


async def test_when_core_opens_the_ticket_its_number_is_on_the_line_and_the_private_note_is_queued_as_a_private_note_for_that_ticket(world):
    w = world
    made = await an_assessment(w, w.acme)
    out = await ask(w, made)
    assert await as_app(w, lambda db: _answer(db, w.acme, f"{tk.UID_PREFIX}{out.id}", "5002")) is True
    (line,) = (await as_app(w, lambda db: ep.list_tickets(made.id, w.user, db))).items
    assert (line.state, line.ticket_id, line.message) == ("opened", "5002", None)
    notes = [a for a in await actions(w) if a.action == "ticket_note"]
    assert (
        len(notes) == 1 and notes[0].params == {"ticket_ids": ["5002"], "note": "Start with the owners."} and notes[0].status == "pending"
    )
    # A ticket with no private note queues no note.
    plain = await ask(w, await an_assessment(w, w.acme), note="")
    await as_app(w, lambda db: _answer(db, w.acme, f"{tk.UID_PREFIX}{plain.id}", "5003"))
    assert len([a for a in await actions(w) if a.action == "ticket_note"]) == 1
    # An answer that is not one of ours is not taken for one.
    assert await as_app(w, lambda db: _answer(db, w.acme, "bec-ticket:" + str(uuid.uuid4()), "5004")) is False
    assert await as_app(w, lambda db: _answer(db, w.acme, f"{tk.UID_PREFIX}not-a-uuid", "5004")) is False


async def test_when_core_cannot_open_it_the_line_says_why(world):
    w = world
    made = await an_assessment(w, w.acme)
    out = await ask(w, made)
    await as_app(w, lambda db: _answer(db, w.acme, f"{tk.UID_PREFIX}{out.id}", None, failed="HaloPSA refused: no ticket type."))
    (line,) = (await as_app(w, lambda db: ep.list_tickets(made.id, w.user, db))).items
    assert (line.state, line.ticket_id, line.message) == ("failed", None, "HaloPSA refused: no ticket type.")
    again = await ask(w, made, summary="Try again")  # a failed one does not block a new request
    assert again.state == "waiting"


async def test_the_status_core_reads_is_kept_and_only_open_or_recently_closed_tickets_are_looked_up_again(world):
    w = world
    made = await an_assessment(w, w.acme)
    a = await ask(w, made, summary="One")
    await as_app(w, lambda db: _answer(db, w.acme, f"{tk.UID_PREFIX}{a.id}", "6001"))
    b = await ask(w, made, summary="Two")
    await as_app(w, lambda db: _answer(db, w.acme, f"{tk.UID_PREFIX}{b.id}", "6002"))
    now = datetime.now(UTC)

    async def tracked(db):
        from app.db.rls_scope import acting_as_tenant

        async with acting_as_tenant(db, w.acme):
            return await tk.tracked_ticket_ids(db, w.acme, now)

    async def apply(db, statuses, at):
        from app.db.rls_scope import acting_as_tenant

        async with acting_as_tenant(db, w.acme):
            changed = await tk.apply_statuses(db, w.acme, statuses, at)
            await db.commit()
            return changed

    assert sorted(await as_app(w, tracked)) == ["6001", "6002"]
    assert await as_app(w, lambda db: apply(db, {"6001": "On Hold", "6002": "Waiting on Customer", "9999": "Open"}, now)) == 2
    lines = {t.ticket_id: t.status for t in (await as_app(w, lambda db: ep.list_tickets(made.id, w.user, db))).items}
    assert lines == {"6001": "On Hold", "6002": "Waiting on Customer"}
    # The same status again changes nothing; no text keeps what was there; a new one replaces it.
    assert await as_app(w, lambda db: apply(db, {"6001": "On Hold", "6002": ""}, now)) == 0
    assert await as_app(w, lambda db: apply(db, {"6001": "Tech Updated"}, now)) == 1
    # A ticket closed more than two days ago is not looked up again; a recently closed one still is.
    assert await as_app(w, lambda db: apply(db, {"6002": "Closed"}, now - timedelta(days=3))) == 1
    assert await as_app(w, lambda db: apply(db, {"6001": "Resolved"}, now - timedelta(hours=1))) == 1
    assert await as_app(w, tracked) == ["6001"]


async def test_deleting_the_assessment_takes_its_tickets_with_it_and_another_client_never_sees_them(world):
    w = world
    made = await an_assessment(w, w.acme)
    await ask(w, made)
    other = await an_assessment(w, w.birch)
    assert (await as_app(w, lambda db: ep.list_tickets(other.id, w.user, db))).items == []
    await as_app(w, lambda db: ep.delete_assessment(made.id, w.user, db))
    assert (await owner_rows("select count(*) from vcio_risk_tickets where assessment_id = :a", {"a": made.id}))[0][0] == 0

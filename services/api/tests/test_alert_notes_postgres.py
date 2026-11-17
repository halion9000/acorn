"""Alert notes on a REAL Postgres: a note is kept under the tenant that holds the alert, listed oldest first, empty ones refused, an unknown alert is a 404, and another owner's alert is not found.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import alert_notes as ep
from app.api.v1.endpoints.alert_notes import NoteIn, add_note, list_notes
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

    monkeypatch.setattr(ep, "emit_audit", noop)  # the audit log is append-only; the shared helper is tested elsewhere


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    owner, client, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    alert_id, foreign_alert = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (owner, other):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"n-{t.hex[:10]}"})
        await s.execute(
            text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, 'Acme', :s, :p)"),
            {"t": client, "s": f"c-{client.hex[:10]}", "p": owner},
        )
        for aid, tid in ((alert_id, client), (foreign_alert, other)):
            await s.execute(
                text(
                    "insert into alerts (id, tenant_id, title, severity, status, priority, affected_hosts, raw_event, enrichment_data, created_at, updated_at) values (:i, :t, 'T', 'low', 'new', 50, '[]'::jsonb, '{}'::jsonb, '{}'::jsonb, now(), now())"
                ),
                {"i": aid, "t": tid},
            )
        await s.commit()
        s.info.update(owner=owner, client=client, alert=alert_id, foreign=foreign_alert)
        yield s
        await off(s)
        await s.execute(text("delete from alert_notes where tenant_id in (:a, :b)"), {"a": client, "b": other})
        await s.execute(text("delete from alerts where tenant_id in (:a, :b)"), {"a": client, "b": other})
        await s.execute(text("delete from tenants where parent_tenant_id = :o"), {"o": owner})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": owner, "b": other})
        await s.commit()
    await engine.dispose()


def user(tenant):
    return SimpleNamespace(tenant_id=tenant, user_id=None, email="hal@example.com")


async def test_a_note_is_kept_under_the_clients_tenant_listed_oldest_first_and_an_empty_one_is_refused(world):
    s = world
    await off(s)
    first = await add_note(s.info["alert"], NoteIn(body="  Called the user.  "), None, user(s.info["owner"]), s)
    await off(s)
    await add_note(s.info["alert"], NoteIn(body="No answer, will retry."), None, user(s.info["owner"]), s)
    assert first.body == "Called the user." and first.author == "hal@example.com"
    await off(s)
    kept = (await s.execute(text("select tenant_id from alert_notes where alert_id = :a"), {"a": s.info["alert"]})).scalars().all()
    assert set(kept) == {s.info["client"]}, "kept under the tenant that holds the alert, not the parent that wrote it"
    await off(s)
    got = await list_notes(s.info["alert"], user(s.info["owner"]), s)
    assert [n.body for n in got] == ["Called the user.", "No answer, will retry."]
    await off(s)
    with pytest.raises(HTTPException) as err:
        await add_note(s.info["alert"], NoteIn(body="   \n  "), None, user(s.info["owner"]), s)
    assert err.value.status_code == 422


async def test_an_unknown_alert_and_another_owners_alert_are_a_404(world):
    s = world
    for aid in (uuid.uuid4(), s.info["foreign"]):
        await off(s)
        with pytest.raises(HTTPException) as err:
            await add_note(aid, NoteIn(body="x"), None, user(s.info["owner"]), s)
        assert err.value.status_code == 404
        await off(s)
        with pytest.raises(HTTPException) as err2:
            await list_notes(aid, user(s.info["owner"]), s)
        assert err2.value.status_code == 404


async def test_a_note_on_an_alert_in_a_case_is_also_a_case_timeline_entry_and_a_note_on_a_loose_alert_is_not(world):
    s = world
    case_id = uuid.uuid4()
    await off(s)
    await s.execute(
        text("insert into cases (id, tenant_id, case_number, title, status, created_at, updated_at) values (:c, :t, 'C-NOTE-1', 'Case', 'open', now(), now())"),
        {"c": case_id, "t": s.info["client"]},
    )
    await s.commit()
    try:
        await off(s)
        await s.execute(text("update alerts set case_id = :c where id = :a"), {"c": case_id, "a": s.info["alert"]})
        await s.commit()
        await off(s)
        note = await add_note(s.info["alert"], NoteIn(body="Called the user, no answer."), None, user(s.info["owner"]), s)
        await off(s)
        rows = (await s.execute(text("select event_type, content, tenant_id, metadata->>'alert_id', metadata->>'note_id', is_automated from case_timeline where case_id = :c"), {"c": case_id})).all()
        assert len(rows) == 1
        event_type, content, tenant, alert_id, note_id, automated = rows[0]
        assert (event_type, tenant, alert_id, note_id, automated) == ("alert_note", s.info["client"], str(s.info["alert"]), str(note.id), False)
        assert content == "Note on alert “T”: Called the user, no answer."
        # An alert in no case adds nothing to any timeline.
        await off(s)
        await s.execute(text("update alerts set case_id = null where id = :a"), {"a": s.info["alert"]})
        await s.commit()
        await off(s)
        await add_note(s.info["alert"], NoteIn(body="A second note, alert out of the case."), None, user(s.info["owner"]), s)
        await off(s)
        after = (await s.execute(text("select count(*) from case_timeline where case_id = :c"), {"c": case_id})).scalar_one()
        assert after == 1, "the second note was written after the alert left the case"
    finally:
        await off(s)
        await s.execute(text("update alerts set case_id = null where id = :a"), {"a": s.info["alert"]})
        await s.execute(text("delete from case_timeline where case_id = :c"), {"c": case_id})
        await s.execute(text("delete from cases where id = :c"), {"c": case_id})
        await s.commit()


def test_the_timeline_line_names_the_alert_then_the_note_and_copes_with_no_title():
    assert ep.timeline_text("Impossible travel", "Called.") == "Note on alert “Impossible travel”: Called."
    assert ep.timeline_text(None, "x") == "Note on alert “an alert”: x"
    assert ep.timeline_text("  ", "x") == "Note on alert “an alert”: x"
    assert len(ep.timeline_text("t" * 500, "x")) < 150

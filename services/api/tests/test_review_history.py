"""The history of each client-review question: the pure part (what counts as a change) and the stored part on a REAL Postgres (AISOC_TEST_PG_URL)."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.services import review_history as rh
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def items():
    return (
        [SimpleNamespace(key="edr", status="partly", evidence="17 of 20 machines report Huntress.")],
        [SimpleNamespace(key="backup", status="seen", suggested="Slide", evidence="Slide protects 12 systems.")],
        [SimpleNamespace(question="Is MFA on for everyone?", status="met", evidence="Every user has it.")],
        [SimpleNamespace(question="Is the firewall patched?", status="needs_person", evidence="")],
    )


def test_a_snapshot_reads_every_section_with_its_worked_out_status_and_evidence():
    got = rh.snapshot(*items())
    assert [(r.section, r.key, r.status) for r in got] == [
        ("readiness", "edr", "partly"),
        ("tech", "backup", "seen"),
        ("m365", "Is MFA on for everyone?", "met"),
        ("assess", "Is the firewall patched?", "needs_person"),
    ]
    assert got[1].detail == "Slide - Slide protects 12 systems."
    assert got[3].detail is None, "no evidence is no detail, not an empty string"


def test_only_a_reading_that_differs_from_the_last_automatic_row_is_a_change():
    readings = rh.snapshot(*items())
    last = {(r.section, r.key): (r.status, r.detail) for r in readings}
    assert rh.changed(readings, last) == []
    last[("readiness", "edr")] = ("partly", "16 of 20 machines report Huntress.")  # the evidence moved
    last[("m365", "Is MFA on for everyone?")] = ("not_met", "Every user has it.")  # the status moved
    del last[("tech", "backup")]  # never recorded
    assert [(r.section, r.key) for r in rh.changed(readings, last)] == [
        ("readiness", "edr"),
        ("tech", "backup"),
        ("m365", "Is MFA on for everyone?"),
    ]


def test_a_long_evidence_is_cut_to_what_is_stored():
    long = [SimpleNamespace(key="x", status="met", evidence="e" * 5000)]
    assert len(rh.snapshot(long, [], [], [])[0].detail or "") == rh.DETAIL_CHARS


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pg = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    tenant, other = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for t in (tenant, other):
            await conn.execute(text("insert into tenants (id, name, slug) values (:t, 'hist', :s)"), {"t": t, "s": f"hist-{t.hex[:10]}"})
    yield engine, tenant, other
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("delete from client_review_history where tenant_id = any(:t)"), {"t": [tenant, other]})
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": [tenant, other]})
    await engine.dispose()


@pg
@pytest.mark.asyncio
async def test_a_changed_automatic_answer_is_stored_once_and_listed_newest_first_with_the_typed_ones(world):
    engine, tenant, other = world
    readiness, tech, m365, assess = items()
    async with AsyncSession(engine) as db:
        assert await rh.record_automatic(db, tenant, rh.snapshot(readiness, tech, m365, assess), NOW) == 4
        assert (
            await rh.record_automatic(db, tenant, rh.snapshot(readiness, tech, m365, assess), NOW + timedelta(hours=1)) == 0
        ), "nothing changed, nothing stored"
        readiness[0].status, readiness[0].evidence = "met", "20 of 20 machines report Huntress."
        assert await rh.record_automatic(db, tenant, rh.snapshot(readiness, tech, m365, assess), NOW + timedelta(days=1)) == 1
        await rh.record_manual(
            db,
            tenant,
            "readiness",
            "edr",
            status="met",
            answer=None,
            note="Confirmed with the client",
            actor="tech@liveoak.test",
            now=NOW + timedelta(days=2),
        )
        await rh.record_automatic(db, other, rh.snapshot(*items()), NOW)  # another client's rows are never in this one's list
        await db.commit()
        rows = await rh.history(db, tenant, "readiness", "edr")
    assert [(r["source"], r["status"]) for r in rows] == [("manual", "met"), ("automatic", "met"), ("automatic", "partly")]
    assert rows[0]["actor"] == "tech@liveoak.test" and rows[0]["note"] == "Confirmed with the client"
    assert rows[1]["detail"] == "20 of 20 machines report Huntress."


@pg
@pytest.mark.asyncio
async def test_only_the_newest_rows_of_a_question_are_kept(world, monkeypatch):
    engine, tenant, _ = world
    monkeypatch.setattr(rh, "KEEP_PER_QUESTION", 3)
    async with AsyncSession(engine) as db:
        for day in range(6):
            reading = [SimpleNamespace(key="edr", status="partly", evidence=f"{day} of 20")]
            await rh.record_automatic(db, tenant, rh.snapshot(reading, [], [], []), NOW + timedelta(days=day))
        await db.commit()
        rows = await rh.history(db, tenant, "readiness", "edr")
    assert [r["detail"] for r in rows] == ["5 of 20", "4 of 20", "3 of 20"]

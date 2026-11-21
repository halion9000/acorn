"""Exporting one client's stored events as a zip with a manifest (real Postgres: AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL)."""

import hashlib
import io
import json
import os
import uuid
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import event_export as ep
from app.db.rls import set_rls_context
from app.services import event_store as es
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def test_the_manifest_lists_each_file_with_its_records_size_and_sha256_and_the_filters_used():
    data = ep.ndjson([{"b": 1, "a": 2}, {"x": "é"}])
    assert data == '{"a": 2, "b": 1}\n{"x": "é"}\n'.encode()
    assert ep.ndjson([]) == b""
    rows = [{"id": 1, "source": "halopsa", "kind": "ticket.created", "event_time": "2026-11-01T10:00:00+00:00", "pulled_at": "2026-11-02T00:00:00+00:00", "external_id": "t1", "payload": {"summary": "a, \"b\""}}]
    import csv as _csv

    back = list(_csv.reader(io.StringIO(ep.csv_of(rows).decode())))
    assert back[0] == ["id", "source", "kind", "event_time", "pulled_at", "external_id", "payload"] and back[1][:3] == ["1", "halopsa", "ticket.created"]
    assert json.loads(back[1][6]) == {"summary": 'a, "b"'}, "commas and quotes in the event survive a round trip through CSV"
    m = ep.manifest_for([("events.ndjson", data, 2)], "c1", {"source": "halopsa"}, NOW)
    assert m["files"] == [{"name": "events.ndjson", "records": 2, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}]
    assert m["total_records"] == 2 and m["client_id"] == "c1" and m["filters"] == {"source": "halopsa"} and m["generated_at"].startswith("2026-11-20")


PG_URL, APP_URL = os.environ.get("AISOC_TEST_PG_URL"), os.environ.get("AISOC_TEST_PG_APP_URL")
needs_pg = pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    a, client, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'ex', :s)"), {"i": a, "s": f"ex-{a.hex[:8]}"})
    yield SimpleNamespace(a=a, client=client, other=other, user=SimpleNamespace(tenant_id=a, user_id=None, email="staff@goliveoak.com"))
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("delete from audit_log where tenant_id = :t"), {"t": a})
        await conn.execute(text("delete from tenants where id = :t"), {"t": a})
    await engine.dispose()


async def with_db(tid, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            out = await work(db)
            await db.commit()
            return out
    finally:
        await engine.dispose()


def ev(i, client, **over):
    return {"source": "halopsa", "kind": "ticket.created", "event_time": f"2026-11-{i:02d}T10:00:00Z", "external_id": f"t{i}", "payload": {"summary": f"Ticket {i}"}, "client_id": str(client), **over}


@needs_pg
@pytest.mark.asyncio
async def test_the_export_is_a_zip_of_that_clients_events_with_a_manifest_that_checks_out_and_an_audit_entry(world):
    rows = [ev(1, world.client), ev(2, world.client, source="dialpad", kind="call.missed", external_id="c2"), ev(3, world.client), ev(4, world.other)]
    await with_db(world.a, lambda db: es.append_events(db, world.a, rows, NOW))

    async def run(**kw):
        args = {"source": None, "since": None, "until": None, **kw}
        return await with_db(world.a, lambda db: ep.export_client(None, world.user, db, client_id=str(world.client), format="ndjson", **args))

    res = await run()
    assert res.media_type == "application/zip" and "events-" in res.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(res.body))
    assert sorted(z.namelist()) == ["events.ndjson", "manifest.json"]
    events = [json.loads(line) for line in z.read("events.ndjson").decode().splitlines()]
    assert [e["external_id"] for e in events] == ["t1", "c2", "t3"], "only this client's events, oldest first"
    manifest = json.loads(z.read("manifest.json"))
    assert manifest["total_records"] == 3 and manifest["files"][0]["sha256"] == hashlib.sha256(z.read("events.ndjson")).hexdigest()
    only = await run(source="dialpad")
    assert [json.loads(line)["external_id"] for line in zipfile.ZipFile(io.BytesIO(only.body)).read("events.ndjson").decode().splitlines()] == ["c2"]
    ranged = await run(since=datetime(2026, 11, 2, tzinfo=UTC), until=datetime(2026, 11, 3, tzinfo=UTC))
    assert [json.loads(line)["external_id"] for line in zipfile.ZipFile(io.BytesIO(ranged.body)).read("events.ndjson").decode().splitlines()] == ["c2"]
    audited = (await with_db(world.a, lambda db: db.execute(text("select action, resource_id from audit_log where tenant_id = :t and action = 'events:exported'"), {"t": world.a}))).all()
    assert len(audited) == 3 and audited[0][1] == str(world.client)


@needs_pg
@pytest.mark.asyncio
async def test_an_export_that_is_too_large_is_refused_with_a_request_to_narrow_the_dates(world, monkeypatch):
    await with_db(world.a, lambda db: es.append_events(db, world.a, [ev(1, world.client), ev(2, world.client)], NOW))
    monkeypatch.setattr(ep, "MAX_EVENTS", 1)
    with pytest.raises(HTTPException) as e:
        await with_db(world.a, lambda db: ep.export_client(None, world.user, db, client_id=str(world.client), source=None, since=None, until=None, format="ndjson"))
    assert e.value.status_code == 413 and "shorter date range" in e.value.detail


@needs_pg
@pytest.mark.asyncio
async def test_the_export_can_be_csv_instead_of_ndjson_with_the_same_manifest(world):
    await with_db(world.a, lambda db: es.append_events(db, world.a, [ev(1, world.client), ev(2, world.client)], NOW))
    res = await with_db(world.a, lambda db: ep.export_client(None, world.user, db, client_id=str(world.client), source=None, since=None, until=None, format="csv"))
    z = zipfile.ZipFile(io.BytesIO(res.body))
    assert sorted(z.namelist()) == ["events.csv", "manifest.json"]
    manifest = json.loads(z.read("manifest.json"))
    assert manifest["files"][0]["name"] == "events.csv" and manifest["files"][0]["records"] == 2 and manifest["filters"]["format"] == "csv"
    assert manifest["files"][0]["sha256"] == hashlib.sha256(z.read("events.csv")).hexdigest()
    assert len(z.read("events.csv").decode().splitlines()) == 3

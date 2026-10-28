"""Compliance evidence is the caller's own unless a client is named, and only the caller's own clients can be named."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import compliance as c
from fastapi import HTTPException


class FakeDB:
    """Answers the client lookup with `managed` (the id found, or None) and records the statement."""

    def __init__(self, managed):
        self.managed = managed
        self.statements = []

    async def execute(self, statement, *a, **k):
        self.statements.append(str(statement.compile(compile_kwargs={"literal_binds": False})))
        return SimpleNamespace(scalar_one_or_none=lambda: self.managed)


def user():
    return SimpleNamespace(tenant_id=uuid.uuid4())


async def scope_of(db, u, client_id):
    gen = c.compliance_tenant(db=db, user=u, client_id=client_id)
    try:
        return await gen.__anext__()
    finally:
        await gen.aclose()


@pytest.mark.asyncio
async def test_with_no_client_named_it_is_the_callers_own_and_no_lookup_is_made():
    u, db = user(), FakeDB(None)
    assert await scope_of(db, u, None) == u.tenant_id
    assert await scope_of(db, u, u.tenant_id) == u.tenant_id
    assert db.statements == []


@pytest.mark.asyncio
async def test_a_client_of_the_caller_is_the_scope_and_the_lookup_is_limited_to_the_callers_clients():
    u, client = user(), uuid.uuid4()
    db = FakeDB(client)
    assert await scope_of(db, u, client) == client
    assert "parent_tenant_id" in db.statements[0]


@pytest.mark.asyncio
async def test_a_tenant_that_is_not_one_of_the_callers_clients_is_not_found():
    u, db = user(), FakeDB(None)
    with pytest.raises(HTTPException) as e:
        await scope_of(db, u, uuid.uuid4())
    assert e.value.status_code == 404


def test_every_endpoint_that_reads_or_writes_evidence_takes_the_client_scope():
    import inspect

    for name in (
        "trigger_evidence_collection",
        "collect_evidence",
        "list_evidence",
        "get_evidence",
        "review_evidence",
        "compliance_report",
    ):
        assert "tenant" in inspect.signature(getattr(c, name)).parameters, name

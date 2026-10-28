"""The MITRE heatmap can be limited to one client: that client's own alerts are read (never the knowledge graph or the other clients'), and a tenant that is not the caller's client is refused."""

from __future__ import annotations

import uuid
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import graph as ep
from app.services import mitre_from_alerts
from fastapi import HTTPException

OWNER, A, B = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _db(children):
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = [NS(id=c) for c in children]
    db.execute = AsyncMock(return_value=result)
    return db


@pytest.mark.asyncio
async def test_one_client_reads_only_that_clients_alerts_and_never_the_knowledge_graph(monkeypatch):
    seen = []

    async def observed(db, tenant_id, **kw):
        seen.append(tenant_id)
        return {"T1078": {"alerts": 3, "tactic": "Initial Access"}}

    monkeypatch.setattr(mitre_from_alerts, "observed_techniques", observed)
    monkeypatch.setattr(ep.graph_service, "get_mitre_coverage", AsyncMock(side_effect=AssertionError("the graph is not split by client")))
    out = await ep.get_mitre_coverage_compat(_db([A, B]), NS(tenant_id=OWNER), A)
    assert seen == [A]
    assert [(c.techniqueId, c.alerts) for c in out.cells] == [("T1078", 3)]


@pytest.mark.asyncio
async def test_without_a_client_it_is_the_callers_whole_estate_as_before(monkeypatch):
    graph = AsyncMock(return_value=[{"technique_id": "T1059", "name": "Command", "tactic": "Execution", "alert_count": 2}])
    monkeypatch.setattr(ep.graph_service, "get_mitre_coverage", graph)
    out = await ep.get_mitre_coverage_compat(_db([A]), NS(tenant_id=OWNER), None)
    graph.assert_awaited_once()
    assert [c.techniqueId for c in out.cells] == ["T1059"]


@pytest.mark.asyncio
async def test_a_tenant_that_is_not_the_callers_client_is_refused(monkeypatch):
    monkeypatch.setattr(ep.graph_service, "get_mitre_coverage", AsyncMock(return_value=[]))
    with pytest.raises(HTTPException) as e:
        await ep.get_mitre_coverage_compat(_db([A]), NS(tenant_id=OWNER), uuid.uuid4())
    assert e.value.status_code == 404

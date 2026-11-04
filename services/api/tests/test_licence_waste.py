"""Licence waste: what counts as waste, what is left out, and that it is quantities only."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

from app.services.licence_waste import waste_rows

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
A, B = uuid.uuid4(), uuid.uuid4()
NAMES = {A: "Acme", B: "Zed"}


def count(tenant, item, bought, available, unit="licence", days=0, source="m365"):
    return NS(tenant_id=tenant, source=source, item=item, unit=unit, count=bought, available=available, updated_at=NOW - timedelta(days=days))


def test_the_gap_between_bought_and_assigned_is_the_waste_biggest_first_with_its_share():
    rows = waste_rows([count(A, "Business Premium", 50, 5), count(B, "E3", 20, 12), count(A, "Exchange Online", 10, 1)], NAMES, NOW)
    assert [(r.client_name, r.item, r.bought, r.unassigned, r.percent) for r in rows] == [("Zed", "E3", 20, 12, 60), ("Acme", "Business Premium", 50, 5, 10), ("Acme", "Exchange Online", 10, 1, 10)]


def test_only_licences_with_a_stated_unassigned_number_above_the_minimum_count():
    rows = waste_rows(
        [count(A, "none stated", 10, None), count(A, "all used", 10, 0), count(A, "a device", 10, 4, unit="device"), count(A, "zero bought", 0, 0), count(A, "real", 10, 3)],
        NAMES,
        NOW,
    )
    assert [r.item for r in rows] == ["real"]
    assert waste_rows([count(A, "real", 10, 3)], NAMES, NOW, minimum=4) == []


def test_an_unassigned_number_above_what_was_bought_is_held_to_what_was_bought():
    assert waste_rows([count(A, "odd", 5, 9)], NAMES, NOW)[0].unassigned == 5


def test_a_count_not_refreshed_for_a_week_is_marked_stale():
    rows = waste_rows([count(A, "old", 10, 2, days=9), count(B, "new", 10, 2, days=1)], NAMES, NOW)
    assert {r.item: r.stale for r in rows} == {"old": True, "new": False}


def test_a_client_with_no_name_is_shown_by_its_id_and_a_naive_time_is_read_as_utc():
    r = waste_rows([NS(tenant_id=B, source="m", item="x", unit="licence", count=4, available=1, updated_at=datetime(2026, 11, 4, 11, 0))], {}, NOW)[0]
    assert r.client_name == str(B) and r.stale is False


def test_the_route_adds_the_rows_and_needs_the_billing_permission(monkeypatch):
    import app.api.v1.endpoints.billing as module

    monkeypatch.setattr(module, "_scope", AsyncMock(return_value=([uuid.uuid4(), A, B], NAMES)))
    monkeypatch.setattr(module, "_as", lambda db, owner, tid: contextlib.nullcontext())
    held = {A: [count(A, "Business Premium", 50, 5)], B: [count(B, "E3", 20, 12)]}
    calls = iter([held[A], held[B]])

    async def execute(_statement):
        out = MagicMock()
        out.scalars.return_value.all.return_value = next(calls)
        return out

    db = NS(execute=AsyncMock(side_effect=execute))
    out = asyncio.run(module.licence_waste(NS(tenant_id=uuid.uuid4()), db, 1, 500))
    assert (out.total_bought, out.total_unassigned, out.clients) == (70, 17, 2)
    assert [r.client_name for r in out.rows] == ["Zed", "Acme"]
    assert not any("price" in k or "cost" in k for k in out.rows[0].model_dump())

    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    assert set(required_permissions(found[("GET", "/billing/licence-waste")])) == {"billing:view"}

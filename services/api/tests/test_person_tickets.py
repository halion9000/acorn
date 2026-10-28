"""A person's recent tickets: what is accepted from CORE and what is stored."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import identities as ep
from pydantic import ValidationError

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
TENANT = uuid.uuid4()


def item(tid="1", **over):
    base = {"vendor_client_id": "5", "id": tid, "summary": "Printer is down", "opened_at": NOW - timedelta(days=2), "user_email": "Amy@Acme.com"}
    return ep.PersonTicketIn(**{**base, **over})


class FakeDB:
    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace()


def apply(monkeypatch, items, placed=None):
    from app.api.v1.endpoints import signins

    async def fake_targets(db, owner, report):
        return {TENANT: placed if placed is not None else report.items}, 1, 0, [SimpleNamespace(vendor_client_id="999", name="Gone Co", devices=1)]

    monkeypatch.setattr(signins, "targets_by_tenant", fake_targets)
    monkeypatch.setattr(ep, "acting_as_tenant", lambda db, tid: contextlib.nullcontext())
    db = FakeDB()
    out = asyncio.run(ep.apply_person_tickets(db, uuid.uuid4(), ep.PersonTicketsReport(vendor="halopsa", items=items), NOW))
    return out, db


def test_the_report_refuses_bad_vendors_oversized_lists_and_tickets_without_a_summary():
    assert ep.PersonTicketsReport(vendor="halopsa", items=[item()]).items[0].id == "1"
    for bad in ({"vendor": "Bad Vendor", "items": []}, {"vendor": "x", "items": [item()] * (ep.MAX_TICKETS + 1)}):
        with pytest.raises(ValidationError):
            ep.PersonTicketsReport(**bad)
    with pytest.raises(ValidationError):
        item(summary="")


def test_only_real_addresses_are_stored_once_each_and_the_unmapped_are_counted(monkeypatch):
    out, db = apply(monkeypatch, [item("1"), item("1"), item("2", user_email="not-an-address"), item("3", user_email="bo@acme.com")])
    assert (out.accepted, out.unmapped) == (2, 1)
    assert out.unmapped_clients[0].name == "Gone Co"
    # one upsert and one prune
    assert len(db.statements) == 2


def test_nothing_acceptable_means_no_upsert_but_old_tickets_are_still_pruned(monkeypatch):
    out, db = apply(monkeypatch, [item("2", user_email="not-an-address")])
    assert out.accepted == 0
    assert len(db.statements) == 1


def test_the_stored_row_has_the_address_lower_cased_and_the_zone_filled_in(monkeypatch):
    out, db = apply(monkeypatch, [item("7", opened_at=datetime(2026, 10, 20, 8, 0))])
    values = db.statements[0].compile().params
    assert "amy@acme.com" in values.values()
    assert any(isinstance(v, datetime) and v.tzinfo is not None for v in values.values())
    assert out.accepted == 1


def test_the_detail_carries_tickets_and_defaults_to_none():
    assert ep.PersonDetail.model_fields["tickets"].default_factory() == []
    t = ep.TicketBrief(id="9", summary="s", opened_at=NOW, source="halopsa")
    assert (t.status, t.url) == (None, None)

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
    base = {
        "vendor_client_id": "5",
        "id": tid,
        "summary": "Printer is down",
        "opened_at": NOW - timedelta(days=2),
        "user_email": "Amy@Acme.com",
    }
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
        return (
            {TENANT: placed if placed is not None else report.items},
            1,
            0,
            [SimpleNamespace(vendor_client_id="999", name="Gone Co", devices=1)],
        )

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


def test_the_latest_ten_sign_ins_come_newest_first_with_the_unusual_ones_marked():
    events = [
        SimpleNamespace(
            occurred_at=NOW - timedelta(hours=i),
            app="Outlook",
            country="US",
            city=None,
            ip_address="1.1.1.1",
            success=i % 2 == 0,
            mfa=True,
            anomaly_score=0.9 if i == 3 else None,
        )
        for i in range(14)
    ]
    rows = ep.signin_rows(list(reversed(events)))
    assert len(rows) == ep.SIGNINS_SHOWN == 10
    assert rows[0].at == NOW and rows[-1].at == NOW - timedelta(hours=9)
    assert [r.unusual for r in rows].index(True) == 3
    assert ep.signin_rows([]) == []


def test_the_detail_lists_default_to_empty_so_an_older_client_still_reads_it():
    d = ep.PersonDetail.model_fields
    assert d["recent_signins"].default_factory() == [] and d["changes"].default_factory() == []


def person(**over):
    base = {
        "key": "c:a@x.com",
        "client_id": uuid.uuid4(),
        "client_name": "Acme",
        "email": "a@x.com",
        "display_name": "Amy",
        "kind": "user",
        "enabled": True,
        "admin": False,
        "mfa": "covered",
        "tools": ["dropsuite", "cipp"],
        "open_alerts": 2,
    }
    return ep.PersonOut(**{**base, **over})


def test_the_people_csv_has_a_header_a_row_per_person_and_sorted_tools():
    import csv
    import io

    rows = list(csv.reader(io.StringIO(ep.people_csv([person(), person(email="b@x.com", enabled=None, admin=True, open_alerts=0)]))))
    assert rows[0] == ["Client", "Address", "Name", "Kind", "Enabled", "Administrator", "Multi-factor", "Known to", "Open alerts"]
    assert rows[1] == ["Acme", "a@x.com", "Amy", "user", "yes", "no", "covered", "cipp, dropsuite", "2"]
    assert rows[2][4:6] == ["", "yes"]


def test_a_name_that_would_run_as_a_spreadsheet_formula_is_made_text():
    import csv
    import io

    rows = list(csv.reader(io.StringIO(ep.people_csv([person(display_name='=HYPERLINK("http://evil","x")', client_name="+cmd")]))))
    assert rows[1][2].startswith("'=") and rows[1][0] == "'+cmd"


class FailingDB:
    def begin_nested(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, _stmt):
        raise RuntimeError('relation "person_tickets" does not exist')


class OneRowDB(FailingDB):
    async def execute(self, _stmt):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: ["row"]))


def test_a_section_an_older_database_cannot_read_is_empty_and_the_rest_of_the_panel_still_loads():
    assert asyncio.run(ep._tolerant(FailingDB(), object())) == []
    assert asyncio.run(ep._tolerant(OneRowDB(), object())) == ["row"]

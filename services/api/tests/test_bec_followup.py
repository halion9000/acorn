"""A BEC search a person starts also opens a case and a HaloPSA ticket, and the result is written on both whichever of "ticket number" and "result" arrives first."""

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest
from app.services import bec_followup as f

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
CLIENT = uuid.uuid4()
OWNER = uuid.uuid4()


class Rows:
    def __init__(self, first=None):
        self._first = first

    def scalars(self):
        return self

    def first(self):
        return self._first


class FakeDB:
    """Records what is added and what raw SQL runs; `halo` is what the client-mapping lookup answers, `bec` what the search lookup answers."""

    def __init__(self, halo=None, bec=None, boom=False):
        self.halo, self.bec, self.boom = halo, bec, boom
        self.added, self.sql = [], []

    def begin_nested(self):
        db = self

        class Ctx:
            async def __aenter__(self):
                return db

            async def __aexit__(self, *a):
                return False

        return Ctx()

    async def execute(self, stmt, params=None):
        if self.boom:
            raise RuntimeError("database down")
        if params is not None:
            self.sql.append((str(stmt), params))
            return Rows()
        return Rows(self.halo if self.halo is not None else self.bec)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


def bec(**over):
    base = dict(id=uuid.uuid4(), tenant_id=CLIENT, case_ref="BEC-1", email="p@x.com", status="pending", message=None, summary={}, report=None, aisoc_case_id=None, ticket_id=None, ticket_note_queued=False)
    base.update(over)
    return NS(**base)


def run(coro):
    return asyncio.run(coro)


def test_a_finished_search_is_worded_from_ciphers_own_rating_and_never_calls_low_clean():
    high = f.result_text(
        case_ref="BEC-1", email="p@x.com", status="done", message=None, summary={"level": "High", "score": 80, "incomplete": ["Sign-ins"]}, report={"NewRules": [1, 2], "AddedApps": [1]}
    )
    assert "CIPP rates it High (score 80)" in high and "2 new inbox rules" in high and "1 added app" in high and "Sign-ins" in high
    low = f.result_text(case_ref="BEC-1", email="p@x.com", status="done", message=None, summary={"level": "Low"}, report={})
    assert "None of the lists" in low and "clean" not in low.lower()
    failed = f.result_text(case_ref="BEC-1", email="p@x.com", status="failed", message="CIPP timed out", summary={}, report=None)
    assert "did not finish" in failed and "CIPP timed out" in failed


def test_the_case_severity_only_rises_to_cipps_high_or_medium():
    assert f.case_severity({"level": "High"}) == "high" and f.case_severity({"level": "medium"}) == "medium"
    assert f.case_severity({"level": "Low"}) == "medium" and f.case_severity({}) == "medium"


def test_starting_opens_one_case_and_queues_one_ticket_request_for_the_mapped_halo_client():
    b, db = bec(), FakeDB(halo="123")
    run(f.open_followup(db, owner_id=OWNER, client_id=CLIENT, bec=b, requested_by_name="hal@x.com", now=NOW))
    assert b.aisoc_case_id is not None and len(db.sql) == 1 and "INSERT INTO aisoc_cases" in db.sql[0][0]
    (a,) = db.added
    assert a.action == "create_ticket" and a.vendor == "core" and a.alert_id is None and a.incident_uid == f"bec-ticket:{b.id}"
    assert a.params["halo_client_id"] == "123" and a.params["summary"] == "BEC search: p@x.com" and "hal@x.com" in a.params["details"]


def test_a_search_for_a_client_with_no_halo_mapping_still_gets_its_ticket_request_without_a_client():
    db = FakeDB(halo=None)
    run(f.open_followup(db, owner_id=OWNER, client_id=CLIENT, bec=bec(), requested_by_name=None, now=NOW))
    assert "halo_client_id" not in db.added[0].params


def test_a_failure_opening_the_paperwork_never_stops_the_search():
    b, db = bec(), FakeDB(boom=True)
    run(f.open_followup(db, owner_id=OWNER, client_id=CLIENT, bec=b, requested_by_name="x", now=NOW))  # does not raise
    assert db.added == []


def test_a_result_that_arrives_after_the_ticket_number_is_written_on_the_ticket_once():
    b, db = bec(status="done", summary={"level": "High"}, ticket_id="9001", aisoc_case_id=uuid.uuid4(), report={}), FakeDB()
    run(f.on_result(db, b, NOW))
    run(f.on_result(db, b, NOW))
    notes = [a for a in db.added if a.action == "ticket_note"]
    assert len(notes) == 1 and notes[0].params["ticket_ids"] == ["9001"] and "High" in notes[0].params["note"] and b.ticket_note_queued
    assert any("UPDATE aisoc_cases" in s for s, _ in db.sql)


def test_a_result_that_arrives_before_the_ticket_number_waits_and_the_number_then_triggers_the_note():
    b = bec(status="done", summary={"level": "High"}, aisoc_case_id=uuid.uuid4(), report={})
    db = FakeDB(bec=b)
    run(f.on_result(db, b, NOW))
    assert [a for a in db.added if a.action == "ticket_note"] == [] and not b.ticket_note_queued
    assert run(f.on_ticket_created(db, CLIENT, f"bec-ticket:{b.id}", "9002", NOW)) is True
    (note,) = [a for a in db.added if a.action == "ticket_note"]
    assert note.params["ticket_ids"] == ["9002"] and b.ticket_id == "9002" and b.ticket_note_queued


def test_a_ticket_number_for_a_search_still_running_is_only_remembered():
    b = bec(status="running")
    db = FakeDB(bec=b)
    assert run(f.on_ticket_created(db, CLIENT, f"bec-ticket:{b.id}", "9003", NOW)) is True
    assert b.ticket_id == "9003" and db.added == [] and not b.ticket_note_queued


@pytest.mark.parametrize("uid", ["alert-ticket:abc", "bec-ticket:not-a-uuid", ""])
def test_a_ticket_that_is_not_for_a_search_is_ignored(uid):
    db = FakeDB()
    assert run(f.on_ticket_created(db, CLIENT, uid, "1", NOW)) is False and db.added == []


def test_a_failed_search_writes_its_failure_on_the_ticket_too():
    b, db = bec(status="failed", message="CIPP timed out", ticket_id="9004"), FakeDB()
    run(f.on_result(db, b, NOW))
    (note,) = [a for a in db.added if a.action == "ticket_note"]
    assert "did not finish" in note.params["note"]

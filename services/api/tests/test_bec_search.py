"""Business email compromise searches: what a click queues, what an alert queues by itself and the limits on that, and what CORE's reports do to a case."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import identity_bec as ep
from app.services import bec_auto
from fastapi import HTTPException

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
OWNER, CLIENT = uuid.uuid4(), uuid.uuid4()
USER = NS(tenant_id=OWNER, user_id=uuid.uuid4(), email="hal@liveoak.example")


def run(coro):
    return asyncio.run(coro)


class Db:
    """Answers the queries in the order they are asked (each scripted answer is one scalar) and keeps what is added."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.added = []
        self.commits = 0
        self.execute = AsyncMock(side_effect=self._execute)

    async def _execute(self, *_a, **_k):
        value = self.answers.pop(0) if self.answers else None
        out = MagicMock()
        out.scalar_one_or_none.return_value = value
        out.scalar_one.return_value = value
        out.scalars.return_value.all.return_value = value if isinstance(value, list) else []
        return out

    def begin_nested(self):
        return contextlib.nullcontext()

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


# ---- the button ---------------------------------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def wired(monkeypatch):
    person = NS(tenant_id=CLIENT, email="pat@acme.com", addresses=["pat@acme.com"], sources=[NS(vendor="cipp", external_id="entra-guid-1")])
    monkeypatch.setattr(ep, "_scope", AsyncMock(return_value=([CLIENT], {CLIENT: "Acme"})))
    monkeypatch.setattr(ep, "_as", lambda db, owner, tid: contextlib.nullcontext())
    monkeypatch.setattr(ep, "_people", AsyncMock(return_value=([person], {})))
    monkeypatch.setattr(ep, "cipp_customer", AsyncMock(return_value="cipp-cust-1"))
    audit = AsyncMock()
    monkeypatch.setattr(ep, "emit_audit", audit)
    return audit


def start(db, **over):
    body = {"client_id": CLIENT, "email": "pat@acme.com", "confirm": True, **over}
    return run(ep.start_bec_search(ep.StartBody(**body), MagicMock(), USER, db))


def test_a_confirmed_start_records_the_case_and_queues_it_for_core_with_the_ids_cipp_needs(wired):
    db = Db([[]])  # no search already running
    item = start(db)
    assert item.status == "pending" and item.email == "pat@acme.com" and item.case_ref.startswith("BEC-")
    case, action = db.added
    assert (case.tenant_id, case.requested_by, case.status) == (CLIENT, USER.user_id, "pending")
    assert (action.vendor, action.action, action.status, action.alert_id) == ("core", "bec_search", "pending", None)
    assert action.params["client_id"] == "cipp-cust-1" and action.params["user_id"] == "entra-guid-1" and action.params["user"] == "pat@acme.com"
    assert action.params["case_id"] == str(case.id) and action.incident_uid == f"bec:{case.id}"
    assert db.commits == 1 and wired.await_args.kwargs["action"] == "identities:bec_requested"


def test_nothing_is_queued_without_the_confirmation(wired):
    db = Db()
    with pytest.raises(HTTPException) as e:
        start(db, confirm=False)
    assert e.value.status_code == 422 and db.added == []


def test_a_person_microsoft_does_not_know_a_client_not_in_cipp_and_a_running_search_are_all_refused(wired, monkeypatch):
    with pytest.raises(HTTPException) as e:
        start(Db(), email="nobody@acme.com")
    assert e.value.status_code == 409
    monkeypatch.setattr(ep, "cipp_customer", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as e:
        start(Db([[]]))
    assert e.value.status_code == 409 and "CIPP" in e.value.detail
    monkeypatch.setattr(ep, "cipp_customer", AsyncMock(return_value="c"))
    with pytest.raises(HTTPException) as e:
        start(Db([[NS(id=uuid.uuid4())]]))
    assert e.value.status_code == 409 and "already running" in e.value.detail


def test_the_owners_own_tenant_is_not_a_client_to_search(wired):
    with pytest.raises(HTTPException) as e:
        start(Db(), client_id=OWNER)
    assert e.value.status_code == 422


def test_an_open_case_nobody_reports_on_shows_as_failed_not_running_for_ever():
    row = NS(status="running", updated_at=NOW - timedelta(minutes=40), message=None)
    assert ep.effective_status(row, NOW) == ("failed", "CORE stopped reporting on this search (it may have been restarted). Start it again.")
    fresh = NS(status="running", updated_at=NOW - timedelta(minutes=2), message=None)
    assert ep.effective_status(fresh, NOW) == ("running", None)
    done = NS(status="done", updated_at=NOW - timedelta(days=3), message="finished")
    assert ep.effective_status(done, NOW) == ("done", "finished")


def test_the_routes_need_the_bec_permission_and_nothing_else_reads_a_report():
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    for key in (("POST", "/identities/bec"), ("GET", "/identities/bec"), ("GET", "/identities/bec/{case_id}")):
        assert set(required_permissions(found[key])) == {"identities:bec"}, key


# ---- the automatic start ------------------------------------------------------------------------------------------------------------------------------------


def finding(rule="aisoc-id-impossible-travel", severity="high", users=("Pat@Acme.com",)):
    return NS(rule_id=rule, severity=severity, users=list(users))


def test_only_high_or_critical_findings_of_account_takeover_rules_name_people_to_check_each_once_and_in_lowercase():
    found = [finding(), finding(users=("pat@acme.com", "eve@acme.com", "third@acme.com")), finding(severity="medium"), finding(rule="aisoc-id-legacy-protocol"), finding(users=("not an address",))]
    assert bec_auto.people_to_check(found) == ["pat@acme.com", "eve@acme.com"]


SETTINGS = NS(BEC_AUTO_ENABLED=True, BEC_AUTO_PER_CLIENT_PER_DAY=3, BEC_AUTO_PER_DAY=15)


@pytest.fixture
def plain(monkeypatch):
    import app.db.rls_scope as rls

    monkeypatch.setattr(rls, "cross_tenant_reads", lambda db: contextlib.nullcontext())


def test_a_new_takeover_alert_queues_a_search_for_the_person_with_no_asker_named_as_automatic(plain):
    # answers in order: owner, cipp customer, searches today (all), searches today (this client), recent for pat, microsoft id of pat
    db = Db([OWNER, "cipp-cust-1", 0, 0, 0, "entra-guid-1"])
    assert run(bec_auto.auto_bec(db, CLIENT, [finding()], SETTINGS, NOW)) == 1
    case, action = db.added
    assert case.requested_by is None and case.email == "pat@acme.com"
    assert action.params["requested_by_name"].startswith("A.C.O.R.N (automatic")


def test_it_does_nothing_when_switched_off_for_the_owners_own_tenant_when_the_client_is_not_in_cipp_or_the_person_is_unknown(plain):
    off = NS(BEC_AUTO_ENABLED=False, BEC_AUTO_PER_CLIENT_PER_DAY=3, BEC_AUTO_PER_DAY=15)
    assert run(bec_auto.auto_bec(Db(), CLIENT, [finding()], off, NOW)) == 0
    assert run(bec_auto.auto_bec(Db([None]), CLIENT, [finding()], SETTINGS, NOW)) == 0  # no owner above it
    no_cipp = Db([OWNER, None])
    assert run(bec_auto.auto_bec(no_cipp, CLIENT, [finding()], SETTINGS, NOW)) == 0 and no_cipp.added == []
    unknown = Db([OWNER, "c", 0, 0, 0, None])
    assert run(bec_auto.auto_bec(unknown, CLIENT, [finding()], SETTINGS, NOW)) == 0 and unknown.added == []


def test_a_person_searched_in_the_last_day_is_not_searched_again(plain):
    db = Db([OWNER, "c", 0, 0, 1])
    assert run(bec_auto.auto_bec(db, CLIENT, [finding()], SETTINGS, NOW)) == 0 and db.added == []


def test_the_per_client_and_per_day_limits_stop_it(plain):
    for answers in ([OWNER, "c", 0, 3], [OWNER, "c", 15, 0]):
        db = Db(answers + [0, "guid"])
        assert run(bec_auto.auto_bec(db, CLIENT, [finding()], SETTINGS, NOW)) == 0 and db.added == [], answers


def test_a_failure_while_queuing_never_escapes(plain):
    db = Db([OWNER, "c", 0, 0, 0, "guid"])
    db.add = MagicMock(side_effect=RuntimeError("boom"))
    assert run(bec_auto.auto_bec(db, CLIENT, [finding()], SETTINGS, NOW)) == 0


# ---- what CORE's reports do to a case ----------------------------------------------------------------------------------------------------------------------

from app.api.v1.endpoints import inbox_core_feed as feed  # noqa: E402


@pytest.fixture
def core(monkeypatch):
    case = NS(id=uuid.uuid4(), case_ref="BEC-1", email="pat@acme.com", status="pending", step=0, steps_total=0, step_label=None, message=None, report=None, summary={}, updated_at=NOW - timedelta(minutes=1), finished_at=None)
    monkeypatch.setattr(feed, "_verify_core_feed_token", AsyncMock(return_value=OWNER))
    monkeypatch.setattr(feed, "adopt_tenant", AsyncMock())
    monkeypatch.setattr(feed, "_bec_case_for", AsyncMock(return_value=(case, CLIENT)))
    monkeypatch.setattr(feed, "acting_as_tenant", lambda db, tid: contextlib.nullcontext())
    db = Db()
    return case, db


def test_progress_marks_the_case_running_and_records_the_step_and_label(core):
    case, db = core
    out = run(feed.report_bec_progress("tok", case.id, feed.BecProgress(step=3, steps_total=15, label="Sign-ins and mobile devices"), db))
    assert out.recorded and case.status == "running" and (case.step, case.steps_total, case.step_label) == (3, 15, "Sign-ins and mobile devices")
    assert db.commits == 1


def test_a_result_stores_the_whole_report_and_finishes_the_case(core):
    case, db = core
    report = {"Score": 3, "MailboxRules": []}
    run(feed.report_bec_result("tok", case.id, feed.BecResult(status="done", message="CIPP finished", report=report, summary={"sections": ["Score"]}), db))
    assert (case.status, case.report, case.summary, case.finished_at is not None) == ("done", report, {"sections": ["Score"]}, True)


def test_a_high_rating_from_cipp_saves_an_alert_for_that_person_and_the_report_is_kept_either_way(core, monkeypatch):
    case, db = core
    saved = []

    async def fake_save(db_, tenant_id, findings, now=None):
        saved.append((tenant_id, findings))
        return len(findings)

    monkeypatch.setattr("app.services.identity_detections.save_findings", fake_save)
    summary = {"score": 9, "level": "High", "incomplete": ["SignIns"]}
    run(feed.report_bec_result("tok", case.id, feed.BecResult(status="done", report={"Score": {"Value": 9, "Level": "High"}}, summary=summary), db))
    assert case.status == "done" and db.commits == 1
    assert len(saved) == 1 and saved[0][0] == CLIENT
    finding = saved[0][1][0]
    assert (finding.severity, finding.users, finding.key) == ("high", ["pat@acme.com"], str(case.id))


def test_a_low_rating_or_a_failed_search_saves_no_alert(core, monkeypatch):
    case, db = core
    saved = []

    async def fake_save(*a, **k):
        saved.append(a)
        return 1

    monkeypatch.setattr("app.services.identity_detections.save_findings", fake_save)
    run(feed.report_bec_result("tok", case.id, feed.BecResult(status="done", report={"Score": {"Value": 1, "Level": "Low"}}, summary={"level": "Low", "score": 1}), db))
    assert saved == [] and case.status == "done"


def test_an_odd_summary_or_a_failure_making_the_alert_never_loses_the_report(core, monkeypatch):
    case, db = core

    async def boom(*a, **k):
        raise RuntimeError("database trouble")

    monkeypatch.setattr("app.services.identity_detections.save_findings", boom)
    run(feed.report_bec_result("tok", case.id, feed.BecResult(status="done", report={"Score": {"Level": "High"}}, summary={"level": "High", "incomplete": 5, "score": "nine"}), db))
    assert case.status == "done" and case.report == {"Score": {"Level": "High"}} and db.commits == 1


def test_a_failed_result_keeps_the_reason_and_no_report(core):
    case, db = core
    run(feed.report_bec_result("tok", case.id, feed.BecResult(status="failed", message="CIPP returned 403"), db))
    assert case.status == "failed" and case.message == "CIPP returned 403" and case.report is None


def test_a_finished_case_or_an_unknown_one_cannot_be_answered_again(core, monkeypatch):
    case, db = core
    case.status = "done"
    for call in (
        lambda: feed.report_bec_progress("tok", case.id, feed.BecProgress(step=1), db),
        lambda: feed.report_bec_result("tok", case.id, feed.BecResult(status="failed"), db),
    ):
        with pytest.raises(HTTPException) as e:
            run(call())
        assert e.value.status_code == 404
    assert case.status == "done"
    monkeypatch.setattr(feed, "_bec_case_for", AsyncMock(return_value=(None, None)))
    with pytest.raises(HTTPException) as e:
        run(feed.report_bec_progress("tok", uuid.uuid4(), feed.BecProgress(step=1), db))
    assert e.value.status_code == 404


def test_an_oversized_report_is_refused_before_anything_is_stored(core, monkeypatch):
    case, db = core
    monkeypatch.setattr(feed, "MAX_BEC_REPORT_BYTES", 100)
    with pytest.raises(HTTPException) as e:
        run(feed.report_bec_result("tok", case.id, feed.BecResult(status="done", report={"x": "y" * 500}), db))
    assert e.value.status_code == 413 and case.status == "pending" and db.commits == 0


def test_an_oversized_summary_is_refused_too_so_the_glance_line_cannot_hold_a_second_report(core, monkeypatch):
    case, db = core
    monkeypatch.setattr(feed, "MAX_BEC_SUMMARY_BYTES", 100)
    with pytest.raises(HTTPException) as e:
        run(feed.report_bec_result("tok", case.id, feed.BecResult(status="done", report={"a": 1}, summary={"x": "y" * 500}), db))
    assert e.value.status_code == 413 and case.status == "pending" and db.commits == 0

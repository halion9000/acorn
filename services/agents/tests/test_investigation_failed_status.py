"""An investigation whose step raised must be reported as failed, not as a green "completed" with nothing in it (and without leaking the error text)."""

import asyncio
from types import SimpleNamespace

from app.api import investigate as inv

RUN = "11111111-1111-1111-1111-111111111111"
SECRET = "psycopg2 password authentication failed for user aisoc_app at 10.9.8.7"


def run_with(monkeypatch, state):
    async def stream(**_kwargs):
        yield {"type": "step", "agent": "recon", "summary": "looked"}
        yield {"type": "done", "state": state}

    monkeypatch.setattr(inv, "_investigate_stream", stream)
    inv._runs[RUN] = {"status": "running", "started_at": "t", "alert_id": "a1"}

    async def go():
        await inv._run_and_store(RUN, "case-1", inv.InvestigateRequest(alert_summary="s", tenant_id="t1"))

    async def no_emit(*_a, **_k):
        return None

    monkeypatch.setattr(inv, "_emit_event", no_emit)
    asyncio.run(go())
    return inv._runs[RUN]


def test_a_run_that_ended_in_a_failed_state_is_failed_with_its_error_kept_internally(monkeypatch):
    run = run_with(monkeypatch, {"status": "failed", "error": SECRET, "report_md": ""})
    assert run["status"] == "failed" and run["error"] == SECRET


def test_a_run_that_finished_is_completed_with_its_report(monkeypatch):
    run = run_with(monkeypatch, {"status": "completed", "report_md": "# done", "error": None})
    assert run["status"] == "completed" and run["error"] is None and run["report_md"] == "# done"


def test_a_failed_run_with_no_error_text_still_says_something_and_is_failed(monkeypatch):
    run = run_with(monkeypatch, {"status": "failed"})
    assert run["status"] == "failed" and run["error"]


def test_the_poll_answer_for_a_failed_run_is_generic_and_leaks_none_of_the_errors_text(monkeypatch):
    run_with(monkeypatch, {"status": "failed", "error": SECRET})
    monkeypatch.setattr(inv, "visible_run", lambda run, _request, _msg: run)
    out = asyncio.run(inv.get_agent_investigation(RUN, SimpleNamespace()))
    assert out.status == "failed" and out.error == inv.FAILED_INVESTIGATION_MESSAGE
    for leaked in ("10.9.8.7", "aisoc_app", "password", "psycopg2"):
        assert leaked not in out.model_dump_json()


def test_the_poll_answer_for_a_completed_run_has_no_error(monkeypatch):
    run_with(monkeypatch, {"status": "completed", "report_md": "r"})
    monkeypatch.setattr(inv, "visible_run", lambda run, _request, _msg: run)
    out = asyncio.run(inv.get_agent_investigation(RUN, SimpleNamespace()))
    assert out.status == "completed" and out.error is None and out.findings == "r"

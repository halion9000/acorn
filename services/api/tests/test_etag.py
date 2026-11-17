"""ETag and If-None-Match for the fleet boards: the tag ignores what changes on every call, a repeat of the same answer is a 304, and a changed answer is a new tag."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.api.v1.endpoints.client_posture import FleetBoardOut, FleetBoardRow, conditional
from app.services.etag import not_modified, payload_etag
from fastapi import Response


def test_the_tag_ignores_generated_at_and_key_order_but_not_a_real_change():
    a = {"generated_at": "2026-11-16T10:00:00Z", "clients": [{"id": 1, "score": 80}], "average_score": 80}
    b = {"average_score": 80, "clients": [{"score": 80, "id": 1}], "generated_at": "2026-11-16T10:05:00Z"}
    c = {**a, "clients": [{"id": 1, "score": 81}]}
    assert payload_etag(a) == payload_etag(b)
    assert payload_etag(a) != payload_etag(c)
    assert payload_etag(a).startswith('W/"') and payload_etag(a).endswith('"')


def test_a_browser_that_holds_this_version_gets_a_304_whatever_the_form_of_its_header():
    tag = payload_etag({"x": 1})
    assert not_modified(tag, tag)
    assert not_modified(tag.removeprefix("W/"), tag)
    assert not_modified(f'"other", {tag}', tag)
    assert not_modified("*", tag)
    assert not not_modified('W/"different"', tag)
    assert not not_modified(None, tag) and not not_modified("", tag)


def _board(evidence: str) -> FleetBoardOut:
    row = FleetBoardRow(
        client_id=uuid.UUID(int=7), client_name="Acme", source="ninjaone", key="k", status="not_met", evidence=evidence, since=None, accepted=False, items=[],
        owner=None, due_date=None, overdue=False, raises_alerts=False,
    )
    return FleetBoardOut(board="b", title="T", keys=["k"], rows=[row])


def test_the_endpoint_answer_carries_a_tag_and_a_repeat_with_it_is_an_empty_304_while_a_change_is_answered_in_full():
    out = _board("3 failing")
    first = Response()
    sent = conditional(SimpleNamespace(headers={}), first, out)
    assert sent is out and first.headers["etag"].startswith('W/"') and first.headers["cache-control"] == "private, no-cache"
    again = conditional(SimpleNamespace(headers={"if-none-match": first.headers["etag"]}), Response(), out)
    assert isinstance(again, Response) and again.status_code == 304 and again.body == b"" and again.headers["etag"] == first.headers["etag"]
    changed = _board("4 failing")
    full = conditional(SimpleNamespace(headers={"if-none-match": first.headers["etag"]}), Response(), changed)
    assert full is changed, "a different answer is sent in full even to a browser holding the old tag"
    assert datetime.now(UTC)  # (the board has no generated_at; the summary's is left out of its tag)


def test_called_without_a_request_the_plain_answer_comes_back():
    out = _board("x")
    assert conditional(None, None, out) is out


def test_through_a_real_route_with_the_same_parameters_a_second_request_with_the_tag_is_a_304():
    from app.api.v1.endpoints.client_posture import conditional as cond
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient

    app = FastAPI()
    state = {"evidence": "3 failing"}

    @app.get("/board", response_model=FleetBoardOut)
    async def board(request: Request = None, response: Response = None):  # type: ignore[assignment]  # the same shape as the real endpoints
        return cond(request, response, _board(state["evidence"]))

    client = TestClient(app)
    first = client.get("/board")
    assert first.status_code == 200 and first.json()["rows"][0]["evidence"] == "3 failing"
    tag = first.headers["etag"]
    assert first.headers["cache-control"] == "private, no-cache"
    again = client.get("/board", headers={"If-None-Match": tag})
    assert again.status_code == 304 and again.content == b"" and again.headers["etag"] == tag
    state["evidence"] = "4 failing"
    fresh = client.get("/board", headers={"If-None-Match": tag})
    assert fresh.status_code == 200 and fresh.json()["rows"][0]["evidence"] == "4 failing" and fresh.headers["etag"] != tag

"""Every answer carries an ``X-Request-ID`` and the slow-request log names it, so a reported error can be matched to one log line."""

import re

from app.main import log_if_slow, request_id_for
from fastapi.testclient import TestClient


def test_a_plain_caller_id_is_kept_and_anything_else_is_replaced():
    assert request_id_for("abc-123_X.9") == "abc-123_X.9"
    for bad in (None, "", "   ", "has space", "x" * 65, "bad\nline", "semi;colon", "<script>"):
        got = request_id_for(bad)
        assert re.fullmatch(r"[0-9a-f]{32}", got), bad
    assert request_id_for(None) != request_id_for(None)


def test_the_slow_log_carries_the_id(monkeypatch):
    seen = {}
    monkeypatch.setattr("app.main.logger.warning", lambda event, **kw: seen.update(event=event, **kw))
    assert log_if_slow("GET", "/x", 200, 5.0, threshold=1.0, request_id="rid-1")
    assert seen["request_id"] == "rid-1"


def test_the_answer_carries_the_callers_id_or_a_new_one():
    from app.main import app

    c = TestClient(app)
    assert c.get("/health", headers={"X-Request-ID": "mine-1"}).headers["X-Request-ID"] == "mine-1"
    assert re.fullmatch(r"[0-9a-f]{32}", c.get("/health").headers["X-Request-ID"])

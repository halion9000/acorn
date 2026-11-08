"""The API-wide limit (A19): log-only by default, 429 only when enforced, never on the CORE feed or health routes, and never naming a caller."""

import pytest
from app.core import api_rate_limit as rl
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(rl, "window", rl.SlidingWindow())
    monkeypatch.setattr(rl, "tally", rl.Tally())
    monkeypatch.delenv("AISOC_RATE_LIMIT_MODE", raising=False)
    monkeypatch.setenv("AISOC_RATE_LIMIT_PER_MINUTE", "3")
    monkeypatch.delenv("AISOC_RATE_LIMIT_EXEMPT_KEY_HASHES", raising=False)


def app():
    a = FastAPI()
    a.add_middleware(rl.RateLimitMiddleware)

    @a.get("/api/v1/things")
    def things():
        return {"ok": True}

    @a.post("/api/v1/inbox/core-feed/tok/status")
    def feed():
        return {"ok": True}

    @a.get("/health")
    def health():
        return {"ok": True}

    return a


def codes(client, path, n, **kw):
    return [client.get(path, **kw).status_code for _ in range(n)]


def test_the_default_mode_is_log_only_so_nothing_is_ever_refused_but_the_excess_is_counted():
    assert rl.mode() == "log"
    c = TestClient(app())
    assert codes(c, "/api/v1/things", 6, headers={"Authorization": "Bearer a"}) == [200] * 6
    snap = rl.tally.snapshot()
    assert snap["checked"] == 6 and snap["over_limit"] == 3 and snap["callers_over_limit"] == 1


def test_enforce_mode_refuses_the_caller_over_the_limit_with_retry_after_and_leaves_another_caller_alone(monkeypatch):
    monkeypatch.setenv("AISOC_RATE_LIMIT_MODE", "enforce")
    c = TestClient(app())
    assert codes(c, "/api/v1/things", 5, headers={"Authorization": "Bearer a"}) == [200, 200, 200, 429, 429]
    r = c.get("/api/v1/things", headers={"Authorization": "Bearer a"})
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    assert c.get("/api/v1/things", headers={"Authorization": "Bearer b"}).status_code == 200


def test_the_core_feed_and_health_are_never_limited_even_when_enforcing(monkeypatch):
    monkeypatch.setenv("AISOC_RATE_LIMIT_MODE", "enforce")
    c = TestClient(app())
    assert codes(c, "/health", 10) == [200] * 10
    assert [c.post("/api/v1/inbox/core-feed/tok/status").status_code for _ in range(10)] == [200] * 10
    assert rl.tally.snapshot()["checked"] == 0


def test_a_key_listed_as_exempt_is_never_limited_and_off_mode_counts_nothing(monkeypatch):
    monkeypatch.setenv("AISOC_RATE_LIMIT_MODE", "enforce")
    key = rl.caller_key("Bearer agents", None, None)[2:]
    monkeypatch.setenv("AISOC_RATE_LIMIT_EXEMPT_KEY_HASHES", f"x, {key}")
    c = TestClient(app())
    assert codes(c, "/api/v1/things", 6, headers={"Authorization": "Bearer agents"}) == [200] * 6
    monkeypatch.setenv("AISOC_RATE_LIMIT_MODE", "off")
    assert codes(c, "/api/v1/things", 6, headers={"Authorization": "Bearer other"}) == [200] * 6
    assert rl.tally.snapshot()["checked"] == 0


def test_the_window_slides_so_a_caller_is_free_again_after_a_minute():
    w = rl.SlidingWindow()
    assert [w.hit("k", t) for t in (0.0, 1.0, 2.0)] == [1, 2, 3]
    assert w.hit("k", 30.0) == 4
    assert w.hit("k", 61.5) == 3, "the first two hits are more than a minute old"


def test_callers_are_keyed_by_a_hash_never_the_token_and_by_address_when_unsigned():
    k = rl.caller_key("Bearer secret-token", None, "1.2.3.4")
    assert k.startswith("k:") and "secret-token" not in k and len(k) == 18
    assert rl.caller_key(None, "9.9.9.9, 10.0.0.1", "1.2.3.4") == "ip:9.9.9.9"
    assert rl.caller_key(None, None, "1.2.3.4") == "ip:1.2.3.4" and rl.caller_key(None, None, None) == "ip:unknown"


def test_a_bad_setting_falls_back_to_the_safe_default(monkeypatch):
    monkeypatch.setenv("AISOC_RATE_LIMIT_MODE", "banana")
    monkeypatch.setenv("AISOC_RATE_LIMIT_PER_MINUTE", "-5")
    assert rl.mode() == "log" and rl.per_minute() == rl.DEFAULT_PER_MINUTE


def test_the_table_of_callers_cannot_grow_without_bound(monkeypatch):
    monkeypatch.setattr(rl, "MAX_TRACKED_CALLERS", 10)
    w = rl.SlidingWindow()
    for i in range(50):
        w.hit(f"ip:{i}", float(i) / 100)
    assert len(w._hits) <= 10

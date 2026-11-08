"""CORE may send its feed token in a header; the path then carries only a placeholder."""

import asyncio

from app.core import core_feed_token as m

TOKEN = "abcDEF0123456789_-abcDEF0123456789"


def test_the_header_token_replaces_the_placeholder_and_nothing_else_is_touched():
    p = "/api/v1/inbox/core-feed/_/sync-requests/claim"
    assert m.rewritten_path(p, TOKEN) == f"/api/v1/inbox/core-feed/{TOKEN}/sync-requests/claim"
    assert m.rewritten_path(p, None) is None
    assert m.rewritten_path(p, "short") is None
    assert m.rewritten_path(p, "has space in it 0123456789") is None
    assert m.rewritten_path(f"/api/v1/inbox/core-feed/{TOKEN}/status", TOKEN) is None, "the old form is left alone"
    assert m.rewritten_path("/api/v1/alerts/_/x", TOKEN) is None, "only the CORE feed routes"


def _run(path, headers):
    seen = {}

    async def app(scope, receive, send):
        seen["scope"] = scope

    original = {"type": "http", "path": path, "raw_path": path.encode(), "headers": headers}
    asyncio.run(m.CoreFeedTokenMiddleware(app)({**original}, None, None))
    return original, seen["scope"]


def test_the_router_sees_the_real_path_while_the_original_request_keeps_the_placeholder():
    original, routed = _run("/api/v1/inbox/core-feed/_/status", [(b"x-core-feed-token", TOKEN.encode())])
    assert routed["path"] == f"/api/v1/inbox/core-feed/{TOKEN}/status"
    assert routed["raw_path"] == routed["path"].encode()
    assert original["path"] == "/api/v1/inbox/core-feed/_/status", "what the servers log never holds the secret"


def test_without_a_usable_header_the_path_is_unchanged_and_other_routes_pass_through():
    _, routed = _run("/api/v1/inbox/core-feed/_/status", [])
    assert routed["path"].endswith("/_/status")
    _, other = _run("/api/v1/alerts", [(b"x-core-feed-token", TOKEN.encode())])
    assert other["path"] == "/api/v1/alerts"

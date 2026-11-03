"""The guarded fetch: what it refuses, and that redirects are checked hop by hop."""

import asyncio

import httpx
import pytest
from app.services import safe_fetch as sf


@pytest.mark.parametrize("url", ["http://example.com/x", "ftp://example.com", "https://u:p@example.com/x", "https:///x", "https://127.0.0.1/x", "https://10.1.2.3/x", "https://[::1]/x", "https://169.254.169.254/latest"])
def test_a_non_https_credentialed_or_non_public_address_never_reaches_a_client(url, monkeypatch):
    made = []
    monkeypatch.setattr(sf.httpx, "AsyncClient", lambda *a, **k: made.append(1))
    with pytest.raises(sf.FetchRefused):
        asyncio.run(sf.fetch(url, max_redirects=3))
    assert made == []


def _serve(monkeypatch, routes):
    """Stand in for the network: public name resolution, and answers by URL."""
    hits = []

    async def resolve(host, port, **kw):
        if host == "internal.example":
            return [(2, 1, 6, "", ("10.0.0.7", port))]
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    class Loop:
        getaddrinfo = staticmethod(resolve)

    monkeypatch.setattr(sf.asyncio, "get_running_loop", lambda: Loop)
    real = httpx.AsyncClient

    def client(*a, **k):
        def handler(request):
            hits.append(str(request.url))
            return routes[str(request.url)](request)

        return real(transport=httpx.MockTransport(handler), **{x: y for x, y in k.items() if x != "transport"})

    monkeypatch.setattr(sf.httpx, "AsyncClient", client)
    return hits


def test_a_redirect_is_followed_only_when_allowed_and_each_hop_is_checked(monkeypatch):
    routes = {
        "https://a.example/x": lambda r: httpx.Response(302, headers={"location": "https://b.example/y"}),
        "https://b.example/y": lambda r: httpx.Response(200, content=b"data"),
        "https://c.example/x": lambda r: httpx.Response(302, headers={"location": "https://internal.example/secret"}),
        "https://internal.example/secret": lambda r: httpx.Response(200, content=b"secret"),
    }
    hits = _serve(monkeypatch, routes)
    assert asyncio.run(sf.fetch("https://a.example/x", max_redirects=2)) == b"data"
    with pytest.raises(sf.FetchRefused, match="redirects"):
        asyncio.run(sf.fetch("https://a.example/x", max_redirects=0))
    with pytest.raises(sf.FetchRefused, match="not on the public internet"):
        asyncio.run(sf.fetch("https://c.example/x", max_redirects=3))  # a redirect into the internal network is refused
    assert "https://internal.example/secret" not in hits


def test_too_many_redirects_a_big_answer_and_a_bad_status_are_refused(monkeypatch):
    routes = {
        "https://loop.example/": lambda r: httpx.Response(302, headers={"location": "https://loop.example/"}),
        "https://big.example/": lambda r: httpx.Response(200, content=b"x" * 500),
        "https://gone.example/": lambda r: httpx.Response(404),
    }
    _serve(monkeypatch, routes)
    with pytest.raises(sf.FetchRefused, match="too many"):
        asyncio.run(sf.fetch("https://loop.example/", max_redirects=2))
    with pytest.raises(sf.FetchRefused, match="larger"):
        asyncio.run(sf.fetch("https://big.example/", max_bytes=100))
    with pytest.raises(sf.FetchRefused, match="404"):
        asyncio.run(sf.fetch("https://gone.example/"))

"""Sign-in cookies (A15): httpOnly cookies carry the tokens, a header always wins over a cookie, and a cookie alone cannot change anything without the console header."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.api.v1 import deps
from app.api.v1.endpoints import auth
from app.auth import session_cookies as sc
from app.core.security import create_access_token, create_refresh_token
from fastapi import HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials


def req(method="GET", cookies=None, headers=None, scheme="https"):
    return SimpleNamespace(
        method=method, cookies=cookies or {}, headers={k.lower(): v for k, v in (headers or {}).items()}, url=SimpleNamespace(scheme=scheme)
    )


def set_cookie_lines(response: Response) -> list[str]:
    return [v.decode() for k, v in response.raw_headers if k == b"set-cookie"]


def test_both_cookies_are_httponly_narrow_and_secure_on_https():
    response = Response()
    sc.set_session_cookies(response, req(), "ACCESS", "REFRESH")
    lines = set_cookie_lines(response)
    access = next(x for x in lines if x.startswith("aisoc_access="))
    refresh = next(x for x in lines if x.startswith("aisoc_refresh="))
    for line in (access, refresh):
        assert "HttpOnly" in line and "Secure" in line and "SameSite=lax" in line
    assert "Path=/api;" in access + ";" and "Path=/api/v1/auth" in refresh


def test_the_secure_flag_follows_https_including_behind_a_proxy_and_http_in_development():
    http = Response()
    sc.set_session_cookies(http, req(scheme="http"), "A", "R")
    assert all("Secure" not in x for x in set_cookie_lines(http))
    proxied = Response()
    sc.set_session_cookies(proxied, req(scheme="http", headers={"X-Forwarded-Proto": "https"}), "A", "R")
    assert all("Secure" in x for x in set_cookie_lines(proxied))


def test_clearing_expires_both_cookies():
    response = Response()
    sc.clear_session_cookies(response)
    lines = set_cookie_lines(response)
    assert len(lines) == 2 and all("Max-Age=0" in x for x in lines)


def test_reading_is_allowed_by_cookie_but_changing_needs_the_console_header():
    assert sc.csrf_ok(req("GET")) and sc.csrf_ok(req("HEAD")) and sc.csrf_ok(req("OPTIONS"))
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert not sc.csrf_ok(req(method)), method
        assert not sc.csrf_ok(req(method, headers={"X-Requested-With": "XMLHttpRequest"})), "only our own value counts"
        assert sc.csrf_ok(req(method, headers={"X-Requested-With": "aisoc-console"})), method


def test_the_authorization_header_always_wins_over_a_cookie():
    header = HTTPAuthorizationCredentials(scheme="Bearer", credentials="FROM-HEADER")
    out = deps._credentials_or_cookie(header, req("POST", cookies={"aisoc_access": "FROM-COOKIE"}))
    assert out is header, "a script with its own token is not held to the cookie rules"


def test_a_cookie_is_used_when_there_is_no_header_and_none_means_not_signed_in():
    assert deps._credentials_or_cookie(None, req("GET")) is None
    out = deps._credentials_or_cookie(None, req("GET", cookies={"aisoc_access": "TOKEN"}))
    assert out is not None and out.credentials == "TOKEN" and out.scheme == "Bearer"
    assert deps._credentials_or_cookie(None, None) is None


def test_a_cookie_that_changes_data_without_the_console_header_is_refused_before_anything_else():
    with pytest.raises(HTTPException) as e:
        deps._credentials_or_cookie(None, req("POST", cookies={"aisoc_access": "TOKEN"}))
    assert e.value.status_code == 403
    ok = deps._credentials_or_cookie(None, req("POST", cookies={"aisoc_access": "TOKEN"}, headers={"X-Requested-With": "aisoc-console"}))
    assert ok is not None and ok.credentials == "TOKEN"


@pytest.mark.asyncio
async def test_refresh_by_cookie_needs_the_console_header_and_a_bad_cookie_is_a_401(monkeypatch):
    monkeypatch.setattr(auth, "is_revoked", AsyncMock(return_value=False))
    token = create_refresh_token({"sub": "not-a-uuid", "tenant_id": "x", "role": "analyst"})
    with pytest.raises(HTTPException) as no_header:
        await auth.refresh_token(
            auth.RefreshRequest(), db=None, http_request=req("POST", cookies={"aisoc_refresh": token}), response=Response()
        )
    assert no_header.value.status_code == 403
    with pytest.raises(HTTPException) as nothing:
        await auth.refresh_token(auth.RefreshRequest(), db=None, http_request=req("POST"), response=Response())
    assert nothing.value.status_code == 401
    with pytest.raises(HTTPException) as bad_subject:  # reaches the token check: a malformed subject is a 401, as with the body form
        await auth.refresh_token(
            auth.RefreshRequest(),
            db=None,
            http_request=req("POST", cookies={"aisoc_refresh": token}, headers={"X-Requested-With": "aisoc-console"}),
            response=Response(),
        )
    assert bad_subject.value.status_code == 401


@pytest.mark.asyncio
async def test_logout_by_cookie_clears_the_cookies_and_revokes_what_it_can(monkeypatch):
    revoked: list[str] = []

    async def fake_revoke(jti, exp):
        revoked.append(jti)

    monkeypatch.setattr(auth, "revoke", fake_revoke)
    access = create_access_token({"sub": "00000000-0000-0000-0000-000000000001", "tenant_id": "t", "role": "admin"})
    refresh = create_refresh_token({"sub": "00000000-0000-0000-0000-000000000001", "tenant_id": "t", "role": "admin"})
    response = Response()
    user = SimpleNamespace(user_id=__import__("uuid").UUID("00000000-0000-0000-0000-000000000001"))
    out = await auth.logout(
        user, None, None, http_request=req("POST", cookies={"aisoc_access": access, "aisoc_refresh": refresh}), response=response
    )
    assert out.revoked and len(revoked) == 2, "the access token and the refresh token, both from cookies"
    assert len([x for x in set_cookie_lines(response) if "Max-Age=0" in x]) == 2


def ws(cookies=None, headers=None):
    return SimpleNamespace(cookies=cookies or {}, headers={k.lower(): v for k, v in (headers or {}).items()})


def test_the_graph_socket_uses_the_cookie_only_when_the_page_that_opened_it_is_this_site():
    from app.api.v1.endpoints.graph_ws import cookie_token_for_ws

    same = ws({"aisoc_access": "T"}, {"Origin": "https://acorn.example.com", "Host": "acorn.example.com"})
    assert cookie_token_for_ws(same) == "T"
    other_site = ws({"aisoc_access": "T"}, {"Origin": "https://evil.example.net", "Host": "acorn.example.com"})
    assert cookie_token_for_ws(other_site) is None, "a page on another site cannot ride the cookie"
    assert cookie_token_for_ws(ws({"aisoc_access": "T"}, {"Host": "acorn.example.com"})) is None, "no Origin: not a browser page"
    assert cookie_token_for_ws(ws({}, {"Origin": "https://acorn.example.com", "Host": "acorn.example.com"})) is None

"""Sign-in cookies: the access and refresh tokens as httpOnly cookies, so a script running in the browser can never read them (A15, tokens out of browser storage).

The server sets the cookies when a person signs in or refreshes, and accepts the access cookie when a request carries no Authorization header. Two rules keep that safe:

* **Cross-site requests cannot use the cookie to change anything.** A request that changes data (anything but GET, HEAD or OPTIONS) and is authenticated by the cookie alone must also carry the header
  ``X-Requested-With: aisoc-console``. A page on another site cannot add that header without the browser asking this server first, and this server does not allow it. SameSite=Lax adds a second wall.
* **The cookies are narrow.** The access cookie is sent to ``/api`` only, and the refresh cookie only to the refresh and sign-out addresses.

A token sent in the Authorization header is always used instead of the cookie, so scripts, API keys and CORE are unaffected.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import Request, Response

from app.core.config import settings

ACCESS_COOKIE = "aisoc_access"
REFRESH_COOKIE = "aisoc_refresh"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "aisoc-console"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
REFRESH_PATH = "/api/v1/auth"


def _secure(request: Request | None) -> bool:
    if request is None:
        return True
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


def set_session_cookies(response: Response, request: Request | None, access_token: str, refresh_token: str) -> None:
    """Set both cookies on a sign-in or refresh answer."""
    secure = _secure(request)
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=int(timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES).total_seconds()),
        path="/api",
        httponly=True,
        samesite="lax",
        secure=secure,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=int(timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS).total_seconds()),
        path=REFRESH_PATH,
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/api")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_PATH)


def csrf_ok(request: Request) -> bool:
    """Whether a request authenticated by cookie may go ahead: reading always may, changing needs the console header."""
    return request.method.upper() in SAFE_METHODS or request.headers.get(CSRF_HEADER, "").strip() == CSRF_VALUE


def access_token_from_cookie(request: Request | None) -> str | None:
    """The access token in the cookie, when there is one."""
    cookies = getattr(request, "cookies", None) if request is not None else None
    value = cookies.get(ACCESS_COOKIE) if cookies else None
    return value or None


def refresh_token_from_cookie(request: Request | None) -> str | None:
    cookies = getattr(request, "cookies", None) if request is not None else None
    value = cookies.get(REFRESH_COOKIE) if cookies else None
    return value or None

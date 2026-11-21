"""One-time links for accepting a policy without signing in (r7-af-13, Hal 2026-11-21).

A staff member makes a link for one person and one version of a policy; the person opens it, reads the text and ticks "I have read and accept". The link works once, stops working after its expiry, and
only a hash of the token is stored. Everything here is pure (token, hash, state, page text); the routes are in endpoints/public_pages.py and endpoints/governance.py.
"""

from __future__ import annotations

import hashlib
import html
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{24,64}$")
PUBLIC_PATH = "/api/v1/public/policy/"
DEFAULT_DAYS = 14
MAX_DAYS = 60


def new_token() -> str:
    return secrets.token_urlsafe(24)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def link_path(token: str) -> str:
    return f"{PUBLIC_PATH}{token}"


def expiry(now: datetime, days: int | None) -> datetime:
    d = DEFAULT_DAYS if days is None else max(1, min(MAX_DAYS, days))
    return now + timedelta(days=d)


def state_of(expires_at: datetime, used_at: datetime | None, now: datetime) -> str:
    """used / expired / open (a used link stays used even after its expiry)."""
    if used_at is not None:
        return "used"
    exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
    return "expired" if exp <= now else "open"


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


_STYLE = (
    "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#1f2937;line-height:1.55}"
    "h1{font-size:1.5rem}.text{white-space:pre-wrap;border:1px solid #e5e7eb;border-radius:8px;padding:1rem;background:#f9fafb}.note{color:#6b7280;font-size:.85rem}"
    "button{font-size:1rem;padding:.55rem 1.1rem;border-radius:6px;border:0;background:#1d4ed8;color:#fff;cursor:pointer}label{display:block;margin:.8rem 0}input[type=text]{width:100%;padding:.4rem;box-sizing:border-box}"
)


def _doc(title: str, body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="robots" content="noindex,nofollow"><title>{_e(title)}</title><style>{_STYLE}</style></head><body>{body}</body></html>'
    )


def render_form(org: str, title: str, version: int, text: str, email: str, expires_on: str) -> str:
    body = (
        f"<h1>{_e(title)}</h1><p class=\"note\">{_e(org)} - version {_e(version)}. This link is for {_e(email)} and can be used once, until {_e(expires_on)}.</p>"
        f'<div class="text">{_e(text)}</div>'
        '<form method="post"><label>Your full name<input type="text" name="name" maxlength="120" required autocomplete="name"></label>'
        '<label><input type="checkbox" name="agree" value="yes" required> I have read this policy and I accept it.</label>'
        "<button type=\"submit\">Accept policy</button></form>"
    )
    return _doc(title, body)


def render_message(heading: str, detail: str) -> str:
    return _doc(heading, f"<h1>{_e(heading)}</h1><p>{_e(detail)}</p>")


def parse_form(raw: bytes, limit: int = 4096) -> dict[str, str]:
    """The fields of a small application/x-www-form-urlencoded body (pure; first value of each field, the body capped at ``limit`` bytes)."""
    from urllib.parse import parse_qs  # noqa: PLC0415

    parsed = parse_qs(raw[:limit].decode("utf-8", "replace"), keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items() if v}

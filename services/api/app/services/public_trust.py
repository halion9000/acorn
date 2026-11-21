"""The public trust page (roadmap trust-center, Hal 2026-11-21): what an organization shows the world about its security, at a link nobody has to sign in for.

Safeguards, because this is the one page of A.C.O.R.N the internet can read:
 - it is OFF unless a person switched the public link on, and the same 404 answers an unknown token, a switched-off link and junk (so the page cannot be used to find out who has one);
 - the token is long and random (``new_token``) and a new one replaces the old at once;
 - it shows only what the trust center settings chose: a headline, an about text, a contact address, the chosen frameworks' health as a percentage, the chosen policies by name and review date, and https links;
 - every value is escaped, there is no script and no outside file, and the page says not to index it.
"""

from __future__ import annotations

import html
import re
import secrets
from datetime import date
from typing import Any

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{24,64}$")
PUBLIC_PATH = "/api/v1/public/trust/"


def new_token() -> str:
    """A fresh link token: 32 URL-safe characters from the system's random source."""
    return secrets.token_urlsafe(24)


def link_path(token: str | None) -> str | None:
    return None if not token else f"{PUBLIC_PATH}{token}"


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def render(org: str, data: dict[str, Any]) -> str:
    """The page as one self-contained HTML document (pure). ``data`` has headline, about, contact_email, documents [{name, url}], frameworks [{framework, controls, percent_healthy}], policies [{title, last_reviewed_at}]."""
    headline = _e(data.get("headline") or f"Security at {org}")
    parts = [f"<h1>{headline}</h1>"]
    if data.get("about"):
        parts.append("".join(f"<p>{_e(p)}</p>" for p in str(data["about"]).split("\n\n") if p.strip()))
    fw = data.get("frameworks") or []
    if fw:
        rows = []
        for f in fw:
            pct = f.get("percent_healthy")
            measured = str(pct) + "%" if pct is not None else "not measured yet"
            rows.append("<tr><td>" + _e(f["framework"]) + "</td><td>" + _e(measured) + "</td><td>" + _e(f.get("controls", 0)) + " controls</td></tr>")
        parts.append("<h2>Compliance frameworks</h2><table>" + "".join(rows) + '</table><p class="note">Shown as measured now from our own evidence, not typed in.</p>')
    pol = data.get("policies") or []
    if pol:
        items = []
        for p in pol:
            reviewed = p.get("last_reviewed_at")
            when = reviewed.isoformat() if isinstance(reviewed, date) else reviewed
            note = ' <span class="note">reviewed ' + _e(when) + "</span>" if when else ""
            items.append("<li>" + _e(p["title"]) + note + "</li>")
        parts.append("<h2>Policies</h2><ul>" + "".join(items) + "</ul>")
    docs = [d for d in (data.get("documents") or []) if str(d.get("url", "")).lower().startswith(("https://", "http://"))]
    if docs:
        parts.append("<h2>Documents</h2><ul>" + "".join(f"<li><a href=\"{_e(d['url'])}\" rel=\"noopener noreferrer nofollow\">{_e(d['name'])}</a></li>" for d in docs) + "</ul>")
    if data.get("contact_email"):
        parts.append(f"<h2>Contact</h2><p>{_e(data['contact_email'])}</p>")
    body = "\n".join(parts)
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<meta name=\"robots\" content=\"noindex,nofollow\"><title>{headline}</title>"
        "<style>body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;color:#1f2937;line-height:1.55}"
        "h1{font-size:1.7rem}h2{font-size:1.1rem;margin-top:1.8rem;border-bottom:1px solid #e5e7eb;padding-bottom:.2rem}table{border-collapse:collapse}"
        "td{padding:.25rem 1rem .25rem 0}.note{color:#6b7280;font-size:.85rem}a{color:#1d4ed8}footer{margin-top:2.5rem;color:#6b7280;font-size:.8rem}</style></head>"
        f"<body>{body}<footer>{_e(org)}</footer></body></html>"
    )

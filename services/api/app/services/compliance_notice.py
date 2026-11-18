"""The weekly notice of compliance action items: who gets it, when it is due, and what it says (pure).

The action items are the ones the Compliance page lists (evidence that ran out, risk tasks, vendor and access reviews, audit requests, vendor contracts, risk acceptances). A notice goes at most once a week and only when
something is waiting. It is an e-mail to a list of people and, if one is set, the same list as JSON to a web address.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

INTERVAL_DAYS = 7
MAX_EMAILS = 20
MAX_LINES = 40
_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
SCHEMA = "acorn.compliance_actions.v1"
KIND_LABEL = {
    "evidence_expired": "Evidence expired",
    "risk_task": "Risk task",
    "vendor_review": "Vendor review",
    "access_review": "Access review",
    "audit_request": "Audit request",
    "vendor_contract": "Vendor contract",
    "risk_acceptance": "Risk acceptance",
}


def clean_emails(raw: list[str] | None) -> list[str]:
    """The addresses in a list, trimmed, lower case, each once, in order; anything that is not an address is dropped; at most ``MAX_EMAILS`` (pure)."""
    seen: dict[str, None] = {}
    for e in raw or []:
        v = str(e).strip().lower()
        if _EMAIL.match(v) and len(v) <= 254:
            seen.setdefault(v)
    return list(seen)[:MAX_EMAILS]


def webhook_problem(url: str | None) -> str:
    """Why a web address cannot be used, or "" when it can (pure; the host is checked again when it is sent to). Only https, no login in the address, and no obvious local name."""
    if not url:
        return ""
    u = urlparse(url.strip())
    if u.scheme != "https":
        return "The web address must start with https://."
    if not u.hostname or "." not in u.hostname:
        return "The web address needs a real host name."
    if u.username or u.password:
        return "Leave the login out of the web address."
    if u.hostname.lower() in ("localhost",) or u.hostname.lower().endswith((".local", ".internal", ".localhost")):
        return "The web address cannot point at this machine or a local name."
    if len(url) > 500:
        return "The web address is too long."
    return ""


def due(weekly: bool, last_sent_at: datetime | None, now: datetime) -> bool:
    """Whether a notice is due: switched on, and never sent or last sent a week or more ago (pure)."""
    if not weekly:
        return False
    if last_sent_at is None:
        return True
    last = last_sent_at if last_sent_at.tzinfo else last_sent_at.replace(tzinfo=UTC)
    return now - last >= timedelta(days=INTERVAL_DAYS)


def _when(due_at: Any, now: datetime) -> str:
    if due_at is None:
        return "no date"
    d = due_at if due_at.tzinfo else due_at.replace(tzinfo=UTC)
    days = (d.date() - now.date()).days
    if days < 0:
        return f"{-days} day{'s' if days != -1 else ''} overdue"
    return "due today" if days == 0 else f"due in {days} day{'s' if days != 1 else ''} ({d.date().isoformat()})"


def digest(items: list[dict[str, Any]], now: datetime, link: str = "", scope: str = "") -> tuple[str, str, dict[str, Any]]:
    """The subject, the text and the JSON of a notice for these action items (each a dict with ``kind``, ``name``, ``event``, ``owner``, ``due``, ``link``). Empty when there are none: the caller sends nothing then."""
    overdue = sum(1 for i in items if i.get("due") is not None and (i["due"] if i["due"].tzinfo else i["due"].replace(tzinfo=UTC)).date() < now.date())
    where = f" for {scope}" if scope else ""
    subject = f"[A.C.O.R.N] {len(items)} compliance action item{'s' if len(items) != 1 else ''} waiting{where}" + (f", {overdue} overdue" if overdue else "")
    lines = [f"{len(items)} compliance action item{'s' if len(items) != 1 else ''} are waiting{where}" + (f"; {overdue} overdue." if overdue else "."), ""]
    for i in items[:MAX_LINES]:
        owner = f" (owner: {i['owner']})" if i.get("owner") else ""
        lines.append(f"- {KIND_LABEL.get(str(i.get('kind')), str(i.get('kind')))}: {i.get('name')}: {i.get('event')}, {_when(i.get('due'), now)}{owner}")
    if len(items) > MAX_LINES:
        lines.append(f"... and {len(items) - MAX_LINES} more on the Compliance page.")
    if link:
        lines += ["", f"Open the Compliance page: {link}"]
    payload = {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "scope": scope,
        "overdue": overdue,
        "items": [
            {
                "kind": str(i.get("kind")),
                "name": str(i.get("name")),
                "event": str(i.get("event")),
                "owner": i.get("owner"),
                "due": i["due"].isoformat() if i.get("due") is not None else None,
                "link": i.get("link"),
            }
            for i in items
        ],
    }
    return subject, "\n".join(lines), payload

"""Standing approvals: "always allow this kind of agent action (for this client, or for all) until this date".

A person makes the decision once; after that a matching approval card is approved at creation and says so. The rules here are what keep that safe:
  * only REVERSIBLE, low-blast kinds of action can be given a standing approval (``ALLOWED``); anything that deletes, disables, isolates, blocks or changes a firewall always needs a person each time;
  * a standing approval for one client matches only a card that names that same client (a card with no client never matches a client approval);
  * revoked or past-date approvals never match;
  * the matching is deterministic and here, never in a model's hands.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.autonomy_agreement import action_key

ALLOWED = frozenset(
    {
        "add_alert_tag",
        "add_case_comment",
        "assign_case",
        "create_case",
        "close_alert",
        "create_ticket",
        "ticket_note",
    }
)
DEFAULT_DAYS = 90
MAX_DAYS = 365


def client_of(action: Any) -> str | None:
    """The client a card is about, from its payload (``client_id`` or ``client_tenant_id``), as text; None when it names none (pure)."""
    if isinstance(action, dict):
        for k in ("client_id", "client_tenant_id"):
            v = action.get(k)
            if isinstance(v, (str, int)) and str(v).strip():
                return str(v).strip()[:80]
    return None


def refusal(action_type: str) -> str | None:
    """Why this kind of action cannot be given a standing approval, or None when it can (pure)."""
    key = action_type.strip().lower()
    if key in ALLOWED:
        return None
    return f"'{key}' always needs a person's approval each time. Standing approvals are only for: {', '.join(sorted(ALLOWED))}."


def matches(standing: dict[str, Any], action: Any, title: str | None, now: datetime) -> bool:
    """Does this standing approval (``action_type``, ``client_id``, ``expires_at``, ``revoked_at``) cover a card with this payload and title right now (pure)."""
    if standing.get("revoked_at") is not None:
        return False
    expires = standing.get("expires_at")
    if not isinstance(expires, datetime) or expires <= now:
        return False
    if action_key(action, title) != str(standing.get("action_type", "")).strip().lower():
        return False
    if action_key(action, title) not in ALLOWED:
        return False
    wanted = standing.get("client_id")
    if wanted in (None, ""):
        return True
    return client_of(action) == str(wanted)

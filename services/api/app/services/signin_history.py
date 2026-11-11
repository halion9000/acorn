"""A person's own recent sign-ins: when, how (password, passkey, Microsoft) and from which address.

A password or passkey sign-in writes one audit entry (``auth:login``); a Microsoft sign-in already writes its own (``auth:sso_login`` and the two for a first sign-in). The history is read from those
entries, for the signed-in person only. Recording never stops a sign-in: if the entry cannot be written the person is still signed in.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.services.audit import emit_audit

logger = logging.getLogger(__name__)

LOGIN_ACTION = "auth:login"
MICROSOFT_ACTIONS = ("auth:sso_login", "auth:sso_linked", "auth:sso_user_created")
SIGNIN_ACTIONS = (LOGIN_ACTION, *MICROSOFT_ACTIONS)
SHOWN = 20
METHOD_WORDS = {"password": "Password", "passkey": "Passkey", "microsoft": "Microsoft"}


def method_of(action: str, changes: Any) -> str:
    """How the person signed in, in a word; "Unknown" for an entry that does not say."""
    if action in MICROSOFT_ACTIONS:
        return METHOD_WORDS["microsoft"]
    method = changes.get("method") if isinstance(changes, dict) else None
    return METHOD_WORDS.get(str(method), "Unknown")


def rows(entries: list[dict[str, Any]], shown: int = SHOWN) -> list[dict[str, str | None]]:
    """The newest ``shown`` sign-ins as {at, method, ip}. ``entries`` are dicts with created_at, action, changes and actor_ip, newest first (pure)."""
    out: list[dict[str, str | None]] = []
    for e in entries[:shown]:
        at = e.get("created_at")
        ip = e.get("actor_ip")
        out.append(
            {
                "at": at.isoformat() if hasattr(at, "isoformat") else (str(at) if at else None),
                "method": method_of(str(e.get("action", "")), e.get("changes")),
                "ip": str(ip) if ip else None,
            }
        )
    return out


async def record(db: Any, *, user_id: uuid.UUID, tenant_id: uuid.UUID, label: str | None, method: str, request: Any = None) -> bool:
    """Write the audit entry for a password or passkey sign-in. Inside a savepoint, so a failure here leaves the sign-in's own work untouched; returns whether it was written."""
    try:
        async with db.begin_nested():
            await emit_audit(
                db=db,
                tenant_id=tenant_id,
                actor_id=user_id,
                actor_email=label,
                action=LOGIN_ACTION,
                resource="user",
                resource_id=str(user_id),
                changes={"method": method},
                request=request,
            )
        return True
    except Exception:  # noqa: BLE001  # a sign-in must never fail because its history line could not be written
        logger.warning("signin history: the entry could not be written", exc_info=True)
        return False

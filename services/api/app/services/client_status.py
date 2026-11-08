"""What a client sees on its private status page, and whether a link may be used.

Everything a client reads is decided HERE, in one place, so the wording can be reviewed in one place: the fixed sentences (``COPY``), and a projection that keeps only counts and plain labels from the
posture numbers A.C.O.R.N already holds. It never carries a raw alert, a person's name or address, a device name, a ticket number, a tool's key or an internal id. The page says nothing the numbers do not
support, and says "not available" instead of guessing when a number is missing.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime
from typing import Any

TOKEN_BYTES = 32
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{40,64}$")

# The only fixed wording a client reads (besides the labels in ``TOOL_LABELS``). Edit here, review here.
COPY = {
    "title": "Your security status",
    "intro": "A plain summary of how your IT environment is protected today, kept up to date by your IT provider. It shows counts only; your provider follows up on anything that needs attention.",
    "devices": "Computers with endpoint protection",
    "people": "People protected by a second sign-in step",
    "alerts_open": "Security alerts open now",
    "alerts_handled": "of those, already being worked on by your provider",
    "tools": "Protections in place",
    "footer": "Questions about this page? Contact your IT provider.",
}

TOOL_LABELS = {
    "huntress": "Managed endpoint detection (Huntress)",
    "blumira": "Security monitoring (Blumira)",
    "ninjaone": "Device management and patching (NinjaOne)",
    "addigy": "Mac management (Addigy)",
    "cipp": "Microsoft 365 management (CIPP)",
    "dnsfilter": "Web filtering (DNSFilter)",
    "fieldeffect": "Managed detection and response (Field Effect)",
    "threatmate": "Security assessment (ThreatMate)",
    "liongard": "Configuration monitoring (Liongard)",
    "datto-saas": "Cloud backup (Datto SaaS Protection)",
    "dropsuite": "Email backup (Dropsuite)",
    "slide": "Server backup (Slide)",
    "autoelevate": "Admin rights control (AutoElevate)",
    "screenconnect": "Remote support (ScreenConnect)",
}


def new_token() -> str:
    """A fresh link secret (URL-safe, 43 characters)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def well_formed(token: str) -> bool:
    """Cheap shape check before any database lookup (pure)."""
    return bool(_TOKEN.fullmatch(token or ""))


def link_problem(link: dict[str, Any], now: datetime) -> str | None:
    """Why this link cannot be used right now, or None: revoked, past its end date, or its wording not reviewed yet (pure)."""
    if link.get("revoked_at") is not None:
        return "revoked"
    expires = link.get("expires_at")
    if not isinstance(expires, datetime) or expires <= now:
        return "expired"
    if link.get("reviewed_at") is None:
        return "not reviewed"
    return None


def percent(part: int, whole: int) -> int | None:
    if whole <= 0:
        return None
    return max(0, min(100, round(100 * part / whole)))


def project(posture: dict[str, Any]) -> dict[str, Any]:
    """The client-safe page from a client posture (``ClientPosture.model_dump()``): counts, percentages and plain labels only (pure)."""
    devices = posture.get("devices") or {}
    total = int(devices.get("devices") or 0)
    covered = max(0, total - int(devices.get("not_in_huntress") or 0))
    identity = posture.get("identity")
    people = int(identity.get("people") or 0) if identity else 0
    protected = int(identity.get("with_mfa") or 0) + int(identity.get("not_required") or 0) if identity else 0
    alerts = posture.get("alerts") or {}
    open_alerts = int(alerts.get("open") or 0)
    handled = max(0, open_alerts - int(alerts.get("without_ticket") or 0))
    seen: list[str] = []
    for t in posture.get("tools") or []:
        label = TOOL_LABELS.get(str(t.get("vendor", "")).lower())
        if label and label not in seen:
            seen.append(label)
    generated = posture.get("generated_at")
    return {
        "client_name": posture.get("client_name") or "",
        "generated_at": generated.isoformat() if isinstance(generated, datetime) else generated,
        "devices": {"total": total, "protected": covered, "percent": percent(covered, total)},
        "people": {"total": people, "protected": min(protected, people), "percent": percent(min(protected, people), people)} if identity else None,
        "alerts": {"open": open_alerts, "being_worked_on": handled},
        "tools": sorted(seen),
        "copy": COPY,
    }

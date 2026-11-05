"""Releasing a quarantined message from A.C.O.R.N: what an alert says about the message, and the link a ticket carries back to it.

A "user asked to release a quarantined message" alert (raised by CORE from Exchange, through CIPP) records the message's quarantine identity and the CIPP customer it belongs to. A person who decides the
message is safe presses Release on the alert; A.C.O.R.N queues a ``release_quarantine`` action for CORE, which asks CIPP (``ExecQuarantineManagement``, type Release, the sender is NEVER added to an
allow list) to release it. Releasing is a decision a person makes each time: nothing releases on its own, a rule that opens a ticket only carries the link.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.models.alert import Alert

ACTION = "release_quarantine"
VENDOR = "core"
UID_PREFIX = "quarantine-release:"


def _context(raw_event: Any) -> dict[str, Any]:
    unmapped = raw_event.get("unmapped") if isinstance(raw_event, dict) else None
    ctx = unmapped.get("context") if isinstance(unmapped, dict) else None
    return ctx if isinstance(ctx, dict) else {}


def _text(value: Any, limit: int = 300) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, str) and value.strip() else ""


def quarantine_of(raw_event: Any) -> dict[str, str] | None:
    """The message a release alert is about, or None when the alert is not one. It needs the alert to be CORE's quarantine-release kind AND to carry both the message's identity and its CIPP customer.

    ``identity`` is Exchange's quarantine identity (opaque), ``client`` the CIPP customer id, ``recipient`` who it was requested for, ``sender`` and ``kind`` (why it was held) for display (pure)."""
    if not isinstance(raw_event, dict):
        return None
    finding = raw_event.get("finding")
    uid = finding.get("uid") if isinstance(finding, dict) else None
    if not (isinstance(uid, str) and uid.startswith(UID_PREFIX)):
        return None
    ctx = _context(raw_event)
    identity, client = _text(ctx.get("quarantine_identity"), 500), _text(ctx.get("cipp_tenant_id"), 100)
    if not identity or not client:
        return None
    return {
        "identity": identity,
        "client": client,
        "recipient": _text(ctx.get("username"), 320),
        "sender": _text(ctx.get("sender"), 320),
        "kind": _text(ctx.get("quarantine_type"), 60),
    }


def release_link(base_url: str, alert_id: Any) -> str | None:
    """The address that opens the alert with the release panel ready, for a ticket to carry. None when the console's public address is not set or is not a plain https address (pure)."""
    base = (base_url or "").strip().rstrip("/")
    if not base.lower().startswith("https://") or any(c.isspace() for c in base):
        return None
    return f"{base}/alerts/{alert_id}?release=1"


async def note_quarantine_released(db: Any, tenant_id: Any, alert_id: Any, now: datetime) -> bool:
    """Record on the alert that its message was released (when CORE reports the release done). Returns whether anything was recorded. The caller owns the transaction."""
    alert = (await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tenant_id))).scalar_one_or_none()
    if alert is None:
        return False
    enrichment = dict(alert.enrichment_data) if isinstance(alert.enrichment_data, dict) else {}
    enrichment["quarantine_release"] = {"released_at": now.isoformat()}
    alert.enrichment_data = enrichment  # a new dict, so the JSONB column is seen as changed
    return True

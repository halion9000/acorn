"""Sending the compliance notice for one organization or client: the e-mail and the web address (the side-effecting half; the wording and the rules are in ``compliance_notice``).

Nothing is sent when no action item is waiting. The e-mail needs the mail credentials; the web address is checked against private and local ranges again at the moment of sending and gets the list as JSON with no redirects followed.
A channel that fails does not stop the other; the notice counts as sent when either one went, and the result text says what happened to each.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select

from app.core.config import settings as default_settings
from app.models.governance import ComplianceNotice
from app.models.tenant import Tenant
from app.services import compliance_notice as cn
from app.services.alert_email.graph import GraphMailer, MailError
from app.services.destinations import DestinationError, _guard_url


async def send_notice(
    db: Any,
    notice: ComplianceNotice,
    *,
    now: datetime | None = None,
    mailer: GraphMailer | None = None,
    post: Any = None,
) -> dict[str, Any]:
    """Send the notice now and record how it went on the row (the caller commits). Returns ``sent`` (whether anything went), ``items`` and what happened to each channel."""
    from app.api.v1.endpoints.compliance_dashboard import build_dashboard  # late: that module is large

    now = now or datetime.now(UTC)
    board = await build_dashboard(db, notice.tenant_id)
    items = [i.model_dump() for i in board.action_items]
    out: dict[str, Any] = {"sent": False, "items": len(items), "email": "not asked", "webhook": "not asked"}
    if not items:
        out["email"] = out["webhook"] = "nothing is waiting"
        notice.last_result = "Nothing was waiting, so nothing was sent."
        return out
    name = (await db.execute(select(Tenant.name).where(Tenant.id == notice.tenant_id))).scalar_one_or_none() or ""
    base = (default_settings.CONSOLE_PUBLIC_BASE_URL or "").strip().rstrip("/")
    link = f"{base}/compliance" if base.lower().startswith(("http://", "https://")) else ""
    subject, text, payload = cn.digest(items, now, link, name)
    emails = cn.clean_emails(notice.emails)
    if emails:
        mailer = mailer or GraphMailer.from_settings()
        if not mailer.configured:
            out["email"] = "the mail credentials are not set"
        else:
            try:
                await mailer.send(emails, subject, text)
                out["email"], out["sent"] = f"sent to {len(emails)}", True
            except MailError as exc:
                out["email"] = f"failed ({'permanent' if exc.permanent else 'will retry'})"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                out["email"] = f"failed ({type(exc).__name__})"
    if notice.webhook_url:
        problem = cn.webhook_problem(notice.webhook_url)
        if problem:
            out["webhook"] = f"not used: {problem}"
        else:
            try:
                await asyncio.to_thread(_guard_url, notice.webhook_url)
                if post is None:
                    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                        res = await client.post(notice.webhook_url, json=payload)
                else:
                    res = await post(notice.webhook_url, payload)
                if 200 <= res.status_code < 300:
                    out["webhook"], out["sent"] = "sent", True
                else:
                    out["webhook"] = f"the address answered {res.status_code}"
            except DestinationError as exc:
                out["webhook"] = f"not sent: {exc}"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                out["webhook"] = f"failed ({type(exc).__name__})"
    notice.last_result = f"{len(items)} items. E-mail: {out['email']}. Web address: {out['webhook']}."[:600]
    if out["sent"]:
        notice.last_sent_at = now
    return out

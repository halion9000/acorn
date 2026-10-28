"""Microsoft 365 account actions carried out through CORE and CIPP.

CORE holds the CIPP credentials. These executors only ask CORE's local route (``AISOC_CORE_ACTIONS_URL``, with its own bearer token ``AISOC_CORE_ACTIONS_TOKEN``, both written into this stack's
.env by CORE) to run one allowlisted action, and CORE decides whether it really runs: its own switch (off until ``CIPP_ACTIONS_LIVE=true`` is saved there), the clients opted in, the protected
accounts and the hourly cap all apply on that side, whatever is asked here. A request CORE did not carry out comes back as ``blocked``; one it only previewed comes back as ``simulated``.

The dispatcher still runs its own autonomy gate first (``_legacy_action_type`` below is what it rates the action as), so a high-blast action waits for a person unless the tier allows it.
Disabling an account, blocking sign-in and containing an account are all rated like disabling a user; revoking sessions like suspending a session; inbox rules like quarantining a file (switching
one off) or killing a process (deleting one).

The client is the CIPP customer id: ``params.client_id`` when the caller knows it, else the one the alert's client is mapped to in A.C.O.R.N's client mapping.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
import structlog

from app.models.action import ActionType

from .executor import LiveActionExecutor
from .models import LiveActionRequest, LiveActionResult, LiveActionStatus

logger = structlog.get_logger(__name__)

VENDOR_ID = "core_cipp"
TIMEOUT_SECONDS = 90.0  # CIPP is slow: it signs in to the client's tenant for each action.


def core_settings() -> tuple[str, str]:
    """(URL, bearer token) of CORE's actions route; empty when this stack was not given them."""
    return (os.getenv("AISOC_CORE_ACTIONS_URL") or "").strip(), (os.getenv("AISOC_CORE_ACTIONS_TOKEN") or "").strip()


async def customer_for_tenant(tenant_id: UUID | None) -> str | None:
    """The CIPP customer id the client tenant is mapped to, or None (no tenant, no database, no mapping)."""
    if tenant_id is None:
        return None
    from sqlalchemy import text

    from app.db import get_session_factory

    factory = get_session_factory()
    if factory is None:
        return None
    try:
        async with factory() as db:
            row = (
                await db.execute(
                    text("select vendor_client_id from client_aliases where child_tenant_id = :t and vendor = 'cipp' and not ignored order by updated_at desc limit 1"),
                    {"t": tenant_id},
                )
            ).first()
    except Exception:  # noqa: BLE001
        logger.warning("core_cipp.alias_lookup_failed", exc_info=True)
        return None
    return str(row[0]) if row else None


class CoreCippAction(LiveActionExecutor):
    """One allowlisted CORE/CIPP action, as a live action."""

    vendor_id = VENDOR_ID
    requires_credentials = True

    def __init__(
        self,
        capability: str,
        core_action: str,
        legacy: ActionType,
        description: str,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        customer_lookup: Callable[[UUID | None], Any] = customer_for_tenant,
    ) -> None:
        self.capability = capability
        self.description = description
        self._core_action = core_action
        self._legacy_action_type = legacy
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=TIMEOUT_SECONDS))
        self._customer_lookup = customer_lookup

    def _result(self, request: LiveActionRequest, status: LiveActionStatus, summary: str, details: dict[str, Any] | None = None, error: str | None = None) -> LiveActionResult:
        return LiveActionResult(request_id=request.request_id, status=status, capability=self.capability, vendor_id=self.vendor_id, summary=summary, details=details or {}, error=error)

    async def execute(self, request: LiveActionRequest) -> LiveActionResult:
        url, token = core_settings()
        if not url or not token:
            return self._result(request, LiveActionStatus.SIMULATED, "CORE's actions route is not configured here, so nothing was sent", {"configured": False})
        params = request.params or {}
        client_id = str(params.get("client_id") or params.get("cipp_customer_id") or "").strip() or await self._customer_lookup(request.tenant_id)
        if not client_id:
            return self._result(request, LiveActionStatus.FAILED, "No CIPP client for this alert's client: map it in Settings, Client mapping", error="no cipp client id")
        user = str(params.get("user") or request.target or "").strip()
        body = {
            "action": self._core_action,
            "client_id": client_id,
            "user": user or None,
            "user_id": params.get("user_id"),
            "rule_id": params.get("rule_id"),
            "rule_name": params.get("rule_name"),
            "dry_run": bool(request.dry_run),
            "reason": f"playbook run {request.playbook_run_id}" if request.playbook_run_id else (f"case {request.case_id}" if request.case_id else None),
            "actor": request.requested_by,
        }
        try:
            async with self._client_factory() as http:
                res = await http.post(url, headers={"Authorization": f"Bearer {token}"}, json={k: v for k, v in body.items() if v is not None})
        except httpx.HTTPError as exc:
            return self._result(request, LiveActionStatus.FAILED, "Could not reach CORE to carry out the action", error=f"{type(exc).__name__}")
        try:
            out = res.json()
        except ValueError:
            out = {}
        if res.status_code == 401:
            return self._result(request, LiveActionStatus.FAILED, "CORE refused this stack's token: run BUILD A.C.O.R.N in CORE to refresh it", error="core refused the token")
        status = str(out.get("status", "")) if isinstance(out, dict) else ""
        detail = str(out.get("detail", ""))[:300] if isinstance(out, dict) else ""
        details = {k: v for k, v in (out.items() if isinstance(out, dict) else []) if k in ("status", "code", "risk", "reversible", "live_enabled", "would_send", "would_refuse")}
        if status == "executed":
            return self._result(request, LiveActionStatus.SUCCEEDED, f"{self.capability} for {user or client_id}: {detail}", details)
        if status == "dry_run":
            return self._result(request, LiveActionStatus.SIMULATED, f"{self.capability} for {user or client_id}: not sent ({detail})", details)
        if status == "refused":
            return self._result(request, LiveActionStatus.BLOCKED, f"{self.capability} for {user or client_id}: refused by CORE ({detail})", details)
        return self._result(request, LiveActionStatus.FAILED, f"{self.capability} for {user or client_id}: {detail or 'CORE could not carry it out'}", details, error=detail or f"status {res.status_code}")


# capability -> (CORE action, what the autonomy gate rates it as, description)
_ACTIONS: tuple[tuple[str, str, ActionType, str], ...] = (
    ("revoke_session", "revoke_sessions", ActionType.SUSPEND_SESSION, "Sign a person out of Microsoft 365 everywhere, through CIPP."),
    ("disable_user", "disable_user", ActionType.DISABLE_USER, "Block a Microsoft 365 account from signing in, through CIPP."),
    ("enable_user", "enable_user", ActionType.DISABLE_USER, "Let a blocked Microsoft 365 account sign in again, through CIPP."),
    ("contain_user", "contain_user", ActionType.DISABLE_USER, "Contain a compromised Microsoft 365 account: block sign-in, sign out everywhere, switch off its inbox rules, through CIPP."),
    ("disable_mailbox_rule", "disable_mailbox_rule", ActionType.QUARANTINE_FILE, "Switch off one inbox rule on a Microsoft 365 mailbox, through CIPP."),
    ("remove_mailbox_rule", "remove_mailbox_rule", ActionType.KILL_PROCESS, "Delete one inbox rule from a Microsoft 365 mailbox, through CIPP."),
)


def core_cipp_executors() -> list[CoreCippAction]:
    return [CoreCippAction(cap, action, legacy, desc) for cap, action, legacy, desc in _ACTIONS]

"""Starting a business email compromise (BEC) search by itself when an alert says a Microsoft 365 account may be taken over.

The search is the same one the button starts (``identity_bec.queue_case``): CORE has CIPP investigate the person, read only. It starts on a NEW alert from one of the account-takeover rules, for the person the
alert names, when Microsoft 365 knows that person and the client is linked to CIPP. Kept small on purpose, so a spray of alerts cannot flood CIPP: at most one search per person per day, ``BEC_AUTO_PER_CLIENT_PER_DAY``
per client and ``BEC_AUTO_PER_DAY`` in all. Never raises: a failure here must not lose the alert that triggered it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Rules that are real signs of a taken-over account (the others, a legacy protocol or a mass deletion, are not).
TRIGGER_RULES: frozenset[str] = frozenset(
    {
        "aisoc-id-impossible-travel",
        "aisoc-id-device-code",
        "aisoc-id-mfa-fatigue",
        "aisoc-id-guessed-password",
        "aisoc-id-failed-after-revoke",
        "aisoc-id-admin-security-info",
        "aisoc-id-app-consent",
        "aisoc-id-dormant-active",
    }
)
TRIGGER_SEVERITIES = frozenset({"high", "critical"})
MAX_PEOPLE_PER_ALERT = 2


def people_to_check(findings: list[Any]) -> list[str]:
    """The addresses worth a search: those named by a high or critical finding of a takeover rule, in order, each once."""
    seen: list[str] = []
    for f in findings:
        if f.rule_id not in TRIGGER_RULES or str(f.severity).lower() not in TRIGGER_SEVERITIES:
            continue
        for who in f.users[:MAX_PEOPLE_PER_ALERT]:
            address = (who or "").strip().lower()
            if "@" in address and address not in seen:
                seen.append(address)
    return seen


async def auto_bec(db: Any, tenant_id: uuid.UUID, findings: list[Any], settings: Any, now: datetime | None = None) -> int:
    """Queue a search for each person the new findings name, within the limits. Returns how many were queued."""
    if not getattr(settings, "BEC_AUTO_ENABLED", True) or not findings:
        return 0
    wanted = people_to_check(findings)
    if not wanted:
        return 0
    now = now or datetime.now(UTC)
    try:
        from sqlalchemy import func, select  # noqa: PLC0415

        from app.api.v1.endpoints.identity_bec import queue_case  # noqa: PLC0415
        from app.db.rls_scope import cross_tenant_reads  # noqa: PLC0415
        from app.models.bec_case import BecCase  # noqa: PLC0415
        from app.models.client_alias import ClientAlias  # noqa: PLC0415
        from app.models.signin import IdentityMfaUser  # noqa: PLC0415
        from app.models.tenant import Tenant  # noqa: PLC0415

        since = now - timedelta(days=1)
        queued = 0
        async with db.begin_nested():
            async with cross_tenant_reads(db):
                owner = (await db.execute(select(Tenant.parent_tenant_id).where(Tenant.id == tenant_id))).scalar_one_or_none()
                if owner is None:
                    return 0  # the owner's own tenant: there is no client to investigate
                cipp = (
                    await db.execute(
                        select(ClientAlias.vendor_client_id)
                        .where(ClientAlias.tenant_id == owner, ClientAlias.child_tenant_id == tenant_id, ClientAlias.vendor == "cipp", ClientAlias.ignored.is_(False))
                        .order_by(ClientAlias.updated_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                total = (await db.execute(select(func.count()).select_from(BecCase).where(BecCase.requested_by.is_(None), BecCase.created_at > since))).scalar_one()
                here = (await db.execute(select(func.count()).select_from(BecCase).where(BecCase.requested_by.is_(None), BecCase.tenant_id == tenant_id, BecCase.created_at > since))).scalar_one()
            if not cipp:
                return 0
            for address in wanted:
                if total + queued >= settings.BEC_AUTO_PER_DAY or here + queued >= settings.BEC_AUTO_PER_CLIENT_PER_DAY:
                    break
                recent = (await db.execute(select(func.count()).select_from(BecCase).where(BecCase.tenant_id == tenant_id, BecCase.email == address, BecCase.created_at > since))).scalar_one()
                if recent:
                    continue
                uid = (await db.execute(select(IdentityMfaUser.user_id).where(IdentityMfaUser.tenant_id == tenant_id, func.lower(IdentityMfaUser.upn) == address).limit(1))).scalar_one_or_none()
                if not uid:
                    continue  # Microsoft 365 does not know this person
                queue_case(db, client_id=tenant_id, email=address, microsoft_id=str(uid), cipp_customer_id=str(cipp), requested_by=None, requested_by_name="A.C.O.R.N (automatic, after an alert)", now=now)
                queued += 1
            await db.flush()
        return queued
    except Exception:  # noqa: BLE001
        logger.warning("automatic BEC search could not be queued for tenant=%s", tenant_id, exc_info=True)
        return 0

"""Open a HaloPSA ticket automatically for an alert type.

A rule says "every alert of this type (for this client, or for all) gets a ticket". A.C.O.R.N opens nothing itself and holds no HaloPSA key: for each matching alert that has no ticket yet it queues a
``create_ticket`` action for CORE (the ``vendor_actions`` queue, vendor ``core``), CORE opens the ticket and reports its number, and the number is linked to the alert.

Safeguards, because this acts on its own:
 - a rule covers only alerts raised AFTER it was made, plus the one it was made from, so making a rule never floods Halo with old alerts;
 - an alert gets at most ONE ticket request, ever (any earlier request for it, whatever happened to it, stops another), so a failure never turns into a loop;
 - an alert that already has a ticket (found by CORE, or entered by hand) gets none;
 - hidden, set aside, resolved or closed alerts get none;
 - a pass queues at most ``MAX_PER_RULE_PASS`` per rule.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.models.alert import Alert
from app.models.alert_ticket_rule import AlertTicketRule
from app.models.client_alias import ClientAlias
from app.models.tenant import Tenant
from app.models.vendor_action import VendorAction
from app.services.alert_status import FINISHED_ALERT_STATUSES
from app.services.alert_suppression import _acting, signature_of, source_of
from app.services.quarantine_release import quarantine_of, release_link

ACTION = "create_ticket"
VENDOR = "core"
MAX_PER_RULE_PASS = 50
TITLE_MAX = 200
DETAILS_MAX = 3000


def _release_url(alert: Any) -> str | None:
    """The link a ticket carries to release the alert's quarantined message: only for an alert that is one, and only when the console's public address is known."""
    return release_link(settings.CONSOLE_PUBLIC_BASE_URL, alert.id) if quarantine_of(alert.raw_event) is not None else None


def has_ticket(enrichment: Any) -> bool:
    """Whether the alert already has a HaloPSA ticket: one CORE matched (``tickets``) or one a person entered (``manual_tickets``). Anything not shaped like a ticket does not count (pure)."""
    if not isinstance(enrichment, dict):
        return False
    for key in ("tickets", "manual_tickets"):
        for t in enrichment.get(key) or []:
            if isinstance(t, dict) and str(t.get("id", "")).strip() and str(t.get("system") or "halopsa") == "halopsa":
                return True
    return False


def rule_covers(
    rule: Any,
    *,
    tenant_id: uuid.UUID,
    rule_id: str | None,
    title: str | None,
    source: str | None,
    created_at: datetime | None,
    source_alert_id: Any = None,
    alert_id: Any = None,
) -> bool:
    """Whether a rule covers an alert: the same type and tool, in the place the rule covers, and raised after the rule was made (or it is the alert the rule was made from) (pure)."""
    if signature_of(rule_id, title) != rule.signature or (rule.source or None) != (source or None):
        return False
    if rule.scope == "client" and rule.client_tenant_id != tenant_id:
        return False
    if source_alert_id is not None and alert_id == source_alert_id:
        return True
    if created_at is None:
        return False
    moment = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
    return moment >= rule.created_at


def ticket_params(alert: Any, halo_client_id: str | None, rule_title: str, release_url: str | None = None) -> dict[str, Any]:
    """What CORE needs to open the ticket: a summary and details taken from the alert, and the HaloPSA client the alert's client is mapped to (when it is)."""
    title = " ".join(str(alert.title or rule_title or "Alert").split())
    details = str(alert.description or alert.title or "").strip()
    note = f"\n\nOpened automatically by an A.C.O.R.N ticket rule for alert {alert.id}."
    release = f"\n\nIf the message is safe, release it in A.C.O.R.N (you will be asked to confirm): {release_url}" if release_url else ""
    return {
        "summary": title[:TITLE_MAX],
        "details": details[: DETAILS_MAX - len(note) - len(release)] + note + release,
        "rule": "ticket_rule",
        **({"halo_client_id": str(halo_client_id)} if halo_client_id else {}),
    }


async def _halo_clients(db: Any, owner: uuid.UUID, tenants: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    rows = (
        await db.execute(
            select(ClientAlias.child_tenant_id, ClientAlias.vendor_client_id).where(
                ClientAlias.tenant_id == owner,
                ClientAlias.vendor == "halopsa",
                ClientAlias.child_tenant_id.in_(tenants),
                ClientAlias.ignored.is_(False),
            )
        )
    ).all()
    return {child: str(vendor_id) for child, vendor_id in rows}


async def tenants_of(db: Any, rule: Any) -> list[uuid.UUID]:
    """The tenants whose alerts a rule can cover: the one client for a client rule, else the owner and all its clients."""
    if rule.scope == "client" and rule.client_tenant_id is not None:
        return [rule.client_tenant_id]
    kids = [r[0] for r in (await db.execute(select(Tenant.id).where(Tenant.parent_tenant_id == rule.tenant_id))).all()]
    return [rule.tenant_id, *kids]


async def queue_for_rule(db: Any, rule: Any, now: datetime | None = None, source_alert_id: uuid.UUID | None = None) -> int:
    """Queue a ticket request for each alert the rule covers that has no ticket and no earlier request. Returns how many were queued. The caller owns the transaction.

    Each client's alerts are read as that client (``_acting``); the owner's own are read as the session already is."""
    now = now or datetime.now(UTC)
    queued = 0
    tenants = await tenants_of(db, rule)
    halo = await _halo_clients(db, rule.tenant_id, tenants)
    for tid in tenants:
        if queued >= MAX_PER_RULE_PASS:
            break
        async with _acting(db, tid, rule.tenant_id):
            rows = (
                (
                    await db.execute(
                        select(Alert)
                        .where(Alert.tenant_id == tid, Alert.status.notin_(FINISHED_ALERT_STATUSES), Alert.created_at >= rule.created_at)
                        .order_by(Alert.created_at)
                        .limit(500)
                    )
                )
                .scalars()
                .all()
            )
            if source_alert_id is not None:
                src = (
                    (
                        await db.execute(
                            select(Alert).where(
                                Alert.id == source_alert_id, Alert.tenant_id == tid, Alert.status.notin_(FINISHED_ALERT_STATUSES)
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if src is not None and all(r.id != src.id for r in rows):
                    rows = [*rows, src]
            candidates = [
                a
                for a in rows
                if rule_covers(
                    rule,
                    tenant_id=tid,
                    rule_id=a.rule_id,
                    title=a.title,
                    source=source_of(a.raw_event, a.connector_type),
                    created_at=a.created_at,
                    source_alert_id=source_alert_id,
                    alert_id=a.id,
                )
                and not has_ticket(a.enrichment_data)
            ]
            if not candidates:
                continue
            already = set(
                (
                    await db.execute(
                        select(VendorAction.alert_id).where(
                            VendorAction.tenant_id == tid,
                            VendorAction.vendor == VENDOR,
                            VendorAction.action == ACTION,
                            VendorAction.alert_id.in_([a.id for a in candidates]),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for a in candidates:
                if a.id in already:
                    continue
                if queued >= MAX_PER_RULE_PASS:
                    break
                db.add(
                    VendorAction(
                        id=uuid.uuid4(),
                        tenant_id=tid,
                        alert_id=a.id,
                        vendor=VENDOR,
                        incident_uid=f"ticket-rule:{a.id}"[:200],
                        action=ACTION,
                        params=ticket_params(a, halo.get(tid), rule.title, _release_url(a)),
                        status="pending",
                        requested_by=rule.created_by,
                        created_at=now,
                    )
                )
                queued += 1
            await db.flush()
    return queued


async def link_created_ticket(db: Any, tenant_id: uuid.UUID, alert_id: uuid.UUID, ticket_id: str, now: datetime) -> bool:
    """Link the ticket CORE opened to its alert, among the tickets entered by hand (CORE's own ticket sync never removes those). Linking the same number twice changes nothing. Returns whether it was added. The caller owns the transaction."""
    alert = (await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tenant_id))).scalar_one_or_none()
    if alert is None:
        return False
    enrichment = dict(alert.enrichment_data) if isinstance(alert.enrichment_data, dict) else {}
    manual = [t for t in (enrichment.get("manual_tickets") or []) if isinstance(t, dict)]
    if any(str(t.get("id")) == ticket_id and str(t.get("system") or "halopsa") == "halopsa" for t in manual):
        return False
    manual.append(
        {
            "system": "halopsa",
            "id": ticket_id,
            "summary": "Opened automatically by a ticket rule",
            "added_by": "ticket rule",
            "added_at": now.isoformat(),
        }
    )
    enrichment["manual_tickets"] = manual
    alert.enrichment_data = enrichment  # a new dict, so the JSONB column is seen as changed
    return True


async def sweep_ticket_rules(db: Any, now: datetime | None = None) -> int:
    """One pass over every active rule: queue a ticket request for each new alert it covers. Run by the background worker. Returns how many were queued."""
    now = now or datetime.now(UTC)
    rules = (await db.execute(select(AlertTicketRule).where(AlertTicketRule.revoked_at.is_(None)))).scalars().all()
    total = 0
    for rule in rules:
        total += await queue_for_rule(db, rule, now)
    return total

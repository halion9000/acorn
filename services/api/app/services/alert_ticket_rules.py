"""Open a HaloPSA ticket automatically for an alert type.

A rule says "every alert of this type (for this client, or for all) gets a ticket". A.C.O.R.N opens nothing itself and holds no HaloPSA key: for each matching alert that has no ticket yet it queues a
``create_ticket`` action for CORE (the ``vendor_actions`` queue, vendor ``core``), CORE opens the ticket and reports its number, and the number is linked to the alert.

A rule also opens a case for each alert it covers that has none (``insert_case_for_alert``), so a ticket and a case always go together; cases are not opened for alerts no rule covers.

Safeguards, because this acts on its own:
 - a rule covers only alerts raised AFTER it was made, plus the one it was made from, so making a rule never floods Halo with old alerts; the person making it may also ask for a one-time catch-up of the
   alerts of that type already open, at most ``CATCH_UP_MAX``, newest first;
 - an alert gets at most ONE ticket request, ever (any earlier request for it, whatever happened to it, stops another), so a failure never turns into a loop;
 - an alert that already has a ticket (found by CORE, or entered by hand) gets none;
 - hidden, set aside, resolved or closed alerts get none;
 - a pass queues at most ``MAX_PER_RULE_PASS`` per rule.
"""

from __future__ import annotations

import re
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
from app.services.core_feed_cases import insert_case_for_alert
from app.services.quarantine_release import _queue_ticket_note, check_note, quarantine_of, release_link

ACTION = "create_ticket"
VENDOR = "core"
MAX_PER_RULE_PASS = 50
CATCH_UP_MAX = 25  # when a rule is made, at most this many tickets for alerts of its type that were already open (the newest first)
TITLE_MAX = 200
DETAILS_MAX = 3000


def _release_url(alert: Any) -> str | None:
    """The link a ticket carries to release the alert's quarantined message: only for an alert that is one, and only when the console's public address is known."""
    return release_link(settings.CONSOLE_PUBLIC_BASE_URL, alert.id) if quarantine_of(alert.raw_event) is not None else None


_QUOTED = re.compile(r'"[^"]*"|“[^”]*”')
_PARENS = re.compile(r"\([^)]*\)")
_FOUND_ON = re.compile(r"\s+found on\s+.*$", re.IGNORECASE)


def type_key(signature: str) -> str:
    """What makes two alerts the same TYPE for a ticket rule (pure). An alert with a rule id is its rule id. An alert with none is its title, minus the parts that change from one alert to the next: text in quotes (a message
    subject), text in brackets (a server id) and "found on <device>". So a rule made from "...released a quarantined message: "Re: Block 2027"" covers every such message, not only that one subject, and one made from
    "ScreenConnect for another server (514f...) found on D68HM3L3" covers every device. A title with nothing left after that stays exact."""
    if not signature.startswith("title:"):
        return signature
    title = signature[len("title:") :]
    stripped = " ".join(_FOUND_ON.sub("", _PARENS.sub(" ", _QUOTED.sub(" ", title))).split()).strip(" :-").lower()
    return f"type:{stripped}" if stripped else signature


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
    catch_up: bool = False,
) -> bool:
    """Whether a rule covers an alert: the same type and tool, in the place the rule covers, and raised after the rule was made (or it is the alert the rule was made from) (pure).
    ``catch_up`` leaves out the "raised after" part: is the alert of the type this rule is for, whenever it was raised."""
    if type_key(signature_of(rule_id, title)) != type_key(rule.signature) or (rule.source or None) != (source or None):
        return False
    if rule.scope == "client" and rule.client_tenant_id != tenant_id:
        return False
    if source_alert_id is not None and alert_id == source_alert_id:
        return True
    if catch_up:
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


async def queue_for_rule(db: Any, rule: Any, now: datetime | None = None, source_alert_id: uuid.UUID | None = None, catch_up: bool = False) -> int:
    """Queue a ticket request for each alert the rule covers that has no ticket and no earlier request. Returns how many were queued. The caller owns the transaction.
    ``catch_up`` (used once, when the rule is made, if the person asked for it) also covers alerts of the type that were already open, the newest ``CATCH_UP_MAX`` of them.

    Each client's alerts are read as that client (``_acting``); the owner's own are read as the session already is."""
    now = now or datetime.now(UTC)
    queued = 0
    cases = 0
    tenants = await tenants_of(db, rule)
    halo = await _halo_clients(db, rule.tenant_id, tenants)
    cap = CATCH_UP_MAX if catch_up else MAX_PER_RULE_PASS
    for tid in tenants:
        if queued >= cap:
            break
        async with _acting(db, tid, rule.tenant_id):
            rows = (
                (
                    await db.execute(
                        select(Alert)
                        .where(Alert.tenant_id == tid, Alert.status.notin_(FINISHED_ALERT_STATUSES), *([] if catch_up else [Alert.created_at >= rule.created_at]))
                        .order_by(Alert.created_at.desc() if catch_up else Alert.created_at)
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
            covered = [
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
                    catch_up=catch_up,
                )
            ]
            if source_alert_id is not None:
                covered.sort(key=lambda a: a.id != source_alert_id)
            # A rule makes a case for each alert it covers that has none (a ticket and a case always go together), whether or not the alert already has a ticket.
            for a in covered:
                if a.case_id is None and cases < cap:
                    a.case_id = await insert_case_for_alert(
                        db,
                        tid,
                        alert_id=a.id,
                        title=a.title,
                        description=a.description,
                        severity=a.severity,
                        techniques=a.mitre_techniques,
                        tags={"source": "ticket-rule", "rule": rule.title, "auto": True},
                        now=now,
                        fallback_description=f"Opened automatically by the ticket rule \"{rule.title}\".",
                    )
                    cases += 1
            candidates = [a for a in covered if not has_ticket(a.enrichment_data)]
            if source_alert_id is not None:
                candidates.sort(key=lambda a: a.id != source_alert_id)  # the alert the rule was made from always comes first, so a cap never cuts it
            if not candidates:
                continue
            # An earlier request stops another (so a failure never turns into a loop); only the one-time catch-up, which a person asked for just now, tries again for a request that FAILED.
            earlier = (
                await db.execute(
                    select(VendorAction.alert_id, VendorAction.status).where(
                        VendorAction.tenant_id == tid,
                        VendorAction.vendor == VENDOR,
                        VendorAction.action == ACTION,
                        VendorAction.alert_id.in_([a.id for a in candidates]),
                    )
                )
            ).all()
            already = {alert for alert, state in earlier if not (catch_up and state == "failed")}  # a waiting or finished request still stands, whatever else the alert has
            for a in candidates:
                if a.id in already:
                    continue
                if queued >= cap:
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
    check = enrichment.get("quarantine_check")
    if isinstance(check, dict) and check.get("text") and not check.get("ticketed"):
        # The look into why the message was held finished before this ticket existed: put it on the ticket now (once).
        _queue_ticket_note(db, tenant_id, alert.id, [ticket_id], check_note(str(check["text"])), now)
        enrichment["quarantine_check"] = {**check, "ticketed": True}
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


async def retry_ticket(db: Any, owner: uuid.UUID, tenant_id: uuid.UUID, alert: Any, now: datetime | None = None) -> bool:
    """Ask CORE once more for the ticket of an alert whose last request failed (a person pressed Try again). Returns False when it should not: the alert already has a ticket, or its newest request is waiting, done
    or absent. The caller owns the transaction."""
    now = now or datetime.now(UTC)
    if has_ticket(alert.enrichment_data):
        return False
    rows = (
        await db.execute(
            select(VendorAction.status)
            .where(VendorAction.tenant_id == tenant_id, VendorAction.alert_id == alert.id, VendorAction.vendor == VENDOR, VendorAction.action == ACTION)
            .order_by(VendorAction.created_at.desc())
        )
    ).scalars().all()
    if not rows or rows[0] != "failed" or any(state in ("pending", "claimed", "done") for state in rows):
        return False
    halo = await _halo_clients(db, owner, [tenant_id])
    db.add(
        VendorAction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            alert_id=alert.id,
            vendor=VENDOR,
            incident_uid=f"ticket-rule:{alert.id}"[:200],
            action=ACTION,
            params=ticket_params(alert, halo.get(tenant_id), str(alert.title or ""), _release_url(alert)),
            status="pending",
            created_at=now,
        )
    )
    return True

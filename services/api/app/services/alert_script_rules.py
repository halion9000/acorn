"""Run a script automatically for an alert type, picking the script by the machine's operating system.

A rule says "when an alert of this type appears for a machine, run the Windows script on a Windows machine and the Mac script on a Mac". A.C.O.R.N runs nothing and holds no NinjaOne key: for each covered alert
it queues the same ``run_script`` request the alert page's Run script button queues (the ``vendor_actions`` queue, vendor ``core``), and CORE decides whether to ask its owner first (a script switched to
"run at once" there starts straight away, any other waits for an approval card in CORE).

Safeguards, because this acts on a client's machine on its own:
 - a rule covers only alerts raised AFTER it was made;
 - an alert gets at most ONE request from a rule, ever, whatever happened to it (so a failure never turns into a loop); an alert the rule will not act on gets a recorded "not run" row saying why, so it is also
   decided once and the reason is visible with the alert's script runs;
 - it acts only on a machine the alert names that A.C.O.R.N holds with a known operating system (Windows or macOS) AND that NinjaOne manages (CORE runs only NinjaOne scripts; a Mac managed only in Addigy is
   reported, not guessed at);
 - ``requires_tool``: the client must already have that tool on at least one machine, so a rule never acts for a client that does not use it;
 - hidden, set aside, resolved or closed alerts get none, and a pass queues at most ``MAX_PER_RULE_PASS`` per rule;
 - while a ticket request for the alert is still waiting, it waits too (so the result goes on the one ticket, not on a second);
 - never two script requests in flight for one alert.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.models.alert import Alert
from app.models.alert_script_rule import AlertScriptRule
from app.models.device import Device, DeviceSource
from app.models.tenant import Tenant
from app.models.vendor_action import VendorAction
from app.services.alert_status import FINISHED_ALERT_STATUSES
from app.services.alert_suppression import _acting, source_of
from app.services.alert_ticket_rules import ACTION as TICKET_ACTION
from app.services.alert_ticket_rules import has_ticket, rule_covers, tenants_of
from app.services.vendor_actions import PENDING_TTL

ACTION = "run_script"
VENDOR = "core"
MAX_PER_RULE_PASS = 20
RUNNER_TOOL = "ninjaone"  # the only tool CORE runs scripts through
TOOLS = ("screenconnect", "huntress", "fieldeffect", "ninjaone", "addigy")

_WINDOWS = re.compile(r"windows", re.IGNORECASE)
_MAC = re.compile(r"mac\s?os|os\s?x|darwin|\bmac\b", re.IGNORECASE)


def os_family(os: str | None) -> str | None:
    """``windows`` or ``mac`` from the operating system text a tool gave, else None (Linux, a phone, unknown). Pure."""
    text = os or ""
    if _WINDOWS.search(text):
        return "windows"
    return "mac" if _MAC.search(text) else None


def decide(
    *,
    rule: Any,
    device: str | None,
    facts: tuple[str | None, set[str]] | None,
    tool_in_use: bool,
    scripts: dict[int, Any],
) -> tuple[str, Any]:
    """What to do for one alert: ``("run", (script, device))`` or ``("skip", reason)``. Pure.

    ``facts`` is the machine's (operating system family, tools that hold it), or None when A.C.O.R.N has no such machine."""
    if device is None:
        return "skip", "The alert does not name a machine."
    if facts is None:
        return "skip", f"A.C.O.R.N has no machine named {device} for this client, so the operating system is unknown."
    family, tools = facts
    if family is None:
        return "skip", f"{device} is not a Windows or Mac machine as far as A.C.O.R.N knows."
    if RUNNER_TOOL not in tools:
        return (
            "skip",
            f"{device} is not managed in NinjaOne (it is in {', '.join(sorted(tools)) or 'no tool'}); CORE runs scripts only through NinjaOne.",
        )
    if rule.requires_tool and not tool_in_use:
        return "skip", f"This client has no machine with {rule.requires_tool}, so the rule does not apply."
    script_id = rule.windows_script_id if family == "windows" else rule.mac_script_id
    if script_id is None:
        return "skip", f"The rule has no {'Windows' if family == 'windows' else 'Mac'} script, so {device} is left alone."
    script = scripts.get(script_id)
    if script is None:
        return "skip", "CORE has not switched that script on (any more)."
    return "run", (script, device)


async def _facts(db: Any, tid: uuid.UUID, device: str) -> tuple[str | None, set[str]] | None:
    row = (
        await db.execute(
            select(Device.id, Device.os).where(Device.tenant_id == tid, func.lower(Device.hostname) == device.lower()).limit(1)
        )
    ).first()
    if row is None:
        return None
    tools = {
        r[0]
        for r in (
            await db.execute(select(DeviceSource.vendor).where(DeviceSource.tenant_id == tid, DeviceSource.device_id == row[0]))
        ).all()
    }
    return os_family(row[1]), tools


async def _tool_in_use(db: Any, tid: uuid.UUID, tool: str) -> bool:
    return (
        await db.execute(select(DeviceSource.id).where(DeviceSource.tenant_id == tid, DeviceSource.vendor == tool).limit(1))
    ).first() is not None


def _ticket_number(enrichment: Any) -> str | None:
    if not isinstance(enrichment, dict):
        return None
    for key in ("tickets", "manual_tickets"):
        for t in enrichment.get(key) or []:
            if isinstance(t, dict) and str(t.get("id", "")).strip().isdigit() and str(t.get("system") or "halopsa") == "halopsa":
                return str(t["id"]).strip()
    return None


async def queue_for_rule(
    db: Any, rule: AlertScriptRule, scripts: dict[int, Any], now: datetime | None = None, source_alert_id: uuid.UUID | None = None
) -> int:
    """Decide, once, every open alert the rule covers that it has not decided yet: queue a ``run_script`` request or record why not. Returns how many requests were queued. The caller owns the transaction.
    ``source_alert_id`` (the alert the rule was just made from) is covered too, although it was raised before the rule."""
    from app.api.v1.endpoints.alert_scripts import device_of, new_ticket_params

    now = now or datetime.now(UTC)
    queued = 0
    for tid in await tenants_of(db, rule):
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
            if source_alert_id is not None and all(r.id != source_alert_id for r in rows):
                src = (
                    await db.execute(
                        select(Alert).where(
                            Alert.id == source_alert_id, Alert.tenant_id == tid, Alert.status.notin_(FINISHED_ALERT_STATUSES)
                        )
                    )
                ).scalar_one_or_none()
                if src is not None:
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
                )
            ]
            if not covered:
                continue
            ids = [a.id for a in covered]
            earlier = (
                await db.execute(
                    select(
                        VendorAction.alert_id, VendorAction.action, VendorAction.status, VendorAction.params, VendorAction.created_at
                    ).where(
                        VendorAction.tenant_id == tid,
                        VendorAction.vendor == VENDOR,
                        VendorAction.alert_id.in_(ids),
                        VendorAction.action.in_((ACTION, TICKET_ACTION)),
                    )
                )
            ).all()
            decided = {
                r.alert_id for r in earlier if r.action == ACTION and isinstance(r.params, dict) and r.params.get("rule_id") == str(rule.id)
            }
            in_flight_script = {
                r.alert_id
                for r in earlier
                if r.action == ACTION and r.status in ("pending", "claimed") and r.created_at > now - PENDING_TTL
            }
            ticket_waiting = {
                r.alert_id
                for r in earlier
                if r.action == TICKET_ACTION and r.status in ("pending", "claimed") and r.created_at > now - PENDING_TTL
            }
            footprint: dict[str, bool] = {}
            for a in covered:
                if a.id in decided or a.id in in_flight_script or a.id in ticket_waiting:
                    continue
                if queued >= MAX_PER_RULE_PASS:
                    break
                device = device_of(a)
                facts = await _facts(db, tid, device) if device else None
                if rule.requires_tool and rule.requires_tool not in footprint:
                    footprint[rule.requires_tool] = await _tool_in_use(db, tid, rule.requires_tool)
                verdict, what = decide(
                    rule=rule, device=device, facts=facts, tool_in_use=footprint.get(rule.requires_tool or "", True), scripts=scripts
                )
                raw = a.raw_event if isinstance(a.raw_event, dict) else {}
                finding = raw.get("finding") if isinstance(raw.get("finding"), dict) else {}
                uid = finding.get("uid") if isinstance(finding.get("uid"), str) else f"alert:{a.id}"
                base = {"rule_id": str(rule.id), "alert_title": (a.title or "")[:300]}
                if verdict == "skip":
                    db.add(
                        VendorAction(
                            id=uuid.uuid4(),
                            tenant_id=tid,
                            alert_id=a.id,
                            vendor=VENDOR,
                            incident_uid=uid[:200],
                            action=ACTION,
                            params={**base, "script_name": "(not run)", "device": device or "", "script_id": 0},
                            status="failed",
                            requested_by=rule.created_by,
                            result_message=f"Not run by the script rule: {what}"[:500],
                            created_at=now,
                            finished_at=now,
                        )
                    )
                    continue
                script, machine = what
                params: dict[str, Any] = {**base, "script_id": script.id, "script_name": script.name, "device": machine}
                number = _ticket_number(a.enrichment_data) if has_ticket(a.enrichment_data) else None
                if number:
                    params["ticket_id"] = number
                else:
                    params["create_ticket"] = await new_ticket_params(db, rule.tenant_id, tid, script, a)
                db.add(
                    VendorAction(
                        id=uuid.uuid4(),
                        tenant_id=tid,
                        alert_id=a.id,
                        vendor=VENDOR,
                        incident_uid=uid[:200],
                        action=ACTION,
                        params=params,
                        status="pending",
                        requested_by=rule.created_by,
                        created_at=now,
                    )
                )
                queued += 1
            await db.flush()
    return queued


async def published(db: Any, owner: uuid.UUID) -> dict[int, Any]:
    """The scripts CORE last said are switched on, by id."""
    from app.api.v1.endpoints.alert_scripts import published_scripts

    settings = (await db.execute(select(Tenant.settings).where(Tenant.id == owner))).scalar_one_or_none()
    return {s.id: s for s in published_scripts(settings)}


async def sweep_script_rules(db: Any, now: datetime | None = None) -> int:
    """One pass over every active rule. Run by the background worker. Returns how many requests were queued."""
    now = now or datetime.now(UTC)
    rules = (await db.execute(select(AlertScriptRule).where(AlertScriptRule.revoked_at.is_(None)))).scalars().all()
    total = 0
    cache: dict[uuid.UUID, dict[int, Any]] = {}
    for rule in rules:
        if rule.tenant_id not in cache:
            cache[rule.tenant_id] = await published(db, rule.tenant_id)
        total += await queue_for_rule(db, rule, cache[rule.tenant_id], now)
    return total

"""Install a tool automatically on machines that should have it and do not (Huntress, Field Effect, the approved ScreenConnect).

A rule says "where this tool is missing, run its install script": the Windows script on a Windows machine, the Mac script on a Mac. A.C.O.R.N runs nothing and holds no NinjaOne key: for each machine in the gap it
queues the same ``run_script`` request the alert page's Run script button queues (the ``vendor_actions`` queue, vendor ``core``), and CORE decides whether to ask its owner first (a script switched to "run at once"
there starts straight away, any other waits for an approval card in CORE). So the safe default is that a person approves every install in CORE until they switch a script to run at once.

Which machines are "in the gap" is decided by the Devices page's own rule (``is_missing_from``: a computer the tool does not report, not one the client was marked as not using the tool, not one offline for
long, not one hidden), plus:
 - the client must already have the tool on at least one machine (so a rule never pushes a tool onto a client that does not use it; this is the footprint check, not a read of NinjaOne's or Addigy's policy);
 - the machine must be a Windows or Mac computer that NinjaOne manages (CORE runs scripts only through NinjaOne; a Mac managed only in Addigy is left alone and counted as not reachable);
 - at most ``MAX_PER_RULE_PASS`` machines per rule per pass, and a machine is asked for at most once in ``RE_ASK_AFTER`` (a failed install is not retried every few minutes).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.models.tool_deploy_rule import ToolDeployRule
from app.models.vendor_action import VendorAction
from app.services.alert_script_rules import RUNNER_TOOL, published
from app.services.alert_suppression import _acting
from app.services.alert_ticket_rules import _halo_clients, tenants_of

ACTION = "run_script"
VENDOR = "core"
MAX_PER_RULE_PASS = 10
RE_ASK_AFTER = timedelta(days=14)
TOOL_NAMES = {"huntress": "Huntress", "fieldeffect": "Field Effect", "screenconnect": "ScreenConnect"}


def pick_devices(devices: list[Any], tool: str) -> list[tuple[Any, str]]:
    """The machines to install ``tool`` on, as (device, "windows" or "mac"), from one client's devices (pure). Empty when the client has the tool on no machine."""
    from app.api.v1.endpoints.devices import is_missing_from, long_offline, os_family

    if not any(s.vendor == tool for d in devices for s in d.sources):
        return []
    out: list[tuple[Any, str]] = []
    for d in devices:
        if d.hidden_since is not None or long_offline(d) or not is_missing_from(d, tool):
            continue
        family = os_family(d)
        if family not in ("windows", "mac") or RUNNER_TOOL not in {s.vendor for s in d.sources}:
            continue
        out.append((d, family))
    return sorted(out, key=lambda pair: pair[0].hostname.lower())


async def queue_for_rule(db: Any, rule: ToolDeployRule, scripts: dict[int, Any], now: datetime | None = None) -> int:
    """Ask for the install on every machine in the rule's gap that has not been asked for lately. Returns how many requests were queued. The caller owns the transaction."""
    from app.api.v1.endpoints.devices import _load

    now = now or datetime.now(UTC)
    tids = await tenants_of(db, rule)
    names = await _names(db, tids)
    devices = await _load(db, rule.tenant_id, tids, names, None)
    by_tenant: dict[uuid.UUID, list[Any]] = {}
    for d in devices:
        by_tenant.setdefault(d.tenant_id, []).append(d)
    halo = await _halo_clients(db, rule.tenant_id, tids)
    queued = 0
    label = TOOL_NAMES.get(rule.tool, rule.tool)
    for tid in tids:
        wanted = pick_devices(by_tenant.get(tid, []), rule.tool)
        if not wanted or queued >= MAX_PER_RULE_PASS:
            continue
        async with _acting(db, tid, rule.tenant_id):
            asked = {
                str((p or {}).get("device", "")).lower()
                for (p,) in (
                    await db.execute(
                        select(VendorAction.params).where(
                            VendorAction.tenant_id == tid,
                            VendorAction.vendor == VENDOR,
                            VendorAction.action == ACTION,
                            VendorAction.created_at > now - RE_ASK_AFTER,
                        )
                    )
                ).all()
                if isinstance(p, dict) and p.get("deploy_rule_id") == str(rule.id)
            }
            for d, family in wanted:
                if queued >= MAX_PER_RULE_PASS:
                    break
                if d.hostname.lower() in asked:
                    continue
                script_id = rule.windows_script_id if family == "windows" else rule.mac_script_id
                script = scripts.get(script_id) if script_id is not None else None
                if script is None:
                    continue  # the rule has no script for this kind of machine, or CORE has not switched it on now: nothing is asked
                ticket: dict[str, Any] = {
                    "summary": f"Install {label} on {d.hostname}"[:200],
                    "details": f"{label} is missing on {d.hostname}, a {family.capitalize()} machine of a client that uses {label} on its other machines. Requested by an A.C.O.R.N automatic install rule; the script is {script.name}.",
                }
                if tid in halo:
                    ticket["halo_client_id"] = halo[tid]
                db.add(
                    VendorAction(
                        id=uuid.uuid4(),
                        tenant_id=tid,
                        alert_id=None,
                        vendor=VENDOR,
                        incident_uid=f"deploy:{rule.tool}:{d.hostname}"[:200],
                        action=ACTION,
                        params={
                            "script_id": script.id,
                            "script_name": script.name,
                            "device": d.hostname[:255],
                            "deploy_rule_id": str(rule.id),
                            "create_ticket": ticket,
                        },
                        status="pending",
                        requested_by=rule.created_by,
                        created_at=now,
                    )
                )
                queued += 1
            await db.flush()
    return queued


async def _names(db: Any, tids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    from app.models.tenant import Tenant

    return {r.id: r.name for r in (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.id.in_(tids)))).all()}


async def sweep_deploy_rules(db: Any, now: datetime | None = None) -> int:
    """One pass over every active rule. Run by the background worker. Returns how many requests were queued."""
    now = now or datetime.now(UTC)
    rules = (await db.execute(select(ToolDeployRule).where(ToolDeployRule.revoked_at.is_(None)))).scalars().all()
    total = 0
    cache: dict[uuid.UUID, dict[int, Any]] = {}
    for rule in rules:
        if rule.tenant_id not in cache:
            cache[rule.tenant_id] = await published(db, rule.tenant_id)
        total += await queue_for_rule(db, rule, cache[rule.tenant_id], now)
    return total

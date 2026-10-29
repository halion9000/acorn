"""The imported Sigma rules as rule packs: "buckets" of rules the MSSP applies to the clients it chooses.

The repository ships about 77 imported Sigma rules (``detections/sigma-imports``). They are loaded ONCE, as the MSSP parent's own rules, and grouped into packs by what they watch
(Windows, Linux, cloud, network, application frameworks, other). A pack does nothing for a client until the MSSP assigns it to that client (the "Rule packs" page, or
``PUT /mssp/rule-packs/{pack}/clients/{client}``); assigning it is what makes its rules part of that client's effective rules. Nothing is copied into each client.

The rules are stored ``active`` at the parent: the resolver only hands a child the ACTIVE rules of a pack it is assigned, so a rule left in testing would reach nobody. The
parent's own tenant therefore also evaluates them, which is the MSP's own organisation and is wanted.

Idempotent: a rule (matched by the Sigma id kept in its provenance), a pack (by name) and a membership that exist are left as they are, so a person's later edits and
assignments survive every restart.
"""

from __future__ import annotations

import re
from typing import Any

SOURCE = "sigma-imports"

# Pack key -> (name, what it covers). The order is the order the page lists them in.
PACKS: dict[str, tuple[str, str]] = {
    "windows": (
        "Sigma: Windows",
        "Imported Sigma rules for Windows: process creation, credential dumping, lateral movement, Defender and event-log tampering.",
    ),
    "linux": ("Sigma: Linux", "Imported Sigma rules for Linux: log clearing, privilege tools, discovery and cron abuse."),
    "cloud": ("Sigma: Cloud", "Imported Sigma rules for cloud accounts (AWS)."),
    "network": ("Sigma: Network", "Imported Sigma rules for firewall and DNS logs (clear-text protocols, crypto-mining pools)."),
    "applications": ("Sigma: Applications", "Imported Sigma rules for application framework errors (Django, Rails, Spring, Python SQL)."),
    "other": ("Sigma: Other endpoint", "Imported Sigma rules that fit none of the other packs (antivirus alerts, for example)."),
}

_SEVERITY = {"critical": "critical", "high": "high", "medium": "medium", "low": "low", "informational": "info", "info": "info"}
_TECHNIQUE = re.compile(r"^attack\.(t\d{4}(?:\.\d{3})?)$", re.IGNORECASE)
_CLOUD_PRODUCTS = {"aws", "azure", "gcp", "m365", "okta", "github"}
_NETWORK_CATEGORIES = {"firewall", "dns", "proxy"}


def folder_of(entry: dict[str, Any]) -> str:
    """The folder under ``sigma-imports`` the rule file sits in (``endpoint``, ``cloud``, ``network``), or "" when the path says none."""
    parts = str(entry.get("source_file") or "").replace("\\", "/").split("/")
    return parts[parts.index(SOURCE) + 1] if SOURCE in parts and parts.index(SOURCE) + 1 < len(parts) - 1 else ""


def pack_key(entry: dict[str, Any]) -> str:
    """Which pack a catalog-shaped entry (see ``load_catalog_detections.entry_for``) belongs in."""
    folder_name = folder_of(entry)
    product = str(entry.get("logsource_product") or "").lower()
    category = str(entry.get("logsource_category") or "").lower()
    if product in _CLOUD_PRODUCTS or folder_name == "cloud":
        return "cloud"
    if category in _NETWORK_CATEGORIES or folder_name == "network":
        return "network"
    if product == "windows":
        return "windows"
    if product == "linux":
        return "linux"
    if category == "application":
        return "applications"
    return "other"


def rule_values(entry: dict[str, Any]) -> dict[str, Any]:
    """The detection-rule columns for one entry."""
    techniques = [m.group(1).upper() for t in entry.get("tags") or [] if (m := _TECHNIQUE.match(str(t)))]
    return {
        "name": str(entry["name"])[:255],
        "description": str(entry.get("description") or "") or None,
        "rule_language": "sigma",
        "rule_body": entry["sigma_yaml"],
        "category": folder_of(entry) or "endpoint",
        "status": "active",
        "severity": _SEVERITY.get(str(entry.get("level") or "").lower(), "medium"),
        "mitre_techniques": techniques,
        "tags": list(entry.get("tags") or []),
        "is_builtin": False,
        "provenance": {
            "source": SOURCE,
            "source_id": entry["id"],
            "author": entry.get("author") or "",
            "license_url": entry.get("license_url") or "",
        },
    }


def well_formed(entry: Any) -> bool:
    """An entry that can become a rule: a dict with a text id, a text name and a text rule body (a missing one is a database error at flush time, which would stop every other rule from loading)."""
    return isinstance(entry, dict) and all(isinstance(entry.get(k), str) and entry[k].strip() for k in ("id", "name", "sigma_yaml"))


async def load_packs(session: Any, parent_id: Any, entries: list[dict[str, Any]]) -> dict[str, int]:
    """Add the rules, packs and memberships that are missing for ONE parent tenant. The caller owns the transaction (and the tenant scope) and commits.

    One malformed entry (no id, no name, no rule body) is skipped and counted, not allowed to stop the other 76. Rules and packs are added together and flushed once, and the existing memberships are read in one query,
    where this used to flush and look up a membership for every rule.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.detection_rule import DetectionRule  # noqa: PLC0415
    from app.models.mssp import MSSPRulePack, MSSPRulePackRule  # noqa: PLC0415

    report = {"rules_created": 0, "rules_existing": 0, "packs_created": 0, "links_created": 0, "skipped": 0}
    rules = {
        (r.provenance or {}).get("source_id"): r
        for r in (await session.execute(select(DetectionRule).where(DetectionRule.tenant_id == parent_id))).scalars()
        if (r.provenance or {}).get("source") == SOURCE
    }
    packs = {p.name: p for p in (await session.execute(select(MSSPRulePack).where(MSSPRulePack.parent_tenant_id == parent_id))).scalars()}
    wanted: list[tuple[Any, Any]] = []  # (pack, rule) for every well-formed entry
    for entry in entries:
        if not well_formed(entry):
            report["skipped"] += 1
            continue
        try:
            values = None if entry["id"] in rules else rule_values(entry)
            name, description = PACKS[pack_key(entry)]
        except (KeyError, TypeError, AttributeError, ValueError):
            report["skipped"] += 1
            continue
        rule = rules.get(entry["id"])
        if rule is None:
            rule = DetectionRule(tenant_id=parent_id, **values)
            session.add(rule)
            rules[entry["id"]] = rule
            report["rules_created"] += 1
        else:
            report["rules_existing"] += 1
        pack = packs.get(name)
        if pack is None:
            pack = MSSPRulePack(
                parent_tenant_id=parent_id, name=name, description=description, category="sigma", metadata_json={"source": SOURCE}
            )
            session.add(pack)
            packs[name] = pack
            report["packs_created"] += 1
        wanted.append((pack, rule))
    await session.flush()  # once: the new rules and packs get their ids here
    have = set()
    if wanted:
        pack_ids = [pack.id for pack in packs.values()]
        have = {
            (row.pack_id, row.rule_id)
            for row in (
                await session.execute(
                    select(MSSPRulePackRule.pack_id, MSSPRulePackRule.rule_id).where(MSSPRulePackRule.pack_id.in_(pack_ids))
                )
            )
        }
    for pack, rule in wanted:
        if (pack.id, rule.id) in have:
            continue
        have.add((pack.id, rule.id))
        session.add(MSSPRulePackRule(pack_id=pack.id, rule_id=rule.id))
        report["links_created"] += 1
    return report

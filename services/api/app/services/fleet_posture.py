"""Putting every client's tool checks side by side: one score per client, and the boards that gather a few related checks across all of them. Pure: no database, no clock."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

STATUS_WEIGHT = {"met": 1.0, "partly": 0.5, "not_met": 0.0}
STATUS_ORDER = {"not_met": 0, "partly": 1, "met": 2}

# A few related checks gathered across all clients, so one page can answer "which clients are about to lose something", "who has Windows 10" and so on.
BOARDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "renewals": (
        "Renewals and expiries",
        ("itglue_domain_expiry", "itglue_certificate_expiry", "liongard_iis_certificates", "cipp_subscriptions", "meraki_licence", "halopsa_agreement", "slide_appliance"),
    ),
    "licences": ("Licence waste and unused accounts", ("cipp_unused_licences", "cipp_inactive_accounts", "liongard_stale_licensed_users")),
    "windows": ("Windows support and updates", ("ninjaone_unsupported_os", "ninjaone_patching", "threatmate_end_of_life", "threatmate_patching")),
    "backups": (
        "Backups",
        ("slide_alerts", "slide_appliance", "slide_verification", "saas_backup_microsoft", "saas_backup_google", "saas_backup_email", "datto_saas_seats", "liongard_datto_bcdr"),
    ),
    "network": ("Network", ("meraki_wan", "meraki_licence", "meraki_admin_2fa")),
    "admins": (
        "Administrator accounts",
        ("meraki_admin_2fa", "dnsfilter_org_mfa", "autoelevate_enforcing", "cipp_inactive_accounts", "liongard_ad_bad_logins", "fieldeffect_account_risk"),
    ),
    "endpoints": (
        "Endpoint protection",
        ("ninjaone_antivirus", "huntress_protection", "huntress_quiet_agents", "liongard_edr_coverage", "autoelevate_enforcing", "threatmate_hardening"),
    ),
}


@dataclass(frozen=True)
class FleetCheck:
    client_id: str
    client_name: str
    source: str
    key: str
    status: str
    evidence: str
    refreshed_at: datetime | None = None
    since: datetime | None = None
    accepted: bool = False
    items: tuple[str, ...] = ()


def summarize(checks: list[FleetCheck]) -> dict[str, Any]:
    """One client's counts and score. The score is the share of its checks that are fine (a check that is only partly fine counts half), over the checks nobody has accepted; None when there are none."""
    counted = [c for c in checks if not c.accepted and c.status in STATUS_WEIGHT]
    score = int(100 * sum(STATUS_WEIGHT[c.status] for c in counted) / len(counted) + 0.5) if counted else None
    return {
        "score": score,
        "met": sum(1 for c in counted if c.status == "met"),
        "partly": sum(1 for c in counted if c.status == "partly"),
        "not_met": sum(1 for c in counted if c.status == "not_met"),
        "accepted": sum(1 for c in checks if c.accepted),
    }


def rank_clients(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Worst first: lowest score, then most problems, then name. A client with no score goes last."""
    return sorted(summaries, key=lambda s: (s["score"] is None, s["score"] if s["score"] is not None else 0, -s["not_met"], str(s.get("client_name") or "").lower()))


def average_score(scores: list[int | None]) -> int | None:
    """The mean of the clients' scores, rounded, leaving out clients with no score. None when nobody has one."""
    have = [s for s in scores if s is not None]
    return int(sum(have) / len(have) + 0.5) if have else None


def below_target(score: int | None, target: int | None) -> bool:
    """True when a client has both a score and a target and the score is under it. No score (no checks) is not below anything."""
    return score is not None and target is not None and score < target


def board_rows(checks: list[FleetCheck], keys: tuple[str, ...] | list[str], include_met: bool = False) -> list[FleetCheck]:
    """The rows of a board: the checks named, worst first (accepted ones after the rest of their status), then by client name. Fine checks only when asked for."""
    wanted = set(keys)
    rows = [c for c in checks if c.key in wanted and (include_met or c.status != "met")]
    return sorted(rows, key=lambda c: (c.accepted, STATUS_ORDER.get(c.status, 3), c.client_name.lower(), c.key))


def coverage_matrix(aliases: list[tuple[str, str]], names: dict[str, str]) -> dict[str, Any]:
    """Which tool each client is mapped to. ``aliases`` is [(client id, vendor)]; tools are listed most-used first (ties by name), clients by name, each with the tools it has and the ones it is missing among
    those at least one other client has."""
    have: dict[str, set[str]] = {}
    for cid, vendor in aliases:
        have.setdefault(cid, set()).add(vendor)
    counts: dict[str, int] = {}
    for vendors in have.values():
        for v in vendors:
            counts[v] = counts.get(v, 0) + 1
    tools = sorted(counts, key=lambda v: (-counts[v], v))
    clients = [
        {"client_id": cid, "client_name": names.get(cid, cid), "tools": [v for v in tools if v in have.get(cid, set())], "missing": [v for v in tools if v not in have.get(cid, set())]}
        for cid in names
    ]
    clients.sort(key=lambda c: (-len(c["tools"]), str(c["client_name"]).lower()))
    return {"tools": [{"vendor": v, "clients": counts[v]} for v in tools], "clients": clients}


def stale_sources(refreshed: dict[str, datetime], now: datetime, hours: int = 48) -> list[str]:
    """The sources whose latest rows for a client are older than ``hours``, for a client that should be getting them daily."""
    return sorted(s for s, t in refreshed.items() if now - t > timedelta(hours=hours))


def expiring_acceptances(rows: list[dict[str, Any]], now: datetime, within_days: int | None = None) -> list[dict[str, Any]]:
    """Accepted risks that still stand, soonest to run out first (ones with no end date last).

    Each row has ``expires_at`` (or None). One already past is not listed (it stopped counting when it ran out). ``within_days`` keeps only those that end inside that many days; an acceptance with no
    end date is never "expiring", so it is dropped when ``within_days`` is given.
    """
    live = [r for r in rows if r["expires_at"] is None or r["expires_at"] > now]
    if within_days is not None:
        limit = now + timedelta(days=within_days)
        live = [r for r in live if r["expires_at"] is not None and r["expires_at"] <= limit]
    far = datetime.max.replace(tzinfo=now.tzinfo)
    return sorted(live, key=lambda r: (r["expires_at"] or far, r.get("client_name") or ""))

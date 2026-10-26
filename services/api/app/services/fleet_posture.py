"""Putting every client's tool checks side by side: one score per client, and the boards that gather a few related checks across all of them. Pure: no database, no clock."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
    owner: str | None = None
    due_date: date | None = None


DEFAULT_WEIGHT = 1
MAX_WEIGHT = 5


def weight_of(key: str, weights: dict[str, int] | None) -> int:
    """How much a check counts: the owner's weight for it (1 to 5), else 1."""
    w = (weights or {}).get(key, DEFAULT_WEIGHT)
    return max(DEFAULT_WEIGHT, min(MAX_WEIGHT, int(w)))


def summarize(checks: list[FleetCheck], weights: dict[str, int] | None = None) -> dict[str, Any]:
    """One client's counts and score. The score is the share of its checks that are fine (a check that is only partly fine counts half), over the checks nobody has accepted; None when there are none.

    A check counts as many times as its weight (1 unless the owner raised it, up to 5): the counts stay plain counts of checks, but a heavier check moves the score further."""
    counted = [c for c in checks if not c.accepted and c.status in STATUS_WEIGHT]
    total = sum(weight_of(c.key, weights) for c in counted)
    score = int(100 * sum(weight_of(c.key, weights) * STATUS_WEIGHT[c.status] for c in counted) / total + 0.5) if counted else None
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


def search_checks(checks: list[FleetCheck], query: str, limit: int = 100) -> list[dict[str, Any]]:
    """The checks across all clients that mention ``query`` (case-insensitive) in what the tool saw, in the check's key or in the machines and accounts behind it.

    Answers "which client has SRV-02" or "who has an account called jsmith". Each hit says which client, tool and check, its status, the items that matched (up to five) and whether the evidence text matched.
    Fewer than two characters matches nothing. Problems first (not met, partly, met), then by client name.
    """
    needle = " ".join(query.lower().split())
    if len(needle) < 2:
        return []
    out: list[dict[str, Any]] = []
    for c in checks:
        in_text = needle in c.evidence.lower() or needle in c.key.lower().replace("_", " ") or needle in c.key.lower()
        matched = [i for i in c.items if needle in i.lower()]
        if not in_text and not matched:
            continue
        out.append(
            {"client_id": c.client_id, "client_name": c.client_name, "source": c.source, "key": c.key, "status": c.status, "evidence": c.evidence, "matched_items": matched[:5], "matched_text": in_text, "accepted": c.accepted}
        )
    out.sort(key=lambda r: (STATUS_ORDER.get(r["status"], 3), r["client_name"].lower(), r["key"]))
    return out[: max(1, limit)]


def score_breakdown(checks: list[FleetCheck], weights: dict[str, int] | None = None) -> dict[str, Any]:
    """Where a client's lost points went: for every counted check that is not fully met, how many points of the score it cost, biggest first.

    The points of all rows add up to ``lost`` (100 minus the unrounded score), so the list explains the whole gap. Accepted checks are left out of both sides, as in the score. None for the score when no check counts.
    """
    counted = [c for c in checks if not c.accepted and c.status in STATUS_WEIGHT]
    total = sum(weight_of(c.key, weights) for c in counted)
    if not counted:
        return {"score": None, "lost": 0.0, "rows": []}
    rows = [
        {"source": c.source, "key": c.key, "status": c.status, "weight": weight_of(c.key, weights), "points_lost": round(100 * weight_of(c.key, weights) * (1 - STATUS_WEIGHT[c.status]) / total, 1)}
        for c in counted
        if STATUS_WEIGHT[c.status] < 1
    ]
    rows.sort(key=lambda r: (-r["points_lost"], r["key"]))
    lost = 100 * sum(weight_of(c.key, weights) * (1 - STATUS_WEIGHT[c.status]) for c in counted) / total
    return {"score": int(100 - lost + 0.5), "lost": round(lost, 1), "rows": rows}


def tool_scorecards(checks: list[FleetCheck]) -> list[dict[str, Any]]:
    """For each tool: how many checks it reported across clients, how many are met, partly met and not met, how many clients have a problem from it, and the share of its checks that are fine.

    Accepted checks are left out. Worst tool (lowest share fine) first; a tool with no counted checks goes last. Answers "which tool has the most problems across clients".
    """
    by: dict[str, dict[str, Any]] = {}
    for c in checks:
        if c.accepted or c.status not in STATUS_WEIGHT:
            continue
        t = by.setdefault(c.source, {"source": c.source, "checks": 0, "met": 0, "partly": 0, "not_met": 0, "clients_with_problems": set()})
        t["checks"] += 1
        t[c.status] += 1
        if c.status != "met":
            t["clients_with_problems"].add(c.client_id)
    out = []
    for t in by.values():
        share = int(100 * (t["met"] + 0.5 * t["partly"]) / t["checks"] + 0.5) if t["checks"] else None
        out.append({"source": t["source"], "checks": t["checks"], "met": t["met"], "partly": t["partly"], "not_met": t["not_met"], "clients_with_problems": len(t["clients_with_problems"]), "percent_fine": share})
    out.sort(key=lambda r: (r["percent_fine"] is None, r["percent_fine"] if r["percent_fine"] is not None else 0, -r["not_met"], r["source"]))
    return out


SIMILAR_FACTOR = 2.0


def similar_size_average(client_size: int, others: dict[str, tuple[int, int | None]], factor: float = SIMILAR_FACTOR) -> dict[str, Any]:
    """The average score of the other clients about the same size as this one.

    ``others`` is {client: (size, score)} (size is how many machines the RMM manages; score may be None). A client is "similar" when its size is between ``client_size / factor`` and ``client_size * factor``.
    A size of 0 is not comparable. Returns the average (rounded, None when nobody similar has a score) and how many clients it is over.
    """
    if client_size <= 0:
        return {"average": None, "clients": 0}
    lo, hi = client_size / factor, client_size * factor
    scores = [sc for size, sc in others.values() if size > 0 and lo <= size <= hi and sc is not None]
    return {"average": average_score(scores), "clients": len(scores)}


def classify_change(status: str, previous: str | None) -> str:
    """How a check moved: ``new`` (first seen), ``worse``, ``better`` or ``same``, by the order not met, partly, met."""
    if previous is None:
        return "new"
    rank = {"met": 0, "partly": 1, "not_met": 2}
    a, b = rank.get(status, 1), rank.get(previous, 1)
    return "worse" if a > b else "better" if a < b else "same"


def is_overdue(status: str, due: date | None, today: date) -> bool:
    """A check is overdue when it has a due date that has passed and is still not fully met. A met check is never overdue, and the due day itself is not late."""
    return due is not None and due < today and status != "met"


def below_target(score: int | None, target: int | None) -> bool:
    """True when a client has both a score and a target and the score is under it. No score (no checks) is not below anything."""
    return score is not None and target is not None and score < target


def board_rows(checks: list[FleetCheck], keys: tuple[str, ...] | list[str], include_met: bool = False) -> list[FleetCheck]:
    """The rows of a board: the checks named, worst first (accepted ones after the rest of their status), then by client name. Fine checks only when asked for."""
    wanted = set(keys)
    rows = [c for c in checks if c.key in wanted and (include_met or c.status != "met")]
    return sorted(rows, key=lambda c: (c.accepted, STATUS_ORDER.get(c.status, 3), c.client_name.lower(), c.key))


def tool_rows(checks: list[FleetCheck], source: str, include_met: bool = False) -> list[FleetCheck]:
    """Every check one tool reported across clients, in the order of a board: worst first (accepted ones after the rest of their status), then by client name. Fine checks only when asked for."""
    rows = [c for c in checks if c.source == source and (include_met or c.status != "met")]
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

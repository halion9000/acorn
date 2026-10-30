"""The second row of SOC Insights tiles: what is waiting, what is noisy, and how much of the work the platform does without a person.

Each tile says what it measures in its ``detail`` line, and says so when it has nothing to measure (``has_data`` false, shown as a dash) instead of a zero that reads as a good result: the first
version of MTTA showed "0.0h" because no alert had ever recorded when a person first touched it.

The database reads are per tenant (row-level security shows one tenant at a time); ``merge`` adds the tenants up and ``build_tiles`` turns the totals into tiles. ``build_tiles`` does no I/O, so every
rule below is tested with plain numbers.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, or_, select

from app.models.alert import Alert
from app.models.playbook_dry_run import PlaybookDryRun
from app.models.signin import ClientM365Check, SigninEvent
from app.models.sla import TenantSLAConfig
from app.services.alert_queue import load_sla_targets, sla_due_at_expression
from app.services.alert_status import FINISHED_ALERT_STATUSES, SUPPRESSED
from app.services.sla import DEFAULT_SLA_TARGETS

TOP_N = 5
# Sign-in scores are z-scores from the UEBA service, which calls 4.0 and above "high" (services/ueba/app/services/scoring.py).
UNUSUAL_SIGNIN_SCORE = 4.0
# A source that has not reported for this long is "silent" on the sources tile.
STALE_SOURCE_MINUTES = 60
# Titles counted per tenant before the roll-up; more than this per client never reaches the top of the whole organization.
TYPES_PER_TENANT = 25  # titles kept for the whole scope


def _unfinished():
    return Alert.status.notin_(FINISHED_ALERT_STATUSES)


def _ticket_count_expr():
    """How many tickets are linked to an alert, 0 when the field is missing or is not a list."""
    tickets = Alert.enrichment_data["tickets"]
    return case((func.jsonb_typeof(tickets) == "array", func.jsonb_array_length(tickets)), else_=0)


async def _grouped_window(
    db: Any, ids: list[uuid.UUID], start: datetime, end: datetime, parts: dict[uuid.UUID, dict[str, Any]], tag: str
) -> None:
    """Counts per tenant over alerts created in [start, end) and sign-ins that happened in it: one grouped statement for each kind, whatever the number of tenants."""
    in_window = [Alert.tenant_id.in_(ids), Alert.created_at >= start, Alert.created_at < end]
    finished = Alert.status.in_(FINISHED_ALERT_STATUSES)
    without_person = or_(Alert.status == SUPPRESSED, Alert.enrichment_data.has_key("closed_in_vendor"))
    rows = (
        await db.execute(
            select(
                Alert.tenant_id,
                func.count(),
                func.count().filter(finished),
                func.count().filter(finished, without_person),
                func.count().filter(_ticket_count_expr() > 0),
            )
            .where(*in_window)
            .group_by(Alert.tenant_id)
        )
    ).all()
    for tid, alerts, fin, fin_np, ticketed in rows:
        parts[tid][tag].update(
            {"alerts": int(alerts), "finished": int(fin), "finished_without_person": int(fin_np), "ticketed": int(ticketed)}
        )
    matched = (
        await db.execute(
            select(PlaybookDryRun.tenant_id, func.count(func.distinct(PlaybookDryRun.alert_id)))
            .where(PlaybookDryRun.tenant_id.in_(ids), PlaybookDryRun.created_at >= start, PlaybookDryRun.created_at < end)
            .group_by(PlaybookDryRun.tenant_id)
        )
    ).all()
    for tid, n in matched:
        parts[tid][tag]["playbook_matched"] = int(n)
    signins = (
        await db.execute(
            select(
                SigninEvent.tenant_id,
                func.count().filter(SigninEvent.anomaly_score.is_not(None)),
                func.count().filter(SigninEvent.anomaly_score >= UNUSUAL_SIGNIN_SCORE),
            )
            .where(SigninEvent.tenant_id.in_(ids), SigninEvent.occurred_at >= start, SigninEvent.occurred_at < end)
            .group_by(SigninEvent.tenant_id)
        )
    ).all()
    for tid, scored, unusual in signins:
        parts[tid][tag].update({"signins_scored": int(scored), "signins_unusual": int(unusual)})


async def gather_all(db: Any, ids: list[uuid.UUID], start: datetime, now: datetime, prev_start: datetime) -> list[dict[str, Any]]:
    """Raw, mergeable numbers for every tenant in ``ids`` (the organization and its clients) with a few grouped statements, not a handful per tenant: 224 clients made the per-tenant version take 20 seconds.

    The caller has put ``db`` in a block that may read several tenants (``cross_tenant_reads``); every statement is limited to ``ids``.
    """
    parts: dict[uuid.UUID, dict[str, Any]] = {
        tid: {"tid": tid, "now": Counter(), "prev": Counter(), "open_now": 0, "oldest_open": None, "sla_breached": 0, "types": {}}
        for tid in ids
    }
    await _grouped_window(db, ids, start, now, parts, "now")
    await _grouped_window(db, ids, prev_start, start, parts, "prev")
    unfinished = _unfinished()
    for tid, n, oldest in (
        await db.execute(
            select(Alert.tenant_id, func.count(), func.min(Alert.created_at))
            .where(Alert.tenant_id.in_(ids), unfinished)
            .group_by(Alert.tenant_id)
        )
    ).all():
        parts[tid]["open_now"] = int(n)
        parts[tid]["oldest_open"] = oldest if isinstance(oldest, datetime) else None
    # Past the response target: the defaults in one grouped statement, and the few tenants that set their own targets one by one.
    own = {r[0] for r in (await db.execute(select(TenantSLAConfig.tenant_id).where(TenantSLAConfig.tenant_id.in_(ids)).distinct())).all()}
    default_due = sla_due_at_expression({sev: cfg["mttd_target"] for sev, cfg in DEFAULT_SLA_TARGETS.items()})
    rest = [t for t in ids if t not in own]
    if rest:
        for tid, n in (
            await db.execute(
                select(Alert.tenant_id, func.count())
                .where(Alert.tenant_id.in_(rest), unfinished, default_due < now)
                .group_by(Alert.tenant_id)
            )
        ).all():
            parts[tid]["sla_breached"] = int(n)
    for tid in own:
        due = sla_due_at_expression(await load_sla_targets(db, tid))
        parts[tid]["sla_breached"] = int(await db.scalar(select(func.count()).where(Alert.tenant_id == tid, unfinished, due < now)) or 0)
    # The noisiest alert types of the whole scope: the top few of all the titles together, which is what the tile shows.
    rows = (
        await db.execute(
            select(Alert.title, func.count().label("n"))
            .where(Alert.tenant_id.in_(ids), Alert.created_at >= start, Alert.created_at < now)
            .group_by(Alert.title)
            .order_by(func.count().desc())
            .limit(TYPES_PER_TENANT)
        )
    ).all()
    first = parts[ids[0]]
    first["types"] = {str(r[0]): int(r[1]) for r in rows}
    for tid, source, checks in (
        await db.execute(
            select(ClientM365Check.tenant_id, ClientM365Check.source, ClientM365Check.checks).where(
                ClientM365Check.tenant_id.in_(ids), ClientM365Check.source.in_(sorted({s for s, _ in WATCHED_CHECKS.values()}))
            )
        )
    ).all():
        parts[tid].setdefault("flagged", {}).update(_flags_of(source, checks))
    return list(parts.values())


# tile key -> (the tool source that sends the check, the check key). A client "reports" the check when the tool sent it; it is "flagged" when the check is not fine.
WATCHED_CHECKS: dict[str, tuple[str, str]] = {
    "leaked_credentials": ("threatmate", "threatmate_deep_dark_web"),
    "google_admins_without_2step": ("threatmate-google", "threatmate_google_admins"),
    "google_failed_sign_ins": ("threatmate-google", "threatmate_google_failed_logins"),
}


def _flags_of(source: str, checks: Any) -> dict[str, bool]:
    """For one client's checks from one tool: ``{tile key: flagged}`` for each watched check the tool sent (a check it did not send is left out, so it is not counted as fine)."""
    by_key = {str(c.get("key")): str(c.get("status")) for c in (checks or []) if isinstance(c, dict)}
    return {tile: by_key[key] != "met" for tile, (src, key) in WATCHED_CHECKS.items() if src == source and key in by_key}


def merge(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Add the tenants up. ``types`` keeps each title's count over all the tenants that reported it."""
    m: dict[str, Any] = {"now": Counter(), "prev": Counter()}
    for p in parts:
        for tag in ("now", "prev"):
            m[tag].update(p[tag])
    m["open_now"] = sum(p["open_now"] for p in parts)
    olds = [p["oldest_open"] for p in parts if p.get("oldest_open") is not None]
    m["oldest_open"] = min(olds) if olds else None
    m["sla_breached"] = sum(p["sla_breached"] for p in parts)
    types: Counter[str] = Counter()
    for p in parts:
        types.update(p["types"])
    m["types"] = types
    m["by_tenant"] = {p["tid"]: p["now"]["alerts"] for p in parts}
    # tile key -> {client id: flagged}: only the clients whose tool reported the check.
    m["flagged"] = {tile: {p["tid"]: p["flagged"][tile] for p in parts if tile in p.get("flagged", {})} for tile in WATCHED_CHECKS}
    return m


def age_phrase(then: datetime | None, now: datetime) -> str:
    """ "3 days", "5 hours" or "12 minutes": the age of the oldest open alert, cut down to whole units."""
    if then is None:
        return "none open"
    seconds = max(0, int((now - then).total_seconds()))
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            n = seconds // size
            return f"{n} {unit}{'' if n == 1 else 's'}"
    return "under a minute"


def _share(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def _change(current: float, previous: float, ready: bool) -> float | None:
    if not ready or previous == 0:
        return None
    return round(((current - previous) / previous) * 100.0, 2)


def _items_from(counter: Counter[str], total: int, names: dict[str, str] | None = None) -> list[dict[str, Any]]:
    out = []
    for key, n in counter.most_common(TOP_N):
        pct = f" ({round(100 * n / total)}%)" if total else ""
        out.append({"label": (names or {}).get(key, key), "value": float(n), "display": f"{n}{pct}"})
    return out


def build_tiles(
    m: dict[str, Any],
    *,
    now: datetime,
    ready: bool,
    sparkline: list[float],
    client_names: dict[uuid.UUID, str] | None = None,
    sources: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """The tiles as plain dicts for ``InsightTile``. ``client_names`` (whole organization only) adds the noisiest-clients tile; ``sources`` is ``{"total": n, "silent": [(name, minutes_ago_or_None)]}``."""
    cur, prev = m["now"], m["prev"]
    tiles: list[dict[str, Any]] = []

    def tile(
        key: str,
        label: str,
        value: float,
        unit: str,
        previous: float = 0.0,
        *,
        has_data: bool = True,
        detail: str | None = None,
        items=None,
        spark=None,
    ) -> None:
        tiles.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "unit": unit,
                "previous_value": previous,
                "delta_pct": _change(value, previous, ready) if has_data else None,
                "sparkline": {"points": spark or []},
                "has_data": has_data,
                "detail": detail,
                "items": items or [],
            }
        )

    open_now = m["open_now"]
    tile("open_alerts", "Open alerts now", float(open_now), "count", detail=f"Oldest: {age_phrase(m['oldest_open'], now)}", spark=sparkline)
    tile(
        "sla_breaches",
        "Past response target",
        float(m["sla_breached"]),
        "count",
        has_data=open_now > 0,
        detail=f"{m['sla_breached']} of {open_now} open alerts are past their severity's response target",
    )
    total = cur["alerts"]
    types = m["types"]
    top_types = _items_from(types, total)
    top_types_n = sum(i["value"] for i in top_types)
    tile(
        "noisy_alert_types",
        "Noisiest alert types",
        _share(int(top_types_n), total),
        "pct",
        has_data=total > 0,
        detail=f"The top {len(top_types)} types are this share of the window's {total} alerts",
        items=top_types,
    )
    if client_names:
        by_key = Counter({str(t): n for t, n in m["by_tenant"].items() if n})
        names = {str(t): client_names.get(t, str(t)) for t in m["by_tenant"]}
        top_clients = _items_from(by_key, total, names)
        tile(
            "noisiest_clients",
            "Noisiest clients",
            _share(int(sum(i["value"] for i in top_clients)), total),
            "pct",
            has_data=total > 0,
            detail=f"The top {len(top_clients)} clients are this share of the window's {total} alerts",
            items=top_clients,
        )
    fin, fin_prev = cur["finished"], prev["finished"]
    rate, rate_prev = _share(cur["finished_without_person"], fin), _share(prev["finished_without_person"], fin_prev)
    tile(
        "automation_rate",
        "Closed without a person",
        rate,
        "pct",
        rate_prev,
        has_data=fin > 0,
        detail=f"{cur['finished_without_person']} of {fin} finished alerts were closed by a suppression rule or by the vendor itself",
    )
    scored = cur["signins_scored"]
    tile(
        "unusual_signins",
        "Unusual sign-ins",
        float(cur["signins_unusual"]),
        "count",
        float(prev["signins_unusual"]),
        has_data=scored > 0,
        detail=f"{cur['signins_unusual']} of {scored} scored sign-ins scored {UNUSUAL_SIGNIN_SCORE:g} or more",
    )
    if sources is not None:
        silent = sources["silent"]
        tile(
            "silent_sources",
            "Silent sources",
            float(len(silent)),
            "count",
            has_data=sources["total"] > 0,
            detail=f"{sources['total'] - len(silent)} of {sources['total']} sources reported in the last {STALE_SOURCE_MINUTES} minutes",
            items=[
                {"label": name, "value": float(mins or 0), "display": "never reported" if mins is None else f"{mins} min ago"}
                for name, mins in silent[:TOP_N]
            ],
        )
    flagged = m.get("flagged") or {}
    for key, label, noun in (
        ("leaked_credentials", "Clients with leaked credentials", "have open dark web findings"),
        ("google_admins_without_2step", "Clients with Google admins lacking 2-Step", "have a super admin without 2-Step"),
        ("google_failed_sign_ins", "Clients with many failed Google sign-ins", "had many failed sign-ins in the last week"),
    ):
        reported = flagged.get(key, {})
        bad = sorted((t for t, v in reported.items() if v), key=str)
        tile(
            key,
            label,
            float(len(bad)),
            "count",
            has_data=len(reported) > 0,
            detail=f"{len(bad)} of {len(reported)} clients that report this {noun}",
            items=[{"label": (client_names or {}).get(t, str(t)), "value": 1.0, "display": "flagged"} for t in bad[:TOP_N]]
            if client_names
            else [],
        )
    pb, pb_prev = _share(cur["playbook_matched"], total), _share(prev["playbook_matched"], prev["alerts"])
    tile(
        "playbook_coverage",
        "Alerts a playbook matches",
        pb,
        "pct",
        pb_prev,
        has_data=total > 0,
        detail=f"{cur['playbook_matched']} of {total} alerts matched a playbook in a dry run (a dry run does nothing; this is what the playbooks would cover)",
    )
    tk, tk_prev = _share(cur["ticketed"], total), _share(prev["ticketed"], prev["alerts"])
    tile(
        "ticket_linkage",
        "Alerts with a ticket",
        tk,
        "pct",
        tk_prev,
        has_data=total > 0,
        detail=f"{cur['ticketed']} of {total} alerts have a linked ticket",
    )
    return tiles

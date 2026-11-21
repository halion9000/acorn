"""Scheduled reports (roadmap r7-af-32, Hal 2026-11-18: "a report scheduler system: for any report choose who gets it, how often, etc.").

A schedule names a report kind (``KINDS``), recipients, a frequency (daily; weekly on a weekday; monthly on day 1 to 28) and an hour (UTC). ``due`` says whether one is due now (pure): it has not run since its
latest slot. ``render`` works the report out as plain text for the e-mail body (the mailer sends text only), for the schedule's own organization or client. Kinds are added by writing one renderer and listing it
here. Sending needs the mail credentials; a report with nothing to say is not sent (a note says so), except when its kind always has something.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.models.trust_audit import Audit, AuditRequest

MAX_EMAILS = 20
FREQUENCIES = ("daily", "weekly", "monthly")

Renderer = Callable[[Any, uuid.UUID, datetime], Awaitable[tuple[str, str] | None]]


def slot_before(frequency: str, day: int, hour: int, now: datetime) -> datetime:
    """The most recent moment at or before ``now`` this schedule was due to run (pure)."""
    now = now.astimezone(UTC)
    at = now.replace(minute=0, second=0, microsecond=0)
    if frequency == "daily":
        slot = at.replace(hour=hour)
        return slot if slot <= now else slot - timedelta(days=1)
    if frequency == "weekly":
        slot = (at - timedelta(days=(at.weekday() - day) % 7)).replace(hour=hour)
        return slot if slot <= now else slot - timedelta(days=7)
    slot = at.replace(day=min(max(day, 1), 28), hour=hour)
    if slot <= now:
        return slot
    month_before = (at.replace(day=1) - timedelta(days=1)).replace(day=min(max(day, 1), 28), hour=hour)
    return month_before


def due(frequency: str, day: int, hour: int, last_run_at: datetime | None, now: datetime) -> bool:
    """True when the latest slot has passed with no run since it (pure). A schedule never run is due at its first slot after it was made, which the caller sets as ``last_run_at`` on creation."""
    if last_run_at is None:
        return True
    return last_run_at.astimezone(UTC) < slot_before(frequency, day, hour, now)


def clean_emails(raw: list[str]) -> list[str]:
    """The addresses, trimmed, lower case, de-duplicated, at most 20, each with one @ and a dot after it (pure)."""
    out: list[str] = []
    for a in raw:
        a = (a or "").strip().lower()
        if a and a.count("@") == 1 and "." in a.split("@")[1] and " " not in a and a not in out:
            out.append(a)
    return out[:MAX_EMAILS]


async def _compliance_actions(db: Any, tenant: uuid.UUID, now: datetime) -> tuple[str, str] | None:
    from app.api.v1.endpoints.compliance_dashboard import build_dashboard  # noqa: PLC0415 - that module is large
    from app.services import compliance_notice as cn  # noqa: PLC0415

    board = await build_dashboard(db, tenant)
    items = [i.model_dump() for i in board.action_items]
    if not items:
        return None
    subject, text, _payload = cn.digest(items, now, "", "")
    return subject, text


async def _open_audit_requests(db: Any, tenant: uuid.UUID, now: datetime) -> tuple[str, str] | None:
    audits = {a.id: a for a in (await db.execute(select(Audit).where(Audit.tenant_id == tenant, Audit.status != "complete"))).scalars()}
    if not audits:
        return None
    lines = []
    today = now.date()
    for r in (await db.execute(select(AuditRequest).where(AuditRequest.tenant_id == tenant, AuditRequest.status == "open"))).scalars():
        a = audits.get(r.audit_id)
        if a is None:
            continue
        late = " (overdue)" if r.due_date is not None and r.due_date < today else ""
        lines.append((a.name, r.due_date or date.max, f"- {a.name}: {r.title}{', due ' + r.due_date.isoformat() if r.due_date else ''}{late}"))
    if not lines:
        return None
    lines.sort(key=lambda x: (x[0], x[1]))
    return f"Open audit requests: {len(lines)}", "\n".join([f"{len(lines)} audit request{'s' if len(lines) != 1 else ''} still open:"] + [x[2] for x in lines[:200]])


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
MAX_VULN_LINES = 60


def new_vulnerabilities_text(rows: list[dict[str, Any]], now: datetime, days: int = 7) -> tuple[str, str] | None:
    """The vulnerabilities first seen in the last ``days`` days, by client, worst first (pure). Each row has ``client``, ``cve``, ``software``, ``severity``, ``devices``, ``exploited`` and ``first_seen``.
    None when there are none. Vulnerabilities that went away are not listed: A.C.O.R.N keeps only what is open now, so a fixed one leaves no trace to compare."""
    since = now - timedelta(days=days)
    fresh = [r for r in rows if r["first_seen"] >= since]
    if not fresh:
        return None
    fresh.sort(key=lambda r: (SEVERITY_ORDER.get(str(r["severity"]).lower(), 9), not r.get("exploited"), str(r["client"]).lower(), str(r["cve"])))
    lines = [
        f"- {r['client'] or 'Live Oak'}: {r['cve']} ({str(r['severity']).lower()}{', exploited' if r.get('exploited') else ''}) in {r['software']}, {r['devices']} device{'' if r['devices'] == 1 else 's'}"
        for r in fresh[:MAX_VULN_LINES]
    ]
    more = f"\n...and {len(fresh) - MAX_VULN_LINES} more" if len(fresh) > MAX_VULN_LINES else ""
    n = len(fresh)
    return f"{n} new vulnerabilit{'y' if n == 1 else 'ies'} in the last {days} days", f"{n} vulnerabilit{'y' if n == 1 else 'ies'} first seen in the last {days} days:\n" + "\n".join(lines) + more


async def _new_vulnerabilities(db: Any, tenant: uuid.UUID, now: datetime) -> tuple[str, str] | None:
    from app.db.rls_scope import acting_as_tenant  # noqa: PLC0415
    from app.models.client_vulnerability import ClientVulnerability  # noqa: PLC0415
    from app.models.tenant import Tenant  # noqa: PLC0415

    names = {r.id: r.name for r in (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == tenant))).all()}
    rows: list[dict[str, Any]] = []
    since = now - timedelta(days=7)
    for tid in [tenant, *names]:
        async with contextlib.nullcontext() if tid == tenant else acting_as_tenant(db, tid):
            found = (await db.execute(select(ClientVulnerability).where(ClientVulnerability.tenant_id == tid, ClientVulnerability.first_seen >= since))).scalars().all()
        rows += [
            {"client": names.get(tid) or "", "cve": v.cve_id, "software": v.software, "severity": v.severity, "devices": v.devices, "exploited": v.exploited, "first_seen": v.first_seen}
            for v in found
        ]
    return new_vulnerabilities_text(rows, now)


async def _org_mismatch(db: Any, tenant: uuid.UUID, now: datetime) -> tuple[str, str] | None:
    from app.api.v1.endpoints.device_reports import org_mismatch_rows  # noqa: PLC0415
    from app.services import device_reports as dr  # noqa: PLC0415

    return dr.org_mismatch_text(await org_mismatch_rows(db, tenant))


def digest_text(d: Any) -> tuple[str, str] | None:
    """The executive weekly digest as plain text (pure over the digest model): the headline, alerts and cases, the time to respond, the top tactics and sources, the recommendations. Always has something to say."""
    p = d.period
    lines = [d.headline, f"Period: {p.label}"]
    a, c = d.alerts, d.cases
    lines += [
        "",
        f"Alerts: {a.total} in the period, {a.new} new, {a.resolved} resolved, {a.open_at_period_end} open at the end (critical {a.severity.critical}, high {a.severity.high})",
        f"Cases: {c.opened} opened, {c.closed} closed, {c.open_at_period_end} open at the end, {c.sla_breached} past their deadline",
        *( [f"Time to respond (hours): detect {d.mtt.mttd_hours}, respond {d.mtt.mttr_hours}, close {d.mtt.mttc_hours}"] if d.mtt.mttr_hours is not None else []),
    ]
    if d.top_tactics:
        lines += ["", "Top tactics:"] + [f"- {t.tactic} ({t.count})" for t in d.top_tactics[:5]]
    if d.top_sources:
        lines += ["", "Top sources:"] + [f"- {t.label or t.connector_type} ({t.count})" for t in d.top_sources[:5]]
    if d.high_risk_alerts:
        lines += ["", "Highest risk alerts:"] + [f"- {h.title}" for h in d.high_risk_alerts[:5]]
    if d.recommendations:
        lines += ["", "Recommendations:"] + [f"- {r.title}: {r.body}" for r in d.recommendations[:6]]
    return d.headline[:150], "\n".join(x for x in lines if x is not None)


async def _executive_digest(db: Any, tenant: uuid.UUID, now: datetime) -> tuple[str, str] | None:
    from app.services.executive_digest import build_weekly_digest  # noqa: PLC0415

    return digest_text(await build_weekly_digest(db, tenant))


def licence_waste_text(rows: list[dict[str, Any]]) -> tuple[str, str] | None:
    """The licenses bought but not assigned, by client, most first (pure). Quantities only, never prices. None when there are none."""
    if not rows:
        return None
    total = sum(int(r["unassigned"]) for r in rows)
    lines = [f"- {r['client_name']}: {r['item']} ({r['source']}): {r['unassigned']} of {r['bought']} unassigned ({r['percent']}%){' (count is old)' if r.get('stale') else ''}" for r in rows[:60]]
    more = f"\n...and {len(rows) - 60} more lines" if len(rows) > 60 else ""
    clients = len({r["client_name"] for r in rows})
    return f"{total} unassigned licenses at {clients} clients", f"{total} licenses bought and not assigned to anyone, {len(rows)} lines at {clients} clients:\n" + "\n".join(lines) + more


async def _licence_waste(db: Any, tenant: uuid.UUID, now: datetime) -> tuple[str, str] | None:
    from app.api.v1.endpoints.billing import _all_count_rows, _scope  # noqa: PLC0415
    from app.services.licence_waste import waste_rows  # noqa: PLC0415

    ids, names = await _scope(db, tenant, None)
    counts = await _all_count_rows(db, ids[1:])
    return licence_waste_text([r.__dict__ for r in waste_rows(counts, names, now, 1)])


def fleet_review_text(d: dict[str, Any]) -> tuple[str, str] | None:
    """The client review: what got worse and better since yesterday, what is overdue, which accepted risks end soon and who is under target (pure over the fleet digest as a dict of lists of {client_name, text})."""
    sections = [("Got worse", "worse"), ("Got better", "better"), ("Overdue", "overdue"), ("Accepted risks ending within a week", "expiring"), ("Clients under their target", "below_target")]
    lines: list[str] = []
    for title, key in sections:
        items = d.get(key) or []
        if items:
            lines += ["", f"{title} ({d.get('counts', {}).get(key, len(items))}):"] + [f"- {i['client_name']}: {i['text']}" for i in items[:25]]
    if not lines:
        return None
    return "Client review: what needs attention", "\n".join(lines).lstrip("\n")


async def _client_review(db: Any, tenant: uuid.UUID, now: datetime) -> tuple[str, str] | None:
    from types import SimpleNamespace  # noqa: PLC0415

    from app.api.v1.endpoints.client_posture import fleet_digest  # noqa: PLC0415

    out = await fleet_digest(SimpleNamespace(tenant_id=tenant), db, days=7, limit=25)
    return fleet_review_text(out.model_dump())


def net_income_text(rows: list[dict[str, Any]], month: str) -> tuple[str, str] | None:
    """Net income for a month, per client (pure over [{client_name, revenue, net_income}]): the totals, how many clients lost money, the five best and five worst. None with no rows."""
    if not rows:
        return None
    revenue = sum(float(r["revenue"]) for r in rows)
    net = sum(float(r["net_income"]) for r in rows)
    losing = [r for r in rows if float(r["net_income"]) < 0]
    ranked = sorted(rows, key=lambda r: float(r["net_income"]))
    money = lambda v: f"{'-' if v < 0 else ''}${abs(v):,.0f}"  # noqa: E731
    lines = [
        f"Net income for {month}: {money(net)} on {money(revenue)} of revenue ({(100 * net / revenue):.1f}%), {len(rows)} clients, {len(losing)} lost money.",
        "",
        "Lowest five:",
        *[f"- {r['client_name']}: {money(float(r['net_income']))}" for r in ranked[:5]],
        "",
        "Highest five:",
        *[f"- {r['client_name']}: {money(float(r['net_income']))}" for r in reversed(ranked[-5:])],
    ]
    return f"Net income {month}: {money(net)}", "\n".join(lines)


async def _net_income(db: Any, tenant: uuid.UUID, now: datetime) -> tuple[str, str] | None:
    from types import SimpleNamespace  # noqa: PLC0415

    from app.api.v1.endpoints.finance import profitability_summary  # noqa: PLC0415

    out = await profitability_summary(SimpleNamespace(tenant_id=tenant), db, month=None)
    through = out.get("through")
    if not through:
        return None
    rows = []
    for r in out.get("rows") or []:
        m = (r.get("by_month") or {}).get(through)
        if m:
            rows.append({"client_name": r["client_name"], "revenue": m["revenue"], "net_income": m["net_income"]})
    return net_income_text(rows, through)


KINDS: dict[str, tuple[str, Renderer]] = {
    "executive_digest": ("Executive digest for the week (alerts, cases, response times, what to do)", _executive_digest),
    "client_review": ("Client review: what got worse, overdue, ending and under target", _client_review),
    "net_income": ("Net income by client for the last complete month", _net_income),
    "licence_waste": ("Licenses bought but not assigned (all clients)", _licence_waste),
    "org_mismatch": ("Machines filed under different clients in Huntress and NinjaOne", _org_mismatch),
    "new_vulnerabilities": ("New vulnerabilities in the last 7 days (all clients)", _new_vulnerabilities),
    "compliance_actions": ("Compliance action items (what needs doing now)", _compliance_actions),
    "open_audit_requests": ("Open audit requests with due dates", _open_audit_requests),
}


async def render(kind: str, db: Any, tenant: uuid.UUID, now: datetime) -> tuple[str, str] | None:
    """The subject and text of a report, or None when it has nothing to say. Raises KeyError for an unknown kind."""
    return await KINDS[kind][1](db, tenant, now)

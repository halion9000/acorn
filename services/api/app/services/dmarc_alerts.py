"""An alert when a client's DMARC pass rate falls sharply from one week to the next.

A domain that passed 98% of its mail last week and 71% this week has changed: a sender was moved or its DKIM key expired (real mail now failing), or someone has started sending as the domain. Either way
the owner wants to hear about it before the policy is tightened or the mail is rejected. The rule reads the stored reports, compares the last seven days with the seven before, and names the sending
addresses whose failing mail grew most.

Two honest limits are built in. A week with only a few messages swings wildly, so both weeks need at least ``MIN_EMAILS`` messages (a quiet domain is never alerted on). And reports arrive a day or more
after the mail was sent, so the most recent days are often incomplete; the alert says so rather than pretending the week is whole.

The detector is a pure function over report rows (anything with the attributes of ``DmarcReport``); ``run_pass_rate_detection`` loads the rows and saves the alerts. An alert has a fixed id built from the
client, the domain and the ISO week, so running it every half hour raises one alert per domain per week, never a stream.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.identity_detections import Finding, alert_values

logger = logging.getLogger("aisoc.dmarc_alerts")

RULE_ID = "aisoc-dmarc-pass-rate-drop"
RULE_NAME = "DMARC pass rate dropped"
MIN_EMAILS = 50  # messages needed in EACH of the two weeks
DROP_POINTS = 10.0  # percentage points the pass rate must fall
HIGH_BELOW = 50.0  # a pass rate under this is high severity, otherwise medium
WINDOW = timedelta(days=7)
TOP_SENDERS = 3


@dataclass
class Drop:
    tenant_id: uuid.UUID
    finding: Finding


def _utc(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _rate(passed: int, total: int) -> float:
    return passed * 100.0 / total if total else 0.0


def detect_pass_rate_drops(reports: list[Any], now: datetime) -> list[Drop]:
    """One drop per client and domain whose pass rate fell by ``DROP_POINTS`` or more, with enough mail in both weeks to mean something."""
    now = _utc(now)
    start_this, start_before = now - WINDOW, now - 2 * WINDOW
    weeks: dict[tuple[uuid.UUID, str], dict[str, list[Any]]] = defaultdict(lambda: {"this": [], "before": []})
    for r in reports:
        end = _utc(r.end_at)
        if start_this < end <= now:
            weeks[(r.tenant_id, r.domain)]["this"].append(r)
        elif start_before < end <= start_this:
            weeks[(r.tenant_id, r.domain)]["before"].append(r)

    out: list[Drop] = []
    iso = now.isocalendar()
    for (tenant_id, domain), w in sorted(weeks.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        total_now, total_before = sum(r.total for r in w["this"]), sum(r.total for r in w["before"])
        if total_now < MIN_EMAILS or total_before < MIN_EMAILS:
            continue
        rate_now = _rate(sum(r.passed for r in w["this"]), total_now)
        rate_before = _rate(sum(r.passed for r in w["before"]), total_before)
        if rate_before - rate_now < DROP_POINTS:
            continue
        failing_now, failing_before = _failing_by_sender(w["this"]), _failing_by_sender(w["before"])
        grown = sorted(((ip, n - failing_before.get(ip, 0), n) for ip, n in failing_now.items() if n > failing_before.get(ip, 0)), key=lambda t: (-t[1], t[0]))[:TOP_SENDERS]
        fields = [
            ("Domain", domain),
            ("Pass rate this week", f"{rate_now:.0f}% of {total_now} messages"),
            ("Pass rate the week before", f"{rate_before:.0f}% of {total_before} messages"),
        ]
        for ip, _more, n in grown:
            fields.append(("Failing more", f"{ip}: {n} failing messages this week, {failing_before.get(ip, 0)} the week before"))
        if not grown:
            fields.append(("Failing more", "No single sending address accounts for it; the failures are spread across many"))
        out.append(
            Drop(
                tenant_id,
                Finding(
                    rule_id=RULE_ID,
                    rule_name=RULE_NAME,
                    title=f"DMARC pass rate for {domain} fell from {rate_before:.0f}% to {rate_now:.0f}%",
                    severity="high" if rate_now < HIGH_BELOW else "medium",
                    tactic="Initial Access",
                    technique="T1566",
                    key=f"{domain}:{iso[0]}-W{iso[1]:02d}",
                    occurred_at=now,
                    summary=(
                        f"Mail sent as {domain} passed DMARC {rate_before:.0f}% of the time in the week before and {rate_now:.0f}% in the last seven days. Either a real sender has stopped authenticating "
                        "(a moved service, an expired DKIM key, a changed SPF record) or someone is sending as the domain. Look at the sending addresses below before tightening the policy. "
                        "Reports arrive a day or more after the mail, so the most recent days may be incomplete."
                    ),
                    fields=fields,
                    ips=[ip for ip, _, _ in grown],
                    source_ids=[],
                ),
            )
        )
    return out


def _failing_by_sender(reports: list[Any]) -> dict[str, int]:
    failing: dict[str, int] = defaultdict(int)
    for r in reports:
        for row in r.rows or []:
            if not row.get("pass"):
                failing[str(row.get("ip") or "")] += int(row.get("count", 0))
    failing.pop("", None)
    return dict(failing)


async def run_pass_rate_detection(db: Any, now: datetime | None = None) -> int:
    """Load the last fourteen days of reports for every client, raise an alert for each drop, and return how many alerts were new. Never raises: a failure here must not stop the mailbox reader."""
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.alert import Alert
    from app.models.dmarc import DmarcReport

    now = now or datetime.now(UTC)
    try:
        reports = (await db.execute(select(DmarcReport).where(DmarcReport.matched.is_(True), DmarcReport.end_at >= now - 2 * WINDOW))).scalars().all()
        drops = detect_pass_rate_drops(list(reports), now)
        made = 0
        async with db.begin_nested():
            for d in drops:
                values = alert_values(d.tenant_id, d.finding, now)
                values.update(
                    category="email",
                    connector_type="dmarc",
                    tags=["email", "dmarc", RULE_ID],
                    raw_event={"source": "aisoc-dmarc", "finding": {"uid": f"{RULE_ID}:{d.finding.key}", "title": d.finding.title}},
                )
                res = await db.execute(pg_insert(Alert).values(**values).on_conflict_do_nothing(index_elements=["id"]))
                made += res.rowcount or 0
        return made
    except Exception:  # noqa: BLE001
        logger.warning("dmarc pass-rate detection failed", exc_info=True)
        return 0

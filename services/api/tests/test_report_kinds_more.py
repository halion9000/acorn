"""The reports that can be scheduled by email (roadmap r7-af-32): the executive digest, the client review, net income and license waste, as plain text."""

from datetime import UTC, datetime

from app.services import report_scheduler as rs
from app.services.executive_digest import (
    AlertSummary,
    AutomationSummary,
    CaseSummary,
    DigestPeriod,
    DigestRecommendation,
    ExecutiveDigest,
    HighRiskAlertHighlight,
    MttSummary,
    SeveritySplit,
    TacticHighlight,
    TopSourceHighlight,
)
import uuid

NOW = datetime(2026, 11, 21, tzinfo=UTC)


def test_every_kind_has_a_name_and_the_four_new_ones_are_listed():
    assert {"executive_digest", "client_review", "net_income", "licence_waste"} <= set(rs.KINDS)
    assert all(name.strip() and callable(fn) for name, fn in rs.KINDS.values())


def test_the_executive_digest_reads_as_text_with_the_numbers_and_the_advice():
    d = ExecutiveDigest(
        tenant_id=uuid.uuid4(),
        period=DigestPeriod(start=NOW, end=NOW, label="Nov 14 to Nov 21, 2026"),
        headline="A quiet week: 40 alerts, 2 cases",
        alerts=AlertSummary(total=40, new=10, resolved=30, open_at_period_end=12, severity=SeveritySplit(critical=1, high=4)),
        cases=CaseSummary(opened=2, closed=1, open_at_period_end=3, sla_breached=0),
        mtt=MttSummary(mttd_hours=1.5, mttr_hours=4.0, mttc_hours=6.0),
        top_tactics=[TacticHighlight(tactic="Credential Access", count=9, delta_from_prior=2)],
        top_sources=[TopSourceHighlight(connector_type="cipp", count=20, label="CIPP")],
        high_risk_alerts=[HighRiskAlertHighlight(alert_id="a", title="Impossible travel - US to RO", severity="high", ai_score=0.9, mitre_tactics=[], event_time=NOW)],
        automation=AutomationSummary(total_decisions=0, auto_executed=0, escalated=0, review_pending=0),
        recommendations=[DigestRecommendation(severity="info", title="Review MFA", body="Three admins have no MFA.")],
    )
    subject, text = rs.digest_text(d)
    assert subject == "A quiet week: 40 alerts, 2 cases"
    for part in ("Nov 14 to Nov 21, 2026", "40 in the period", "2 opened, 1 closed", "respond 4.0", "Credential Access (9)", "CIPP (20)", "Impossible travel", "Review MFA: Three admins have no MFA."):
        assert part in text, part


def test_license_waste_lists_quantities_by_client_and_says_nothing_when_there_is_none():
    assert rs.licence_waste_text([]) is None
    rows = [
        {"client_name": "Acme", "item": "Business Premium", "source": "cipp", "bought": 20, "unassigned": 6, "percent": 30, "stale": False},
        {"client_name": "Birch", "item": "Huntress", "source": "huntress", "bought": 5, "unassigned": 2, "percent": 40, "stale": True},
    ]
    subject, text = rs.licence_waste_text(rows)
    assert subject == "8 unassigned licenses at 2 clients"
    assert "Acme: Business Premium (cipp): 6 of 20 unassigned (30%)" in text and "(count is old)" in text and "$" not in text


def test_net_income_gives_the_totals_who_lost_money_and_the_best_and_worst_five():
    rows = [{"client_name": f"C{i}", "revenue": 1000, "net_income": n} for i, n in enumerate([-500, -100, 50, 200, 300, 400, 450, 500])]
    subject, text = rs.net_income_text(rows, "2026-10")
    assert subject == "Net income 2026-10: $1,300"
    assert "8 clients, 2 lost money" in text and "C0: -$500" in text and "C7: $500" in text and "16.2%" in text
    assert rs.net_income_text([], "2026-10") is None


def test_the_client_review_lists_each_group_and_is_empty_when_all_is_quiet():
    d = {
        "counts": {"worse": 3, "overdue": 1},
        "worse": [{"client_name": "Acme", "text": "mfa is now not met"}],
        "overdue": [{"client_name": "Birch", "text": "patching is overdue (Dan, due 2026-11-01)"}],
        "better": [], "expiring": [], "below_target": [],
    }
    subject, text = rs.fleet_review_text(d)
    assert subject.startswith("Client review") and "Got worse (3):" in text and "- Acme: mfa is now not met" in text and "Overdue (1):" in text and "Got better" not in text
    assert rs.fleet_review_text({"counts": {}, "worse": [], "better": [], "overdue": [], "expiring": [], "below_target": []}) is None

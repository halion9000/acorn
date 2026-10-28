"""Automatic playbooks, first version: which playbooks WOULD have run for an alert (a dry run; nothing is run)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from app.db.database import Base
from app.models.alert import Alert
from app.models.playbook_dry_run import PlaybookDryRun
from app.models.tenant import Tenant
from app.services import playbook_dry_runs as dr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)

ATO = {
    "id": "ato-mfa-fatigue-response-v1",
    "name": "ATO: MFA Fatigue",
    "enabled": True,
    "trigger": {"on": "alert", "severity": ["medium", "high"], "tags": ["account-takeover"]},
    "steps": [
        {"id": "e1", "type": "enrich", "name": "Enrich the user"},
        {"id": "n1", "type": "notify"},
        {"id": "r1", "type": "revoke_session"},
    ],
}
RANSOM = {
    "id": "ransom-v1",
    "name": "Ransomware",
    "enabled": True,
    "trigger": {"on": "alert", "severity": ["critical"], "tags": ["ransomware"]},
    "steps": [],
}


def test_an_alert_names_itself_by_its_tags_category_and_techniques():
    assert dr.alert_signals(["Account-Takeover", " "], "Identity", ["T1621", "T1078.004", 5]) == {
        "account-takeover",
        "identity",
        "mitre.t1621",
        "mitre.t1078",
        "mitre.t1078.004",
    }
    assert dr.alert_signals(None, None, None) == set()


def test_a_trigger_matches_on_severity_and_a_shared_tag_and_says_why():
    assert dr.trigger_matches(ATO["trigger"], "high", {"account-takeover", "x"}) == ["severity high", "tag account-takeover"]
    assert dr.trigger_matches(ATO["trigger"], "HIGH", {"account-takeover"}) is not None, "case does not matter"


def test_a_trigger_does_not_match_the_wrong_severity_no_shared_tag_or_a_trigger_that_is_too_broad():
    assert dr.trigger_matches(ATO["trigger"], "critical", {"account-takeover"}) is None
    assert dr.trigger_matches(ATO["trigger"], "high", {"ransomware"}) is None
    assert dr.trigger_matches({"on": "alert", "severity": ["high"]}, "high", {"account-takeover"}) is None, "no tags: matches nothing"
    assert dr.trigger_matches({"on": "alert"}, "high", {"anything"}) is None
    assert dr.trigger_matches({"on": "schedule", "tags": ["account-takeover"]}, "high", {"account-takeover"}) is None
    assert dr.trigger_matches(None, "high", {"account-takeover"}) is None


def test_a_trigger_with_tags_but_no_severity_matches_on_the_tag_alone():
    assert dr.trigger_matches({"on": "alert", "tags": ["bec"]}, "low", {"bec"}) == ["tag bec"]


def test_only_enabled_playbooks_with_a_matching_trigger_would_run():
    off = {**ATO, "id": "off", "enabled": False}
    found = dr.would_run([ATO, RANSOM, off, {"enabled": True}, "junk"], "high", {"account-takeover"})  # type: ignore[list-item]
    assert [pb["id"] for pb, _ in found] == ["ato-mfa-fatigue-response-v1"]


def test_the_steps_are_listed_in_order_with_their_type_and_name():
    assert dr.steps_of(ATO) == [
        {"id": "e1", "type": "enrich", "name": "Enrich the user"},
        {"id": "n1", "type": "notify", "name": ""},
        {"id": "r1", "type": "revoke_session", "name": ""},
    ]
    assert len(dr.steps_of({"steps": [{"id": str(i), "type": "http"} for i in range(80)]})) == dr.MAX_STEPS


def run(coro_fn):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as c:
            await c.run_sync(
                lambda conn: Base.metadata.create_all(conn, tables=[Tenant.__table__, Alert.__table__, PlaybookDryRun.__table__])
            )
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            try:
                return await coro_fn(s)
            finally:
                await engine.dispose()

    return asyncio.run(main())


def alert(tid, *, severity="high", tags=(), category="identity", status="new", age_hours=1, techniques=()):
    return Alert(
        id=uuid.uuid4(),
        tenant_id=tid,
        title=f"alert {uuid.uuid4().hex[:4]}",
        severity=severity,
        status=status,
        category=category,
        tags=list(tags),
        mitre_techniques=list(techniques),
        event_time=NOW - timedelta(hours=age_hours),
        first_seen=NOW - timedelta(hours=age_hours),
        last_seen=NOW - timedelta(hours=age_hours),
        created_at=NOW - timedelta(hours=age_hours),
    )


def test_recording_adds_a_row_for_each_matching_alert_once_and_skips_old_finished_and_unrelated_alerts():
    async def body(s):
        t = Tenant(id=uuid.uuid4(), name="Acme", slug="acme")
        s.add(t)
        await s.flush()
        hit = alert(t.id, tags=["account-takeover"])
        by_technique = alert(t.id, severity="medium", category="identity", techniques=["T1621"])
        s.add_all(
            [
                hit,
                by_technique,
                alert(t.id, tags=["account-takeover"], status="resolved"),
                alert(t.id, tags=["account-takeover"], age_hours=30),
                alert(t.id, tags=["other"], category="x"),
            ]
        )
        await s.commit()
        mfa_by_technique = {**ATO, "id": "mfa-t", "trigger": {"on": "alert", "severity": ["medium"], "tags": ["mitre.t1621"]}}
        first = await dr.record_for_tenant(s, t.id, [ATO, mfa_by_technique], NOW)
        await s.commit()
        again = await dr.record_for_tenant(s, t.id, [ATO, mfa_by_technique], NOW)
        await s.commit()
        rows = (await s.execute(select(PlaybookDryRun))).scalars().all()
        return first, again, {(r.alert_id, r.playbook_id) for r in rows}, hit.id, by_technique.id, rows

    first, again, keys, hit_id, tech_id, rows = run(body)
    assert (first, again) == (2, 0), "two matches the first time, nothing the second"
    assert keys == {(hit_id, "ato-mfa-fatigue-response-v1"), (tech_id, "mfa-t")}
    by_pb = {r.playbook_id: r for r in rows}
    assert by_pb["ato-mfa-fatigue-response-v1"].matched_on == ["severity high", "tag account-takeover"]
    assert [s["type"] for s in by_pb["ato-mfa-fatigue-response-v1"].steps] == ["enrich", "notify", "revoke_session"]

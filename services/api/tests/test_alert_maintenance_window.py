"""Maintenance windows: a client rule for every alert type between two times. It hides nothing before it starts, never hides critical alerts, is short, and gives the alerts back when it ends."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import alert_suppressions as ep
from app.services import alert_suppression as sup
from fastapi import HTTPException
from pydantic import ValidationError

OWNER, CLIENT, OTHER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def window(**over):
    base = {"id": uuid.uuid4(), "tenant_id": OWNER, "scope": "client", "client_tenant_id": CLIENT, "device_key": None, "source": None, "signature": sup.WINDOW_SIGNATURE, "revoked_at": None, "starts_at": None, "expires_at": None,
                "revoked_reason": None}
    base.update(over)
    return SimpleNamespace(**base)


def now():
    return datetime.now(UTC)


def test_a_window_is_active_only_between_its_start_and_its_end():
    t = now()
    w = window(starts_at=t + timedelta(hours=1), expires_at=t + timedelta(hours=5))
    assert not sup.is_active(w, t)  # not started
    assert sup.is_active(w, t + timedelta(hours=2))
    assert not sup.is_active(w, t + timedelta(hours=5))  # ended
    assert not sup.is_active(window(starts_at=t - timedelta(hours=1), expires_at=t + timedelta(hours=1), revoked_at=t), t)  # lifted early
    assert sup.is_active(window(starts_at=None, expires_at=t + timedelta(hours=1)), t)  # a rule made before the column existed has no start


def test_a_window_covers_every_alert_type_of_its_client_and_nothing_of_another_client():
    w = window()
    for title, rid, src in [("Anything", None, "ninjaone"), ("Other", "rule-9", "huntress"), ("x", None, None)]:
        assert sup.matches(w, tenant_id=CLIENT, rule_id=rid, title=title, source=src, hosts=[])
    assert not sup.matches(w, tenant_id=OTHER, rule_id=None, title="Anything", source="ninjaone", hosts=[])


def test_an_ordinary_rule_still_needs_its_own_type_and_tool():
    r = window(signature="title:Disk full", source="ninjaone")
    assert sup.matches(r, tenant_id=CLIENT, rule_id=None, title="Disk full", source="ninjaone", hosts=[])
    assert not sup.matches(r, tenant_id=CLIENT, rule_id=None, title="Other", source="ninjaone", hosts=[])
    assert not sup.matches(r, tenant_id=CLIENT, rule_id=None, title="Disk full", source="huntress", hosts=[])


def test_a_window_never_hides_critical_alerts():
    text = str(sup._type_filter(window()).compile(compile_kwargs={"literal_binds": True}))
    assert "severity" in text and "critical" in text and "!=" in text


class SweepDB:
    def __init__(self, rules):
        self.rules, self.commits = rules, 0

    async def execute(self, statement):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.rules))

    async def commit(self):
        self.commits += 1


def test_the_sweep_leaves_a_window_that_has_not_started_hides_for_one_that_has_and_gives_back_when_it_ends(monkeypatch):
    t = now()
    applied, released = [], []

    async def fake_apply(db, r, owner):
        applied.append(r)
        return 4

    async def fake_release(db, r, owner):
        released.append(r)
        return 2

    monkeypatch.setattr(sup, "apply_rule", fake_apply)
    monkeypatch.setattr(sup, "release_rule", fake_release)
    future = window(starts_at=t + timedelta(hours=3), expires_at=t + timedelta(hours=9))
    running = window(starts_at=t - timedelta(hours=1), expires_at=t + timedelta(hours=1))
    over = window(starts_at=t - timedelta(hours=9), expires_at=t - timedelta(hours=1))
    out = asyncio.run(sup.sweep(SweepDB([future, running, over]), t))
    assert applied == [running] and released == [over]
    assert (out["expired"], out["hidden"], out["restored"]) == (1, 4, 2)
    assert future.revoked_at is None, "a window that has not started must not be treated as ended"
    assert over.revoked_reason == "expired" and over.revoked_at == over.expires_at and running.revoked_at is None


class StartDB:
    def __init__(self, kids):
        self.kids, self.added, self.commits = kids, [], 0

    async def execute(self, statement):
        return SimpleNamespace(all=lambda: [SimpleNamespace(id=i, name=n) for i, n in self.kids.items()])

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for o in self.added:
            o.id = o.id or uuid.uuid4()
            o.created_at = o.created_at or now()

    async def commit(self):
        self.commits += 1


@pytest.fixture
def applied(monkeypatch):
    calls = []

    async def fake_apply(db, r, owner):
        calls.append(r)
        return 7

    monkeypatch.setattr(ep, "apply_rule", fake_apply)
    return calls


def start(db, **over):
    body = ep.MaintenanceIn(**{"client_id": CLIENT, "hours": 4, **over})
    return asyncio.run(ep.start_maintenance(body, SimpleNamespace(tenant_id=OWNER, user_id=uuid.uuid4()), db))


def test_starting_now_stores_a_client_window_and_hides_the_open_alerts_right_away(applied):
    db = StartDB({CLIENT: "Acme"})
    out = start(db, reason="Server migration")
    r = db.added[0]
    assert (r.scope, r.client_tenant_id, r.tenant_id, r.signature, r.source) == ("client", CLIENT, OWNER, sup.WINDOW_SIGNATURE, None)
    assert r.title == "Maintenance: Server migration" and (r.expires_at - r.starts_at) == timedelta(hours=4)
    assert applied == [r] and out.maintenance is True and out.hidden_alerts == 7 and out.client_name == "Acme" and out.active is True


def test_a_window_that_starts_later_hides_nothing_yet(applied):
    db = StartDB({CLIENT: "Acme"})
    out = start(db, starts_at=now() + timedelta(days=2))
    assert applied == [] and out.hidden_alerts == 0 and out.active is False and db.commits == 1


def test_the_managing_company_can_open_a_window_for_itself_but_not_for_a_stranger(applied):
    assert start(StartDB({}), client_id=OWNER).client_id == OWNER
    with pytest.raises(HTTPException) as e:
        start(StartDB({CLIENT: "Acme"}), client_id=OTHER)
    assert e.value.status_code == 404
    assert len(applied) == 1  # only the managing company's own window; nothing was hidden for the stranger


@pytest.mark.parametrize("hours", [0, -1, 73, 1000])
def test_a_window_is_one_to_seventy_two_hours(hours):
    with pytest.raises(ValidationError):
        ep.MaintenanceIn(client_id=CLIENT, hours=hours)


def test_a_window_cannot_start_in_the_past_or_more_than_thirty_days_away(applied):
    with pytest.raises(HTTPException) as past:
        start(StartDB({CLIENT: "Acme"}), starts_at=now() - timedelta(hours=1))
    with pytest.raises(HTTPException) as far:
        start(StartDB({CLIENT: "Acme"}), starts_at=now() + timedelta(days=31))
    assert (past.value.status_code, far.value.status_code) == (422, 422) and applied == []

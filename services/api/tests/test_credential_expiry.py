"""Credential end-date reminders: strict validation, days left, warnings at 30 and 7 days, an audited platform-admin save, and a health page that survives an unreadable list."""

import asyncio
import uuid
from datetime import date
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import health
from app.api.v1.endpoints import platform_credential_expiries as ep
from app.services import credential_expiry as ce
from fastapi import HTTPException

TODAY = date(2026, 11, 5)


def test_good_entries_are_trimmed_and_kept_as_typed_otherwise():
    assert ce.clean_entries([{"name": "  Entra   secret ", "expires_on": " 2027-01-31 "}]) == [
        {"name": "Entra secret", "expires_on": "2027-01-31"}
    ]
    assert ce.clean_entries([]) == []


@pytest.mark.parametrize(
    "raw,fragment",
    [
        ("nope", "must be a list"),
        ([1], "not a name and a date"),
        ([{"name": "  ", "expires_on": "2027-01-01"}], "no name"),
        ([{"name": "x" * 81, "expires_on": "2027-01-01"}], "longer than"),
        ([{"name": "A", "expires_on": "31/01/2027"}], "YYYY-MM-DD"),
        ([{"name": "A", "expires_on": "2027-02-30"}], "YYYY-MM-DD"),
        ([{"name": "A", "expires_on": "2027-01-01"}, {"name": "a", "expires_on": "2027-02-01"}], "listed twice"),
        ([{"name": f"c{i}", "expires_on": "2027-01-01"} for i in range(51)], "At most 50"),
    ],
)
def test_bad_entries_are_refused_with_what_is_wrong_never_dropped(raw, fragment):
    with pytest.raises(ce.InvalidEntries) as e:
        ce.clean_entries(raw)
    assert fragment in str(e.value)


def test_a_malformed_stored_list_reads_as_empty_not_as_a_failure():
    assert ce.stored_entries(None) == [] and ce.stored_entries({}) == []
    assert ce.stored_entries({"credential_expiries": "garbage"}) == []
    assert ce.stored_entries({"credential_expiries": [{"name": "A", "expires_on": "2027-01-01"}]}) == [
        {"name": "A", "expires_on": "2027-01-01"}
    ]


def test_days_left_are_counted_from_today_negative_once_past_and_soonest_first():
    rows = ce.with_days_left(
        [
            {"name": "Later", "expires_on": "2026-12-25"},
            {"name": "Past", "expires_on": "2026-11-01"},
            {"name": "Today", "expires_on": "2026-11-05"},
        ],
        TODAY,
    )
    assert [(r["name"], r["days_left"]) for r in rows] == [("Past", -4), ("Today", 0), ("Later", 50)]


def test_a_warning_starts_at_thirty_days_and_is_an_error_from_seven_or_once_past():
    rows = ce.with_days_left(
        [
            {"name": n, "expires_on": d}
            for n, d in [
                ("a31", "2026-12-06"),
                ("a30", "2026-12-05"),
                ("a8", "2026-11-13"),
                ("a7", "2026-11-12"),
                ("a1", "2026-11-06"),
                ("a0", "2026-11-05"),
                ("gone", "2026-10-01"),
            ]
        ],
        TODAY,
    )
    by = {w["text"].split()[0]: w for w in ce.warning_rows(rows)}
    assert "a31" not in by, "thirty-one days is not yet a warning"
    assert by["a30"]["level"] == "warn" and by["a8"]["level"] == "warn"
    assert by["a7"]["level"] == "error" and by["a1"]["level"] == "error" and by["gone"]["level"] == "error"
    assert "expires in 1 day (" in by["a1"]["text"] and "expires today" in by["a0"]["text"] and "has expired" in by["gone"]["text"]
    assert by["a30"]["key"] == "credential_expiry:a30"


def test_the_health_page_carries_the_reminders_as_warnings():
    rows = ce.with_days_left([{"name": "Entra secret", "expires_on": "2026-11-10"}], TODAY)
    warnings = health.platform_warnings(
        down=[],
        disk=None,
        pending=None,
        core_feed=None,
        device_feeds=[],
        signins=None,
        loop=None,
        failing_connectors=None,
        credential_expiries=rows,
    )
    assert [w["key"] for w in warnings] == ["credential_expiry:entra secret"]


class FakeDB:
    def __init__(self, owner):
        self.owner = owner
        self.commits = 0
        self.nested = MagicMock()

    async def get(self, _model, _id):
        return self.owner

    async def commit(self):
        self.commits += 1


def user():
    return NS(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())


def test_saving_replaces_the_list_keeps_the_other_settings_audits_names_only_and_returns_days_left(monkeypatch):
    audits = []

    async def fake_audit(**kw):
        audits.append(kw)

    monkeypatch.setattr(ep, "emit_audit", fake_audit)
    owner = NS(id=uuid.uuid4(), settings={"keep": 1, "credential_expiries": [{"name": "Old", "expires_on": "2026-12-01"}]})
    db = FakeDB(owner)
    out = asyncio.run(ep.replace_credential_expiries(ep.Entries(entries=[ep.Entry(name="New cert", expires_on="2027-06-01")]), user(), db))
    assert owner.settings["keep"] == 1 and owner.settings["credential_expiries"] == [{"name": "New cert", "expires_on": "2027-06-01"}]
    assert [e.name for e in out.entries] == ["New cert"] and db.commits == 1
    (entry,) = audits
    assert entry["action"] == "platform:credential_expiries_changed"
    assert entry["changes"] == {"names_before": ["Old"], "names_after": ["New cert"]}, "names only, which carry no secret"


def test_a_bad_save_is_422_and_changes_nothing(monkeypatch):
    monkeypatch.setattr(ep, "emit_audit", AsyncMock())
    owner = NS(id=uuid.uuid4(), settings={"credential_expiries": [{"name": "Keep", "expires_on": "2027-01-01"}]})
    db = FakeDB(owner)
    with pytest.raises(HTTPException) as e:
        asyncio.run(ep.replace_credential_expiries(ep.Entries(entries=[ep.Entry(name="A", expires_on="soon")]), user(), db))
    assert e.value.status_code == 422 and "YYYY-MM-DD" in e.value.detail
    assert owner.settings == {"credential_expiries": [{"name": "Keep", "expires_on": "2027-01-01"}]} and db.commits == 0


def test_the_health_reader_returns_none_when_the_list_cannot_be_read():
    class Broken:
        def begin_nested(self):
            raise RuntimeError("settings unreadable")

    assert asyncio.run(health._credential_expiries_or_none(Broken(), user())) is None


def test_the_routes_need_platform_cross_tenant_query():
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    for method in ("GET", "PUT"):
        assert set(required_permissions(found[(method, "/platform/credential-expiries")])) == {"platform:cross_tenant_query"}

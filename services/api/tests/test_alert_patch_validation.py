"""``PATCH /alerts/{id}`` and ``POST /alerts/{id}/snooze``: bad values are a 422/400, a change of status is audited, a snooze keeps its reason, and the list filters have length caps.

Before: any status ("banana"; a 31-character one was a 500 from the database), any priority (-5), any number of tags (10,000), no audit line for a status change (the bulk close writes one), a snooze whose ``reason`` was accepted and dropped and whose ``until`` could be in the past,
a 1 MB ``search`` string into three ILIKEs, and a source link check whose ``$`` accepted a trailing newline.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.api.v1 import deps
from app.api.v1.deps import CurrentUser
from app.api.v1.endpoints import alerts as ep
from app.api.v1.endpoints.alerts import AlertSnoozeRequest, AlertUpdateRequest, snooze_alert, update_alert
from app.db.rls import get_tenant_db
from app.main import app
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_alerts_tenant_isolation import _alert as _full_alert  # tests/ is on sys.path (pytest's default import mode)


def _client() -> TestClient:
    user = CurrentUser(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="platform_admin", email="p@example.com", scopes=None)

    async def fake_db():
        yield None

    app.dependency_overrides[get_tenant_db] = fake_db
    app.dependency_overrides[deps.get_db] = fake_db
    app.dependency_overrides[deps.get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _clean():
    yield
    app.dependency_overrides.clear()


class TestTheUpdateModel:
    def test_an_unknown_status_is_refused_and_a_known_one_is_normalised(self):
        for bad in ("banana", "x" * 31, "suppressed", ""):
            with pytest.raises(ValidationError):
                AlertUpdateRequest(status=bad)
        assert AlertUpdateRequest(status=" Resolved ").status == "resolved"
        for good in ("new", "triaged", "investigating", "in_progress", "closed", "false_positive", "fp"):
            assert AlertUpdateRequest(status=good).status == good

    def test_priority_is_zero_to_one_hundred(self):
        for bad in (-5, 101, 10**12):
            with pytest.raises(ValidationError):
                AlertUpdateRequest(priority=bad)
        assert AlertUpdateRequest(priority=0).priority == 0 and AlertUpdateRequest(priority=100).priority == 100

    def test_tags_are_limited_trimmed_and_unique(self):
        with pytest.raises(ValidationError):
            AlertUpdateRequest(tags=[f"t{i}" for i in range(51)])
        for bad in ("", "   ", "x" * 65):
            with pytest.raises(ValidationError):
                AlertUpdateRequest(tags=[bad])
        assert AlertUpdateRequest(tags=["  vip   user ", "vip user", "b"]).tags == ["vip user", "b"]

    def test_nothing_sent_stays_nothing(self):
        req = AlertUpdateRequest()
        assert (req.status, req.priority, req.tags) == (None, None, None)


class TestOverHttp:
    def test_a_bad_patch_is_a_422_before_the_database_is_touched(self):
        url = f"/api/v1/alerts/{uuid.uuid4()}"
        for body in ({"status": "banana"}, {"status": "x" * 31}, {"priority": -5}, {"tags": ["t"] * 10_000}):
            response = _client().patch(url, json=body)
            assert response.status_code == 422, (list(body), response.status_code, response.text[:100])

    def test_the_list_filters_have_length_caps(self):
        client = _client()
        for name in ("search", "category", "severity", "status"):
            response = client.get("/api/v1/alerts", params={name: "x" * 1_000})
            assert response.status_code == 422, (name, response.status_code)  # all four are over their caps (200, 128, 64, 64)


def _alert(tenant: uuid.UUID, status: str = "new") -> Any:
    return _full_alert(tenant, status=status)  # the same builder the tenant-isolation tests use: every field the response needs


def _db(alert: Any) -> MagicMock:
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=alert)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _user(tenant: uuid.UUID) -> CurrentUser:
    return CurrentUser(user_id=uuid.uuid4(), tenant_id=tenant, role="soc_analyst", email="a@example.com")


@pytest.mark.asyncio
class TestTheAuditLine:
    async def test_a_change_of_status_is_audited_with_before_and_after(self):
        tenant = uuid.uuid4()
        alert = _alert(tenant, "new")
        audit = AsyncMock()
        with patch.object(ep, "emit_audit", audit):
            await update_alert(alert.id, AlertUpdateRequest(status="false_positive"), _user(tenant), _db(alert))
        kwargs = audit.await_args.kwargs
        assert kwargs["action"] == "alerts:status_change" and kwargs["resource_id"] == str(alert.id)
        assert kwargs["changes"] == {"status_from": "new", "status_to": "false_positive"}
        assert kwargs["tenant_id"] == tenant

    async def test_a_patch_that_changes_no_status_writes_no_status_line(self):
        tenant = uuid.uuid4()
        alert = _alert(tenant, "new")
        audit = AsyncMock()
        with patch.object(ep, "emit_audit", audit):
            await update_alert(alert.id, AlertUpdateRequest(priority=70), _user(tenant), _db(alert))
            await update_alert(alert.id, AlertUpdateRequest(status="new"), _user(tenant), _db(alert))
        audit.assert_not_awaited()


@pytest.mark.asyncio
class TestSnooze:
    async def test_the_reason_is_kept_in_the_audit_log(self):
        tenant = uuid.uuid4()
        alert = _alert(tenant)
        audit = AsyncMock()
        with patch.object(ep, "emit_audit", audit):
            await snooze_alert(
                alert.id, AlertSnoozeRequest(duration_minutes=30, reason="  waiting   for the vendor  "), _user(tenant), _db(alert)
            )
        assert audit.await_args.kwargs["changes"]["reason"] == "waiting for the vendor"
        assert audit.await_args.kwargs["action"] == "alerts:snooze"

    async def test_a_snooze_with_no_reason_has_none_in_the_line(self):
        tenant = uuid.uuid4()
        alert = _alert(tenant)
        audit = AsyncMock()
        with patch.object(ep, "emit_audit", audit):
            await snooze_alert(alert.id, AlertSnoozeRequest(duration_minutes=30), _user(tenant), _db(alert))
        assert "reason" not in audit.await_args.kwargs["changes"]

    async def test_until_must_be_in_the_future_and_within_thirty_days(self):
        tenant = uuid.uuid4()
        alert = _alert(tenant)
        db = _db(alert)
        for until in (datetime.now(UTC) - timedelta(minutes=1), datetime.now(UTC) + timedelta(days=31)):
            with pytest.raises(HTTPException) as exc:
                await snooze_alert(alert.id, AlertSnoozeRequest(until=until), _user(tenant), db)
            assert exc.value.status_code == 400
        db.execute.assert_not_awaited()
        with patch.object(ep, "emit_audit", AsyncMock()):
            ok = await snooze_alert(alert.id, AlertSnoozeRequest(until=datetime.now(UTC) + timedelta(days=2)), _user(tenant), _db(alert))
        assert ok.id == alert.id

    async def test_a_reason_over_five_hundred_characters_is_refused(self):
        with pytest.raises(ValidationError):
            AlertSnoozeRequest(duration_minutes=5, reason="x" * 501)


class TestTheSourceLinkCheck:
    def test_a_trailing_newline_is_not_a_link(self):
        for good in ("https://acme.huntress.io/x", "HTTPS://A.test/p?q=1"):
            assert ep._HTTPS.fullmatch(good)
        for bad in ("https://acme.huntress.io/x\n", "https://x y", "http://x", "https://", "https://x\n\nrm"):
            assert not ep._HTTPS.fullmatch(bad), repr(bad)

    def test_the_device_and_user_link_filter_uses_the_same_rule(self):
        alert = SimpleNamespace(raw_event={"links": {"device_url": "https://ok.test/d", "user_url": "https://bad.test/u\n"}})
        assert ep._links_of(alert) == {"device_url": "https://ok.test/d"}

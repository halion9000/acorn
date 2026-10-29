"""Insider-threat requests: an indicator can only link this organization's own alert, inputs are bounded, and taking a person off the watchlist forgets why and when they were put on it.

Before: ``source_alert_id`` was stored without checking whose alert it was (another tenant's alert id linked through), every text and JSON field was unbounded, and un-watchlisting left the old reason, date and person in place.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import insider_threat as ep
from fastapi import HTTPException
from pydantic import ValidationError

TENANT = uuid.uuid4()
USER = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT)


def _profile(**over):
    base = {
        "id": uuid.uuid4(),
        "tenant_id": TENANT,
        "is_watchlisted": False,
        "watchlist_reason": None,
        "watchlisted_at": None,
        "watchlisted_by": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _db(profile, alert_owned: bool = True):
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)
    db.scalar = AsyncMock(return_value=uuid.uuid4() if alert_owned else None)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _indicator(profile_id, **over):
    return ep.IndicatorCreate(
        **{"profile_id": profile_id, "indicator_type": "off_hours_download", "description": "Downloaded 4 GB at 3 am", **over}
    )


class TestSourceAlert:
    def test_an_alert_of_another_tenant_is_a_404_and_nothing_is_stored(self):
        profile = _profile()
        db = _db(profile, alert_owned=False)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(ep.create_indicator(_indicator(profile.id, source_alert_id=uuid.uuid4()), db, USER))
        assert exc.value.status_code == 404 and exc.value.detail == "Alert not found"
        db.add.assert_not_called()
        db.commit.assert_not_awaited()

    def test_the_alert_lookup_is_scoped_to_the_callers_tenant(self):
        profile = _profile()
        db = _db(profile, alert_owned=True)
        asyncio.run(ep.create_indicator(_indicator(profile.id, source_alert_id=uuid.uuid4()), db, USER))
        compiled = db.scalar.await_args.args[0].compile()
        assert "alerts.tenant_id" in str(compiled) and "alerts.id" in str(compiled)
        assert TENANT in compiled.params.values(), "the caller's tenant is what the alert is checked against"
        db.add.assert_called_once()

    def test_an_indicator_with_no_source_alert_needs_no_lookup(self):
        profile = _profile()
        db = _db(profile)
        asyncio.run(ep.create_indicator(_indicator(profile.id), db, USER))
        db.scalar.assert_not_awaited()
        db.add.assert_called_once()


class TestWatchlist:
    def _set(self, profile, **body):
        return asyncio.run(ep.update_watchlist(profile.id, ep.WatchlistUpdate(**body), _db(profile), USER))

    def test_adding_records_the_reason_the_time_and_the_person(self):
        profile = _profile()
        self._set(profile, is_watchlisted=True, watchlist_reason="Resigned, working notice")
        assert profile.is_watchlisted and profile.watchlist_reason == "Resigned, working notice"
        assert isinstance(profile.watchlisted_at, datetime) and profile.watchlisted_by == USER.id

    def test_removing_forgets_all_three(self):
        profile = _profile(
            is_watchlisted=True, watchlist_reason="old reason", watchlisted_at=datetime.now(UTC), watchlisted_by=uuid.uuid4()
        )
        self._set(profile, is_watchlisted=False)
        assert profile.is_watchlisted is False
        assert (profile.watchlist_reason, profile.watchlisted_at, profile.watchlisted_by) == (None, None, None)

    def test_a_reason_sent_while_removing_is_not_kept(self):
        profile = _profile(is_watchlisted=True, watchlist_reason="old", watchlisted_at=datetime.now(UTC), watchlisted_by=uuid.uuid4())
        self._set(profile, is_watchlisted=False, watchlist_reason="leftover note")
        assert profile.watchlist_reason is None

    def test_a_profile_of_another_tenant_is_a_404(self):
        profile = _profile(tenant_id=uuid.uuid4())
        with pytest.raises(HTTPException) as exc:
            asyncio.run(ep.update_watchlist(profile.id, ep.WatchlistUpdate(is_watchlisted=True), _db(profile), USER))
        assert exc.value.status_code == 404 and profile.is_watchlisted is False


class TestBounds:
    def test_an_indicator_is_bounded(self):
        pid = uuid.uuid4()
        assert _indicator(pid, severity="critical").severity == "critical"
        for bad in (
            {"severity": "banana"},
            {"indicator_type": ""},
            {"indicator_type": "t" * 101},
            {"description": ""},
            {"description": "d" * 4001},
            {"evidence": {"blob": "z" * 20_000}},
        ):
            with pytest.raises(ValidationError):
                _indicator(pid, **bad)

    def test_a_peer_group_is_bounded(self):
        assert ep.PeerGroupCreate(name="Finance", criteria={"department": "finance"}).name == "Finance"
        for bad in (
            {"name": ""},
            {"name": "n" * 256},
            {"name": "x", "description": "d" * 4001},
            {"name": "x", "criteria": {"b": "z" * 20_000}},
        ):
            with pytest.raises(ValidationError):
                ep.PeerGroupCreate(**bad)

    def test_a_watchlist_reason_is_bounded(self):
        with pytest.raises(ValidationError):
            ep.WatchlistUpdate(is_watchlisted=True, watchlist_reason="r" * 1001)

    def test_what_comes_back_reads_a_stored_group_whatever_its_size(self):
        out = ep.PeerGroupOut.model_validate(
            SimpleNamespace(
                id=uuid.uuid4(), tenant_id=uuid.uuid4(), name="n" * 300, description=None, criteria={}, created_at=datetime.now(UTC)
            ),
            from_attributes=True,
        )
        assert len(out.name) == 300

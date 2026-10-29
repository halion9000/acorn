"""Asset and vulnerability requests: a PATCH changes only what it sends, values are bounded and from a fixed list, and nothing a caller sends can be longer than its column.

Before: ``PATCH /assets/{id}`` with ``{"name": "x"}`` reset the type to "host", the criticality to "medium" and the metadata to {} (the update model was the create model, and its defaults were applied); criticality and severity were free text;
every string was unbounded, so a 600-character name was a database error answered with a 500.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import assets as ep
from fastapi import HTTPException
from pydantic import ValidationError


def _asset(tenant: uuid.UUID, **over):
    base = {
        "id": uuid.uuid4(),
        "tenant_id": tenant,
        "asset_type": "server",
        "name": "FS-01",
        "fqdn": "fs01.acme.test",
        "ip_addresses": ["10.0.0.5"],
        "cloud_provider": None,
        "cloud_region": None,
        "cloud_account": None,
        "os": "Windows Server",
        "os_version": "2022",
        "criticality": "high",
        "tags": ["file-server"],
        "owner_email": "it@acme.test",
        "asset_metadata": {"rack": "A2"},
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "last_seen": datetime.now(UTC),
        "first_seen": datetime.now(UTC),
    }
    base.update(over)
    return SimpleNamespace(**base)


def _db(asset):
    db = MagicMock()
    db.get = AsyncMock(return_value=asset)
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _patch(asset, body: dict):
    user = SimpleNamespace(tenant_id=asset.tenant_id)
    return asyncio.run(ep.update_asset(asset.id, ep.AssetUpdate(**body), _db(asset), user))


def test_a_patch_that_sends_only_a_name_leaves_everything_else_as_it_was():
    asset = _asset(uuid.uuid4())
    _patch(asset, {"name": "FS-02"})
    assert asset.name == "FS-02"
    assert (asset.asset_type, asset.criticality, asset.asset_metadata) == ("server", "high", {"rack": "A2"})
    assert (asset.fqdn, asset.ip_addresses, asset.tags, asset.owner_email) == (
        "fs01.acme.test",
        ["10.0.0.5"],
        ["file-server"],
        "it@acme.test",
    )


def test_a_field_sent_as_null_is_cleared_when_the_column_allows_it_and_ignored_when_it_does_not():
    asset = _asset(uuid.uuid4())
    _patch(asset, {"fqdn": None, "owner_email": None, "name": None, "criticality": None, "metadata": None})
    assert (asset.fqdn, asset.owner_email) == (None, None)
    assert (asset.name, asset.criticality, asset.asset_metadata) == (
        "FS-01",
        "high",
        {"rack": "A2"},
    ), "a null name, criticality or metadata is not a change"


def test_an_empty_patch_changes_nothing():
    asset = _asset(uuid.uuid4())
    before = dict(vars(asset))
    _patch(asset, {})
    assert vars(asset) == before


def test_another_tenants_asset_is_a_404_and_nothing_is_written():
    asset = _asset(uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ep.update_asset(asset.id, ep.AssetUpdate(name="x"), _db(asset), SimpleNamespace(tenant_id=uuid.uuid4())))
    assert exc.value.status_code == 404 and asset.name == "FS-01"


class TestCreateAssetRefusesBadValues:
    def test_criticality_is_one_of_four(self):
        for good in ("low", "medium", "high", "critical"):
            assert ep.AssetCreate(name="x", criticality=good).criticality == good
        for bad in ("banana", "CRITICAL", "", "very high", "informational"):
            with pytest.raises(ValidationError):
                ep.AssetCreate(name="x", criticality=bad)

    def test_a_string_longer_than_its_column_is_refused(self):
        for field, limit in (
            ("name", 512),
            ("fqdn", 512),
            ("asset_type", 50),
            ("cloud_provider", 50),
            ("cloud_region", 100),
            ("cloud_account", 255),
            ("os", 100),
            ("os_version", 100),
            ("owner_email", 255),
        ):
            ep.AssetCreate(**{"name": "x", field: "a" * limit})
            with pytest.raises(ValidationError):
                ep.AssetCreate(**{"name": "x", field: "a" * (limit + 1)})

    def test_a_name_is_required_and_not_empty(self):
        for bad in ("", None):
            with pytest.raises(ValidationError):
                ep.AssetCreate(name=bad)

    def test_lists_and_metadata_are_bounded(self):
        with pytest.raises(ValidationError):
            ep.AssetCreate(name="x", tags=["t"] * 51)
        with pytest.raises(ValidationError):
            ep.AssetCreate(name="x", tags=["t" * 65])
        with pytest.raises(ValidationError):
            ep.AssetCreate(name="x", ip_addresses=["1.1.1.1"] * 65)
        with pytest.raises(ValidationError):
            ep.AssetCreate(name="x", metadata={"blob": "z" * 20_000})
        assert ep.AssetCreate(name="x", metadata={"k": "v"}).metadata == {"k": "v"}

    def test_the_same_limits_apply_to_a_patch(self):
        with pytest.raises(ValidationError):
            ep.AssetUpdate(criticality="banana")
        with pytest.raises(ValidationError):
            ep.AssetUpdate(name="a" * 513)
        with pytest.raises(ValidationError):
            ep.AssetUpdate(metadata={"blob": "z" * 20_000})


class TestVulnerabilityRequests:
    def _ok(self, **over):
        return ep.VulnerabilityCreate(**{"asset_id": uuid.uuid4(), "title": "OpenSSL", "source": "scanner", **over})

    def test_severity_is_one_of_five_and_scores_are_in_range(self):
        for good in ("info", "low", "medium", "high", "critical"):
            assert self._ok(severity=good).severity == good
        for bad in ("banana", "Critical", "urgent"):
            with pytest.raises(ValidationError):
                self._ok(severity=bad)
        for field, bad in (("cvss_score", 10.1), ("cvss_score", -1), ("epss_score", 1.5), ("epss_score", -0.1)):
            with pytest.raises(ValidationError):
                self._ok(**{field: bad})
        assert self._ok(cvss_score=10, epss_score=1).cvss_score == 10

    def test_strings_are_bounded(self):
        with pytest.raises(ValidationError):
            self._ok(title="a" * 513)
        with pytest.raises(ValidationError):
            self._ok(cve_id="C" * 51)
        with pytest.raises(ValidationError):
            self._ok(description="d" * 20_001)
        with pytest.raises(ValidationError):
            self._ok(source="")


def test_what_the_api_returns_still_reads_an_older_row_with_a_value_the_create_model_would_refuse():
    out = ep.AssetOut.model_validate(_asset(uuid.uuid4(), criticality="informational", name="n" * 600), from_attributes=True)
    assert out.criticality == "informational" and len(out.name) == 600
    assert out.metadata == {"rack": "A2"}

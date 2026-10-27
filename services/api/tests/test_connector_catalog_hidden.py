"""The Add connector picker leaves out the connectors this deployment does not offer, and keeps the one that carries CORE's tools."""

import asyncio

from app.api.v1.endpoints import connectors as ep


def _catalog(*ids: str) -> list[dict]:
    return [{"connector_id": i, "display_name": i} for i in ids]


def _listed(monkeypatch, *ids: str) -> list[str]:
    async def fake() -> list[dict]:
        return _catalog(*ids)

    monkeypatch.setattr(ep, "_fetch_catalog", fake)
    out = asyncio.run(ep.list_catalog(current_user=None))  # the permission check is a dependency, not the function's own
    return [c["connector_id"] for c in out["connectors"]]


def test_hidden_connectors_are_not_listed_and_the_rest_are(monkeypatch):
    shown = _listed(monkeypatch, "crowdstrike", "splunk", "okta", "github", "jira", "core_feed", "tailscale", "m365_audit")
    assert shown == ["core_feed", "tailscale", "m365_audit"]


def test_the_core_feed_connector_is_never_hidden():
    assert "core_feed" not in ep.HIDDEN_CATALOG_IDS


def test_a_hidden_connector_can_still_be_validated_so_an_existing_instance_keeps_working(monkeypatch):
    async def fake() -> list[dict]:
        return _catalog("splunk", "core_feed")

    monkeypatch.setattr(ep, "_fetch_catalog", fake)
    assert asyncio.run(ep._validate_connector_type("splunk"))["connector_id"] == "splunk"

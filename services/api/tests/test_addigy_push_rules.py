"""Pushing Huntress through Addigy: which Macs are picked (pure rule), and the Addigy device id read from the stored page address."""

import uuid
from datetime import UTC, datetime

from app.api.v1.endpoints.devices import DeviceOut, DeviceSourceOut
from app.services.tool_deploy_rules import addigy_agent_id, pick_addigy_devices

AGENT = "aaaaaaaa-1111-2222-3333-444444444444"


def device(name, os_name, *vendors, url=f"https://app.addigy.com/devices/{AGENT}"):
    now = datetime.now(UTC)
    return DeviceOut(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        hostname=name,
        os=os_name,
        last_seen=now,
        first_seen=now,
        sources=[DeviceSourceOut(vendor=v, name=name, last_seen=now, details={"url": url} if v == "addigy" else {}) for v in vendors],
    )


def test_the_agent_id_comes_from_the_addigy_page_address_and_nothing_else_counts():
    assert addigy_agent_id(device("m", "macOS 14", "addigy")) == AGENT
    assert addigy_agent_id(device("m", "macOS 14", "addigy", url="https://evil.example/devices/x")) is None
    assert addigy_agent_id(device("m", "macOS 14", "ninjaone")) is None


def test_only_addigy_only_macs_in_a_client_that_uses_huntress_are_picked():
    has = device("HAS", "macOS 14", "addigy", "huntress")
    gap = device("GAP", "macOS 14", "addigy")
    also_ninja = device("NINJA-TOO", "macOS 14", "addigy", "ninjaone")
    windows = device("WIN", "Windows 11", "ninjaone")
    no_url = device("NOURL", "macOS 14", "addigy", url="")
    picked = pick_addigy_devices([has, gap, also_ninja, windows, no_url], "huntress")
    assert [(d.hostname, a) for d, a in picked] == [("GAP", AGENT)]


def test_nothing_is_picked_for_a_client_that_has_no_huntress_anywhere_or_for_another_tool():
    assert pick_addigy_devices([device("GAP", "macOS 14", "addigy")], "huntress") == []
    assert (
        pick_addigy_devices([device("HAS", "macOS 14", "addigy", "fieldeffect"), device("GAP", "macOS 14", "addigy")], "fieldeffect") == []
    )

"""One client's environment page: devices by kind, tool coverage and the cabling Auvik sent with each network device."""

import uuid
from datetime import UTC, datetime

from app.api.v1.endpoints.client_environment import MAX_LINKS, build_environment
from app.api.v1.endpoints.devices import DeviceOut, DeviceSourceOut

CLIENT = uuid.uuid4()


def device(name, os_name, *sources, hidden=False):
    now = datetime.now(UTC)
    return DeviceOut(
        id=uuid.uuid4(),
        tenant_id=CLIENT,
        hostname=name,
        os=os_name,
        last_seen=now,
        first_seen=now,
        hidden_since=now if hidden else None,
        sources=[DeviceSourceOut(vendor=v, name=name, last_seen=now, details=d) for v, d in sources],
    )


FIREWALL = ("auvik", {"device_type": "firewall", "connected_to": [{"id": "s", "name": "core-switch", "port": "LAN", "remote_port": "Gi1/0/1", "speed": "1 Gbps"}]})


def test_counts_kinds_tools_and_gaps_and_lists_network_gear_before_computers():
    env = build_environment(
        CLIENT,
        "Acme",
        [
            device("pc-1", "Windows 11", ("ninjaone", {"node_class": "WINDOWS_WORKSTATION"}), ("huntress", {})),
            device("pc-2", "Windows 11", ("ninjaone", {"node_class": "WINDOWS_WORKSTATION"})),
            device("fw", None, FIREWALL),
        ],
    )
    assert env.counts == {"computer": 2, "network": 1, "camera": 0, "other": 0}
    assert [d.hostname for d in env.devices] == ["fw", "pc-1", "pc-2"]
    assert env.tools["ninjaone"] == 2 and env.tools["huntress"] == 1 and env.tools["auvik"] == 1
    assert env.gaps["huntress"] == 1, "only pc-2 lacks Huntress; the firewall is never a gap"
    assert env.devices[2].missing and "huntress" in env.devices[2].missing
    assert env.devices[0].role == "firewall"


def test_cabling_comes_from_auvik_and_a_client_without_it_says_so():
    env = build_environment(CLIENT, "Acme", [device("fw", None, FIREWALL)])
    assert env.has_auvik and env.has_links
    assert env.devices[0].links[0].name == "core-switch" and env.devices[0].links[0].port == "LAN"
    plain = build_environment(CLIENT, "Acme", [device("pc", "Windows 11", ("ninjaone", {}))])
    assert not plain.has_auvik and not plain.has_links


def test_hidden_devices_malformed_links_and_too_many_links_are_handled():
    bad = ("auvik", {"device_type": "switch", "connected_to": ["x", {"name": 5}, {"name": ""}, *({"name": f"n{i}"} for i in range(40))]})
    env = build_environment(CLIENT, "Acme", [device("sw", None, bad), device("gone", "Windows 11", ("ninjaone", {}), hidden=True)])
    assert [d.hostname for d in env.devices] == ["sw"] and env.counts["computer"] == 0
    assert len(env.devices[0].links) == MAX_LINKS

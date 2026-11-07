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


# ---- push through Addigy ----------------------------------------------------------------------------------------------------------------------------------

import asyncio  # noqa: E402
import contextlib  # noqa: E402
from types import SimpleNamespace as NS  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402
from app.api.v1.endpoints import client_environment as ep  # noqa: E402
from fastapi import HTTPException  # noqa: E402

AGENT = "aaaaaaaa-1111-2222-3333-444444444444"
ADDIGY = ("addigy", {"url": f"https://app.addigy.com/devices/{AGENT}"})


def test_only_an_addigy_only_mac_missing_huntress_can_be_pushed():
    mac = device("mac", "macOS 14", ADDIGY)
    both = device("both", "macOS 14", ADDIGY, ("ninjaone", {}))
    win = device("win", "Windows 11", ("ninjaone", {}))
    has = device("has", "macOS 14", ADDIGY, ("huntress", {}))
    env = build_environment(CLIENT, "Acme", [mac, both, win, has])
    by = {d.hostname: d.pushable for d in env.devices}
    assert by == {"mac": ["huntress"], "both": [], "win": [], "has": []}


class Rows:
    def __init__(self, first=None):
        self._first = first

    def first(self):
        return self._first


class FakeDB:
    def __init__(self, waiting=None):
        self.waiting, self.added, self.commits = waiting, [], 0

    async def get(self, *_):
        return NS(settings={})

    async def execute(self, _stmt):
        return Rows(self.waiting)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


@pytest.fixture
def wired(monkeypatch):
    audits = []

    async def fake_audit(**kw):
        audits.append(kw)

    mac = device("mac", "macOS 14", ADDIGY)
    win = device("win", "Windows 11", ("ninjaone", {}))
    monkeypatch.setattr(ep, "emit_audit", fake_audit)
    monkeypatch.setattr(ep, "_scope", AsyncMock(return_value=([CLIENT], {CLIENT: "Acme"})))
    monkeypatch.setattr(ep, "_load_cached", AsyncMock(return_value=[mac, win]))
    monkeypatch.setattr(ep, "_acting", lambda *a, **k: contextlib.nullcontext())
    return NS(audits=audits, mac=mac, win=win)


def push(w, db, device_id, tool="huntress"):
    user = NS(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    return asyncio.run(ep.push_tool(CLIENT, ep.PushIn(device_id=device_id, tool=tool), MagicMock(), user, db))


def test_a_push_queues_one_addigy_request_with_the_agent_id_and_audits(wired):
    db = FakeDB()
    out = push(wired, db, wired.mac.id)
    (a,) = db.added
    assert out.queued and a.action == "addigy_push" and a.vendor == "core" and a.status == "pending"
    assert a.params == {"tool": "huntress", "agent_id": AGENT, "device": "mac"}
    assert db.commits == 1 and wired.audits[0]["action"] == "addigy_push:requested"


def test_a_push_is_refused_for_a_machine_that_cannot_be_pushed_an_unknown_one_a_waiting_one_and_another_tool(wired):
    for device_id, db, code in ((wired.win.id, FakeDB(), 409), (uuid.uuid4(), FakeDB(), 404), (wired.mac.id, FakeDB(waiting=(1,)), 409)):
        with pytest.raises(HTTPException) as e:
            push(wired, db, device_id)
        assert e.value.status_code == code and db.added == [] and db.commits == 0
    with pytest.raises(ValueError):
        ep.PushIn(device_id=uuid.uuid4(), tool="fieldeffect")

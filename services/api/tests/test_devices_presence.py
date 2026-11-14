"""The Devices page's online / offline / all choice: it follows what the tools say right now, and a device no tool gives a state for is in neither list."""

import uuid
from datetime import UTC, datetime

from app.api.v1.endpoints.devices import DeviceOut, filter_devices


def device(name, online):
    now = datetime.now(UTC)
    return DeviceOut(id=uuid.uuid4(), tenant_id=uuid.uuid4(), hostname=name, last_seen=now, first_seen=now, online=online)


def names(rows):
    return sorted(d.hostname for d in rows)


ALL = [device("up-1", True), device("down-1", False), device("unknown-1", None), device("up-2", True)]


def test_online_lists_only_the_machines_the_tools_say_are_online():
    assert names(filter_devices(ALL, presence="online")) == ["up-1", "up-2"]


def test_offline_lists_only_the_machines_the_tools_say_are_offline_not_the_unknown_ones():
    assert names(filter_devices(ALL, presence="offline")) == ["down-1"]


def test_all_is_everything_and_is_the_default():
    assert names(filter_devices(ALL, presence="all")) == ["down-1", "unknown-1", "up-1", "up-2"]
    assert names(filter_devices(ALL)) == ["down-1", "unknown-1", "up-1", "up-2"]


def test_the_choice_combines_with_the_other_filters():
    assert names(filter_devices(ALL, presence="online", search="up-2")) == ["up-2"]
    assert names(filter_devices(ALL, presence="offline", search="up")) == []

"""A device's BitLocker state reaches the Devices page: a field on each device and a filter."""

import uuid
from datetime import UTC, datetime

from app.api.v1.endpoints.devices import DeviceOut, DeviceSourceOut, filter_devices


def device(host, *sources, os_name="Windows 11 Pro"):
    now = datetime.now(UTC)
    return DeviceOut(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        hostname=host,
        os=os_name,
        last_seen=now,
        first_seen=now,
        sources=[DeviceSourceOut(vendor=v, name=host, last_seen=now, details=d) for v, d in sources],
    )


def test_the_device_carries_its_encryption_state_or_none():
    assert device("a", ("ninjaone", {"bitlocker_encrypted": True})).encrypted is True
    assert device("b", ("ninjaone", {"bitlocker_encrypted": True}), ("liongard", {"bitlocker_encrypted": False})).encrypted is False
    assert device("c", ("ninjaone", {})).encrypted is None


def test_the_filter_shows_the_workstations_that_are_not_encrypted_or_that_are():
    rows = [
        device("enc", ("ninjaone", {"bitlocker_encrypted": True})),
        device("plain", ("ninjaone", {"bitlocker_encrypted": False})),
        device("unknown", ("ninjaone", {})),
        device("both-disagree", ("ninjaone", {"bitlocker_encrypted": True}), ("liongard", {"bitlocker_encrypted": False})),
    ]
    assert [d.hostname for d in filter_devices(rows, encryption="not_encrypted")] == ["both-disagree", "plain"]
    assert [d.hostname for d in filter_devices(rows, encryption="encrypted")] == ["enc"]
    assert len(filter_devices(rows)) == 4, "without the filter everything is shown, including machines with no reading"

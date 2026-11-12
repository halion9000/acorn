"""What Addigy says about a device's MDM reaches the Devices page: whether MDM is on, how the device was enrolled, and a filter for each problem."""

import uuid
from datetime import UTC, datetime

from app.api.v1.endpoints.devices import DeviceOut, DeviceSourceOut, attention_of, filter_devices, mdm_counts


def device(host, *sources):
    now = datetime.now(UTC)
    return DeviceOut(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        hostname=host,
        os="macOS",
        last_seen=now,
        first_seen=now,
        sources=[DeviceSourceOut(vendor=v, name=host, last_seen=now, details=d) for v, d in sources],
    )


def rows():
    return [
        device("ade-ok", ("addigy", {"mdm_enabled": True, "enrollment": "ADE"})),
        device("manual-ok", ("addigy", {"mdm_enabled": True, "enrollment": "Manual"}), ("huntress", {})),
        device("manual-off", ("addigy", {"mdm_enabled": False, "enrollment": "Manual", "needs_attention": ["MDM is disabled in Addigy"]})),
        device("iphone", ("addigy", {"mdm_enabled": True})),
        device("windows-pc", ("ninjaone", {"mdm_enabled": False, "enrollment": "Manual"})),
    ]


def test_the_device_carries_its_mdm_state_and_enrollment_only_from_addigy_and_none_when_addigy_does_not_say():
    by = {d.hostname: d for d in rows()}
    assert (by["ade-ok"].mdm_enabled, by["ade-ok"].enrollment) == (True, "ADE")
    assert (by["manual-off"].mdm_enabled, by["manual-off"].enrollment) == (False, "Manual")
    assert (by["iphone"].mdm_enabled, by["iphone"].enrollment) == (
        True,
        None,
    ), "a device that does not say how it was enrolled is not called manual"
    assert (by["windows-pc"].mdm_enabled, by["windows-pc"].enrollment) == (
        None,
        None,
    ), "another tool's fields of the same name are not Addigy's word"
    assert device("odd", ("addigy", {"mdm_enabled": "no", "enrollment": "Something else"})).enrollment is None


def test_the_filters_show_the_devices_with_mdm_disabled_and_the_ones_not_enrolled_through_ade():
    assert [d.hostname for d in filter_devices(rows(), mdm="disabled")] == ["manual-off"]
    assert [d.hostname for d in filter_devices(rows(), mdm="not_ade")] == ["manual-off", "manual-ok"]
    assert len(filter_devices(rows())) == 5, "without the filter everything is shown"


def test_the_counts_for_the_tiles_agree_with_the_filters_and_say_how_many_devices_addigy_has_a_reading_for():
    assert mdm_counts(rows()) == {"mdm_disabled": 1, "mdm_known": 4, "not_ade": 2, "enrollment_known": 3}
    assert mdm_counts([]) == {"mdm_disabled": 0, "mdm_known": 0, "not_ade": 0, "enrollment_known": 0}


def test_mdm_disabled_needs_attention_and_a_manual_enrollment_alone_does_not():
    by = {d.hostname: d for d in rows()}
    assert attention_of(by["manual-off"]) == ["MDM is disabled in Addigy"]
    assert attention_of(by["manual-ok"]) == [], "a manual enrollment is shown and can be filtered, but raises nothing"

"""Device lifecycle: age bands from the day a machine was first seen, and whether its operating system is still patched."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from app.services import device_lifecycle as lc

NOW = datetime(2026, 11, 21, tzinfo=UTC)


def dev(i, first_days, os="Windows 11 Pro", version=None, host=None, client="Acme"):
    return NS(id=f"id{i}", client_name=client, hostname=host or f"PC-{i}", os=os, os_version=version, manufacturer="Dell", model="Latitude", serial_number=f"S{i}", first_seen=NOW - timedelta(days=first_days))


def test_age_is_banded_from_the_day_the_machine_was_first_seen():
    assert [lc.age_band(NOW - timedelta(days=d), NOW) for d in (10, 364, 366, 1096, 1500, 1827, 4000)] == ["under_1", "under_1", "1_to_3", "3_to_5", "3_to_5", "over_5", "over_5"]


def test_windows_versions_that_ended_are_ended_and_long_term_editions_and_windows_11_are_not():
    cases = {
        "Windows 7 Professional": "ended",
        "Microsoft Windows 10 Pro": "ended",
        "Windows 10 Enterprise LTSC 2021": "supported",
        "Windows 11 Pro": "supported",
        "Windows Server 2012 R2": "ended",
        "Windows Server 2022 Standard": "supported",
        "Ubuntu 22.04": "unknown",
        "": "unknown",
    }
    assert {k: lc.os_support(k) for k in cases} == cases


def test_macos_13_and_older_ended_and_newer_is_supported_and_the_version_can_come_separately():
    assert lc.os_support("macOS 12.7") == "ended" and lc.os_support("Mac OS X 10.15.7") == "ended"
    assert lc.os_support("macOS 14.5") == "supported" and lc.os_support("macOS 26.1") == "supported"
    assert lc.os_support("macOS", "13.6") == "ended" and lc.os_support("macOS", "15.0") == "supported"
    assert lc.os_support(None, None) == "unknown"


def test_a_row_carries_the_band_the_support_and_whether_it_is_worth_a_review():
    old_win10 = lc.lifecycle_row(dev(1, 200, os="Windows 10 Pro"), NOW)
    assert (old_win10["os_support"], old_win10["band"], old_win10["review"]) == ("ended", "under_1", True)
    ancient = lc.lifecycle_row(dev(2, 2200), NOW)
    assert (ancient["os_support"], ancient["band"], ancient["review"], ancient["age_days"]) == ("supported", "over_5", True, 2200)
    fine = lc.lifecycle_row(dev(3, 100), NOW)
    assert fine["review"] is False and fine["first_seen"].startswith("2026-08")


def test_the_summary_counts_and_the_order_puts_ended_systems_first_then_the_oldest():
    rows = [lc.lifecycle_row(d, NOW) for d in (dev(1, 100), dev(2, 2000), dev(3, 500, os="Windows 10 Pro"), dev(4, 900, os=None), dev(5, 3000, os="Windows 7"))]
    s = lc.summarize(rows)
    assert s["computers"] == 5 and s["os_ended"] == 2 and s["os_unknown"] == 1 and s["review"] == 3
    assert s["bands"] == {"under_1": 1, "1_to_3": 2, "3_to_5": 0, "over_5": 2}
    assert [r["hostname"] for r in lc.order(rows)] == ["PC-5", "PC-3", "PC-2", "PC-4", "PC-1"]

"""The indexed ``ip_brand_pairs`` finds exactly the pairs, in exactly the order, that the full scan it replaced found.

The old function (it compared every made-up-name device with every device, recomputing names and addresses each time: 1.8 million address reads for 187 clients) is copied here unchanged as the
reference, and both are run on hundreds of random clients built to force overlaps: shared addresses, made-up names beside real ones, different and missing makers and serials, hardware units
beside agents, addresses that are not usable, pairs already taken and pairs a person dismissed.
"""

import random
import uuid
from types import SimpleNamespace as NS
from typing import Any

import pytest
from app.services.device_identity import (
    could_be_same_machine,
    hostname_key,
    ip_brand_pairs,
    is_placeholder_name,
    same_brand,
    usable_ips,
)


def naive_ip_brand_pairs(
    devices: list[Any], tools: dict[Any, set[str]], dismissed: set[tuple[Any, Any]], taken: set[tuple[Any, Any]]
) -> list[tuple[Any, Any]]:
    out: list[tuple[Any, Any]] = []
    seen = set(taken)
    for a in devices:
        if not is_placeholder_name(hostname_key(a.hostname)):
            continue
        ips = usable_ips(a.ip_addresses)
        if not ips:
            continue
        for b in devices:
            if b.id == a.id or (is_placeholder_name(hostname_key(b.hostname)) and str(b.id) < str(a.id)):
                continue
            if not (ips & usable_ips(b.ip_addresses)) or not same_brand(a.manufacturer, b.manufacturer):
                continue
            if a.serial_number and b.serial_number:
                continue
            if not could_be_same_machine(tools.get(a.id, set()), tools.get(b.id, set())):
                continue
            lo, hi = sorted((a.id, b.id), key=str)
            if (lo, hi) in dismissed or (lo, hi) in seen:
                continue
            seen.add((lo, hi))
            out.append((lo, hi))
    return out


ADDRESSES = ["10.0.0.%d" % i for i in range(1, 9)] + ["192.168.1.5", "0.0.0.0", "127.0.0.1", "169.254.1.1", "not-an-ip", "", "10.0.0.1 "]
MAKERS = [None, "", "Dell", "Dell Inc.", "ubiquiti", "Ubiquiti Inc.", "HP", "Apple"]
TOOLSETS = [{"auvik"}, {"ninjaone"}, {"huntress", "ninjaone"}, {"unifi"}, {"meraki"}, {"auvik", "unifi"}, {"screenconnect"}, set()]


def random_client(rng: random.Random) -> tuple[list[Any], dict[Any, set[str]], set[tuple[Any, Any]], set[tuple[Any, Any]]]:
    devices = []
    for i in range(rng.randint(0, 40)):
        placeholder = rng.random() < 0.4
        ips = [rng.choice(ADDRESSES) for _ in range(rng.randint(0, 3))]
        host = (
            f"Device@{rng.choice(ADDRESSES[:8])}"
            if placeholder
            else rng.choice([f"PC-{i}", f"pc-{i}.corp.local", f"AP-{i % 3}", f"Device@{rng.choice(ADDRESSES[:8])}.x"])
        )
        devices.append(
            NS(
                id=uuid.UUID(int=rng.getrandbits(128)),
                hostname=host,
                ip_addresses=ips,
                manufacturer=rng.choice(MAKERS),
                serial_number=rng.choice([None, None, "S1", "S2"]),
            )
        )
    tools = {d.id: set(rng.choice(TOOLSETS)) for d in devices}
    ids = [d.id for d in devices]
    pairs = [tuple(sorted((rng.choice(ids), rng.choice(ids)), key=str)) for _ in range(rng.randint(0, 4))] if len(ids) > 1 else []
    dismissed = {p for p in pairs[: len(pairs) // 2] if p[0] != p[1]}
    taken = {p for p in pairs[len(pairs) // 2 :] if p[0] != p[1]}
    return devices, tools, dismissed, taken


@pytest.mark.parametrize("seed", range(40))
def test_the_indexed_version_gives_the_same_pairs_in_the_same_order_as_the_full_scan(seed):
    rng = random.Random(seed)
    found_any = 0
    for _ in range(25):
        devices, tools, dismissed, taken = random_client(rng)
        expected = naive_ip_brand_pairs(devices, tools, dismissed, taken)
        assert ip_brand_pairs(devices, tools, dismissed, taken) == expected
        found_any += bool(expected)
    assert found_any > 0, "the random clients really produced pairs, so the comparison is not empty"


def test_it_does_not_change_its_inputs_and_handles_no_devices():
    taken = {(uuid.UUID(int=1), uuid.UUID(int=2))}
    assert ip_brand_pairs([], {}, set(), taken) == []
    assert taken == {(uuid.UUID(int=1), uuid.UUID(int=2))}

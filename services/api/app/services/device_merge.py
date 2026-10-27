"""A person's decisions about "possible duplicate" devices (see ``possible_duplicates``): say two are NOT the same machine, or merge them into one.

Both are stored on the client tenant, so every person in the organization sees the same decision. The caller owns the transaction and has put ``db`` in the client's scope.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.device import Device, DeviceMergeDismissal, DeviceMergeLog, DeviceSource
from app.services.device_identity import could_be_same_machine, hostname_key, is_placeholder_name, loose_name_key, mac_key


class DeviceMergeError(ValueError):
    """The request cannot be done; the message is safe to show."""


def _ordered(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    lo, hi = sorted((a, b), key=str)
    return lo, hi


async def _both(db: Any, tenant_id: uuid.UUID, a: uuid.UUID, b: uuid.UUID) -> tuple[Device, Device]:
    if a == b:
        raise DeviceMergeError("Pick two different devices.")
    found = {
        d.id: d for d in (await db.execute(select(Device).where(Device.tenant_id == tenant_id, Device.id.in_([a, b])))).scalars().all()
    }
    if a not in found or b not in found:
        raise DeviceMergeError("Both devices must belong to the same client.")
    return found[a], found[b]


async def dismiss_pair(db: Any, tenant_id: uuid.UUID, a: uuid.UUID, b: uuid.UUID) -> None:
    """Remember that these two devices are different machines, so they are not suggested again. Saying it twice is fine."""
    await _both(db, tenant_id, a, b)
    lo, hi = _ordered(a, b)
    await db.execute(pg_insert(DeviceMergeDismissal).values(tenant_id=tenant_id, device_a=lo, device_b=hi).on_conflict_do_nothing())


UNDO_WINDOW = timedelta(days=14)
_COPIED = ("os", "os_version", "manufacturer", "model")


def snapshot_of(device: Any) -> dict[str, Any]:
    """The removed device as it was: enough to recreate it."""
    return {
        "id": str(device.id),
        "hostname": device.hostname,
        "serial_number": device.serial_number,
        "os": device.os,
        "os_version": device.os_version,
        "manufacturer": device.manufacturer,
        "model": device.model,
        "ip_addresses": list(device.ip_addresses or []),
        "first_seen": device.first_seen.isoformat() if device.first_seen else None,
        "last_seen": device.last_seen.isoformat() if device.last_seen else None,
    }


def can_undo(entry: Any, now: datetime | None = None) -> bool:
    """A merge can be undone while it is recent and has not been undone already."""
    moment = now or datetime.now(UTC)
    created = entry.created_at if entry.created_at.tzinfo else entry.created_at.replace(tzinfo=UTC)
    return entry.undone_at is None and moment - created <= UNDO_WINDOW


async def merge_devices(
    db: Any, tenant_id: uuid.UUID, keep_id: uuid.UUID, remove_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> uuid.UUID:
    """Fold ``remove_id`` into ``keep_id``: every tool that reported the removed device now reports the kept one, blanks on the kept device are filled from the removed one,
    and the removed device is deleted. Two devices with different serial numbers are different machines and are refused."""
    keep, remove = await _both(db, tenant_id, keep_id, remove_id)
    # Auvik keeps a MAC as the serial of a device with none; that is not a serial, so it neither proves two devices differ nor beats a real serial.
    real_keep = None if mac_key(keep.serial_number) else keep.serial_number
    real_remove = None if mac_key(remove.serial_number) else remove.serial_number
    if real_keep and real_remove and real_keep != real_remove:
        raise DeviceMergeError("These have different serial numbers, so they are different machines.")
    replaced_serial = keep.serial_number if (keep.serial_number and not real_keep and real_remove) else None
    if replaced_serial:
        keep.serial_number = None
        await db.flush()

    removed_snapshot = snapshot_of(remove)
    moved = (await db.execute(select(DeviceSource).where(DeviceSource.device_id == remove.id))).scalars().all()
    moved_ids = [str(s.id) for s in moved]
    for source in moved:
        source.device_id = keep.id
    filled: dict[str, Any] = {"fields": [], "ip_addresses": False, "first_seen_was": None, "carried_serial": None, "replaced_serial": replaced_serial}
    for name in _COPIED:
        if getattr(keep, name) is None and getattr(remove, name) is not None:
            setattr(keep, name, getattr(remove, name))
            filled["fields"].append(name)
    if not keep.ip_addresses and remove.ip_addresses:
        keep.ip_addresses = list(remove.ip_addresses)
        filled["ip_addresses"] = True
    if remove.first_seen < keep.first_seen:
        filled["first_seen_was"] = keep.first_seen.isoformat()
        keep.first_seen = remove.first_seen
    carried_serial = remove.serial_number if keep.serial_number is None else None
    filled["carried_serial"] = carried_serial
    await db.flush()

    # The serial is unique per client, so the removed device has to be gone before the kept one can take its serial. Its dismissals go with it (they cascade).
    await db.execute(delete(Device).where(Device.id == remove.id))
    db.expunge(remove)
    if carried_serial:
        keep.serial_number = carried_serial
    db.add(
        DeviceMergeLog(
            tenant_id=tenant_id,
            kept_device_id=keep.id,
            removed=removed_snapshot,
            moved_source_ids=moved_ids,
            filled=filled,
            created_by=actor_id,
        )
    )
    await db.flush()
    return keep.id


async def undo_merge(db: Any, tenant_id: uuid.UUID, merge_id: uuid.UUID, now: datetime | None = None) -> uuid.UUID:
    """Reverse a merge: recreate the removed device with its own id and serial, move its feed rows back, and put back what was filled in on the kept device. Returns the recreated device's id.

    Refused (with a message safe to show) when the merge is too old, was already undone, or the kept device is gone. Dismissals the removed device had are not restored.
    """
    entry = (
        await db.execute(select(DeviceMergeLog).where(DeviceMergeLog.id == merge_id, DeviceMergeLog.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if entry is None:
        raise DeviceMergeError("That merge was not found.")
    if entry.undone_at is not None:
        raise DeviceMergeError("That merge was already undone.")
    if not can_undo(entry, now):
        raise DeviceMergeError("That merge is too old to undo.")
    keep = (await db.execute(select(Device).where(Device.id == entry.kept_device_id, Device.tenant_id == tenant_id))).scalar_one_or_none()
    if keep is None:
        raise DeviceMergeError("The device it was merged into no longer exists, so this cannot be undone.")
    removed = entry.removed
    filled = entry.filled or {}
    restored_id = uuid.UUID(removed["id"])
    if (await db.execute(select(Device.id).where(Device.id == restored_id))).first() is not None:
        raise DeviceMergeError("A device with the removed device's id already exists, so this cannot be undone.")

    # The serial is unique per client: if the kept device took the removed one's serial, give it back before the removed device is recreated.
    carried = filled.get("carried_serial")
    if carried and keep.serial_number == carried:
        keep.serial_number = filled.get("replaced_serial")
        await db.flush()
    db.add(
        Device(
            id=restored_id,
            tenant_id=tenant_id,
            hostname=removed["hostname"],
            serial_number=removed.get("serial_number"),
            os=removed.get("os"),
            os_version=removed.get("os_version"),
            manufacturer=removed.get("manufacturer"),
            model=removed.get("model"),
            ip_addresses=list(removed.get("ip_addresses") or []),
            first_seen=datetime.fromisoformat(removed["first_seen"]) if removed.get("first_seen") else datetime.now(UTC),
            last_seen=datetime.fromisoformat(removed["last_seen"]) if removed.get("last_seen") else datetime.now(UTC),
        )
    )
    await db.flush()
    moved_ids = [uuid.UUID(x) for x in entry.moved_source_ids or []]
    if moved_ids:
        for source in (
            (await db.execute(select(DeviceSource).where(DeviceSource.id.in_(moved_ids), DeviceSource.device_id == keep.id)))
            .scalars()
            .all()
        ):
            source.device_id = restored_id
    for name in filled.get("fields", []):
        if getattr(keep, name) == removed.get(name):
            setattr(keep, name, None)
    if filled.get("ip_addresses") and list(keep.ip_addresses or []) == list(removed.get("ip_addresses") or []):
        keep.ip_addresses = []
    if filled.get("first_seen_was"):
        keep.first_seen = datetime.fromisoformat(filled["first_seen_was"])
    entry.undone_at = now or datetime.now(UTC)
    # A merge that was undone was judged wrong: the two are not suggested or merged automatically again.
    lo, hi = _ordered(restored_id, keep.id)
    await db.execute(pg_insert(DeviceMergeDismissal).values(tenant_id=tenant_id, device_a=lo, device_b=hi).on_conflict_do_nothing())
    await db.flush()
    return restored_id


# ---- same name, unambiguous: merged without asking ---------------------------------------------------------------------------------------------------------

_OS_KINDS = (
    ("windows", "windows"),
    ("mac", "mac"),
    ("darwin", "mac"),
    ("os x", "mac"),
    ("ios", "ios"),
    ("ipad", "ios"),
    ("linux", "linux"),
    ("ubuntu", "linux"),
    ("debian", "linux"),
)


def os_kind(os_name: str | None) -> str | None:
    """windows / mac / ios / linux from the OS text a tool reports, or None when it says nothing useful."""
    text = (os_name or "").lower()
    for needle, kind in _OS_KINDS:
        if needle in text:
            return kind
    return None


# "Katrinas-MacBook-Pro" names a person's Mac: too common to say which CLIENT a machine belongs to (so client matching ignores it), but inside one client it points at one machine. A bare factory
# name ("MacBook-Pro", "Mac") has no person in front of it and is still treated as stock.
_PERSONAL_APPLE = re.compile(r"^[a-z]{2,}s?[-_ ](macbook|imac|mac[-_ ]?mini|mac[-_ ]?studio)([-_ ]?(pro|air|mini|studio))?([-_ ]?\d+)?$")


def usable_for_merge(key: str) -> bool:
    """True when a machine name can be trusted to mean one machine within a client."""
    from app.services.client_matching import is_generic_hostname

    return not is_generic_hostname(key) or bool(_PERSONAL_APPLE.match(key.split(".")[0]))


# A name held by more devices than this is left for a person: it is more likely a stock or reused name than one machine seen by several tools.
MAX_AUTO_MERGE_GROUP = 6


# Tools that keep one record per agent install, so a machine that was re-imaged or reinstalled shows up there twice under one name (old records stay "active" with a last sync from years ago). Two records of
# one of these tools under one name in one client are one machine; every other tool's two records are left for a person.
DUPLICATING_TOOLS = frozenset({"dnsfilter"})

LEGACY_SCREENCONNECT = "screenconnect-legacy"


def _tool_of(vendor: str, external_id: str) -> str:
    """The tool a source belongs to, with the old ScreenConnect feed kept apart: it keyed each machine as ``Company::Name`` before the real session id was available, so that record
    and a session-id record of the same machine are one machine seen twice, not two machines in one tool."""
    return LEGACY_SCREENCONNECT if vendor == "screenconnect" and "::" in external_id else vendor


async def drop_legacy_screenconnect(db: Any, tenant_id: uuid.UUID) -> int:
    """Remove the old ``Company::Name`` ScreenConnect record from any device that also has the real, session-id record of the same machine. Returns how many were removed."""
    real = DeviceSource.__table__.alias("real")
    result = await db.execute(
        delete(DeviceSource).where(
            DeviceSource.tenant_id == tenant_id,
            DeviceSource.vendor == "screenconnect",
            DeviceSource.external_id.like("%::%"),
            select(real.c.id)
            .where(real.c.device_id == DeviceSource.device_id, real.c.vendor == "screenconnect", ~real.c.external_id.like("%::%"))
            .exists(),
        )
    )
    return result.rowcount or 0


# The tools that put a MAC address in a source's details (UniFi: ``mac``, Huntress: ``macs``).
MAC_TOOLS = ("unifi", "huntress", "auvik", "ninjaone")


def macs_of(details: Any) -> set[str]:
    """The MAC addresses a tool reported for a device, each reduced to twelve hex digits: ``mac`` (UniFi), ``macs`` (Huntress and Auvik, a list; Auvik's come from the device's interfaces), and NinjaOne's
    ``facts.macAddresses`` (one MAC, or several separated by commas, semicolons or spaces)."""
    det = details if isinstance(details, dict) else {}
    raw: list[Any] = [det.get("mac"), *(det.get("macs") if isinstance(det.get("macs"), list) else [])]
    facts = det.get("facts") if isinstance(det.get("facts"), dict) else {}
    ninja = facts.get("macAddresses")
    if isinstance(ninja, str):
        raw.extend(ninja.replace(";", ",").replace(" ", ",").split(","))
    elif isinstance(ninja, list):
        raw.extend(ninja)
    return {m for m in (mac_key(x) for x in raw) if m}


async def auto_merge_by_mac(db: Any, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None) -> int:
    """Merge two devices of one client that hold the same MAC address. Returns how many merges were made.

    A MAC is one network card. Tools report it differently: UniFi gives a unit's MAC, Huntress a machine's cards, and Auvik keeps a device's MAC as its serial when it has none. Two devices that hold
    the same MAC are one machine seen twice. A pair merges only when exactly two devices hold the MAC (a MAC shared more widely, such as a virtual adapter, is left alone), no tool reports both,
    a hardware unit is not paired with a machine an agent runs on, their serials do not differ, and nobody said they are different. Each merge is the ordinary logged one."""
    devices = {d.id: d for d in (await db.execute(select(Device).where(Device.tenant_id == tenant_id))).scalars().all()}
    holders: dict[str, set[uuid.UUID]] = {}
    for d in devices.values():
        mac = mac_key(d.serial_number)
        if mac:
            holders.setdefault(mac, set()).add(d.id)
    vendors: dict[uuid.UUID, set[str]] = {}
    for device_id, vendor, external_id in (await db.execute(select(DeviceSource.device_id, DeviceSource.vendor, DeviceSource.external_id).where(DeviceSource.tenant_id == tenant_id))).all():
        vendors.setdefault(device_id, set()).add(_tool_of(vendor, external_id))
    # Only the tools that report MACs have their details read (a tool's details can be large), and only the two keys that hold them.
    for device_id, mac, macs, ninja in (
        await db.execute(
            select(DeviceSource.device_id, DeviceSource.details["mac"], DeviceSource.details["macs"], DeviceSource.details["facts"]["macAddresses"]).where(
                DeviceSource.tenant_id == tenant_id, DeviceSource.vendor.in_(MAC_TOOLS)
            )
        )
    ).all():
        for found in macs_of({"mac": mac, "macs": macs, "facts": {"macAddresses": ninja}}):
            holders.setdefault(found, set()).add(device_id)
    pairs = [sorted(ids, key=str) for ids in holders.values() if len(ids) == 2]
    if not pairs:
        return 0
    dismissed = {(x.device_a, x.device_b) for x in (await db.execute(select(DeviceMergeDismissal).where(DeviceMergeDismissal.tenant_id == tenant_id))).scalars().all()}
    gone: set[uuid.UUID] = set()
    merged = 0
    for first, second in pairs:
        if first in gone or second in gone or first not in devices or second not in devices:
            continue
        a, b = devices[first], devices[second]
        va, vb = vendors.get(first, set()), vendors.get(second, set())
        if (va & vb) - DUPLICATING_TOOLS or not could_be_same_machine(va, vb):
            continue
        # Auvik keeps a MAC as the serial of a device with none: that is not a serial, so only real serials can show two machines apart.
        real_a = None if mac_key(a.serial_number) else a.serial_number
        real_b = None if mac_key(b.serial_number) else b.serial_number
        if real_a and real_b and real_a != real_b:
            continue
        if _ordered(first, second) in dismissed:
            continue
        # The device with a real serial is kept, so the machine does not end up identified by a MAC.
        keep, remove = sorted((a, b), key=lambda d: (1 if mac_key(d.serial_number) else 0, -len(vendors.get(d.id, set())), d.first_seen, str(d.id)))
        await merge_devices(db, tenant_id, keep.id, remove.id, actor_id)
        gone.add(remove.id)
        vendors[keep.id] = va | vb
        merged += 1
    return merged



# What Auvik calls a computer (see ``device_kind`` in the devices endpoint): the types a person's workstation or a server can have.
_AUVIK_COMPUTER_TYPES = frozenset({"workstation", "server", "hypervisor", "virtualmachine", "thinclient", "tablet", "handheld"})
_NETWORK_TOOLS = frozenset({"auvik", "unifi", "meraki"})
IP_MATCH_WINDOW = timedelta(days=3)


async def auto_merge_by_ip(db: Any, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None) -> int:
    """Merge an Auvik-discovered computer into the machine an agent runs on when the two share a private address. Returns how many merges were made.

    Auvik lists every workstation and server it finds on the network, under whatever name DHCP or NetBIOS gave it, with no serial. Those show up as machines no agent covers although the agent's own record is
    the same machine. A pair merges only when ALL hold: the address is held by exactly one such Auvik computer and exactly one device an agent runs on in the client; both were seen within
    ``IP_MATCH_WINDOW`` of each other (an address is reused over time); no real serials differ; nobody said they are different. Each merge is the ordinary logged one."""
    from app.services.device_identity import AGENT_TOOLS, usable_ips

    vendors: dict[uuid.UUID, set[str]] = {}
    for device_id, vendor, external_id in (await db.execute(select(DeviceSource.device_id, DeviceSource.vendor, DeviceSource.external_id).where(DeviceSource.tenant_id == tenant_id))).all():
        vendors.setdefault(device_id, set()).add(_tool_of(vendor, external_id))
    # Only Auvik's details are read, and only its device type.
    auvik_computer: set[uuid.UUID] = set()
    for device_id, device_type in (await db.execute(select(DeviceSource.device_id, DeviceSource.details["device_type"]).where(DeviceSource.tenant_id == tenant_id, DeviceSource.vendor == "auvik"))).all():
        if str(device_type or "").strip().lower() in _AUVIK_COMPUTER_TYPES:
            auvik_computer.add(device_id)
    discovered = {d for d in auvik_computer if vendors[d] <= _NETWORK_TOOLS}
    if not discovered:
        return 0
    devices = {d.id: d for d in (await db.execute(select(Device).where(Device.tenant_id == tenant_id))).scalars().all()}
    agent_machines = {i for i, v in vendors.items() if v & AGENT_TOOLS and i in devices}
    holders_found: dict[str, set[uuid.UUID]] = {}
    holders_agent: dict[str, set[uuid.UUID]] = {}
    for i in discovered:
        for ip in usable_ips(devices[i].ip_addresses) if i in devices else ():
            holders_found.setdefault(ip, set()).add(i)
    for i in agent_machines:
        for ip in usable_ips(devices[i].ip_addresses):
            holders_agent.setdefault(ip, set()).add(i)
    dismissed = {(x.device_a, x.device_b) for x in (await db.execute(select(DeviceMergeDismissal).where(DeviceMergeDismissal.tenant_id == tenant_id))).scalars().all()}
    gone: set[uuid.UUID] = set()
    merged = 0
    for ip, found in holders_found.items():
        agents = holders_agent.get(ip, set())
        if len(found) != 1 or len(agents) != 1:
            continue
        (found_id,), (agent_id,) = tuple(found), tuple(agents)
        if found_id in gone or agent_id in gone:
            continue
        found_dev, agent_dev = devices[found_id], devices[agent_id]
        if abs(found_dev.last_seen - agent_dev.last_seen) > IP_MATCH_WINDOW:
            continue
        real_found = None if mac_key(found_dev.serial_number) else found_dev.serial_number
        if real_found and agent_dev.serial_number and real_found != agent_dev.serial_number:
            continue
        if _ordered(found_id, agent_id) in dismissed or not could_be_same_machine(vendors[found_id], vendors[agent_id]):
            continue
        await merge_devices(db, tenant_id, agent_id, found_id, actor_id)
        gone.add(found_id)
        vendors[agent_id] = vendors[agent_id] | vendors[found_id]
        merged += 1
    return merged


async def auto_merge_same_name(db: Any, tenant_id: uuid.UUID, actor_id: uuid.UUID | None = None) -> int:
    """Merge, in one client, the devices that are plainly one machine seen by different tools. Returns how many merges were made.

    A name can be held by several records at once (one per tool that has not yet been matched), so each name's records are folded one by one into the one that already holds the most tools.
    A record joins only when ALL of these hold, so a wrong merge stays rare:
      * the name is not a stock name (``server``, ``MacBook-Pro``...) and no more than ``MAX_AUTO_MERGE_GROUP`` devices in the client carry it;
      * no tool reports both (two entries from the same tool are two machines that happen to share a name), except for the tools in ``DUPLICATING_TOOLS`` (one record per agent install) and that the old ScreenConnect record (keyed by company and name) and a
        ScreenConnect session record are the same tool seen before and after the feed learned real session ids;
      * they are not provably different: no two different serial numbers, and the operating systems they report do not disagree (a Windows PC and a Mac);
      * nobody said they are different machines (a pair marked "not a duplicate", or a merge that was undone).
    Each merge is the ordinary one: logged, and a person can undo it for two weeks."""
    await drop_legacy_screenconnect(db, tenant_id)
    by_mac = await auto_merge_by_mac(db, tenant_id, actor_id) + await auto_merge_by_ip(db, tenant_id, actor_id)
    devices = (await db.execute(select(Device).where(Device.tenant_id == tenant_id))).scalars().all()
    by_name: dict[str, list[Device]] = {}
    for d in devices:
        key = hostname_key(d.hostname)
        if key and usable_for_merge(key) and not is_placeholder_name(key):
            # Grouped by the name with punctuation ignored, so "Airport SP - Parking" (UniFi) and "Airport-SP-Parking" (Auvik) meet.
            by_name.setdefault(loose_name_key(d.hostname) or key, []).append(d)
    vendors: dict[uuid.UUID, set[str]] = {}
    for device_id, vendor, external_id in (
        await db.execute(select(DeviceSource.device_id, DeviceSource.vendor, DeviceSource.external_id).where(DeviceSource.tenant_id == tenant_id))
    ).all():
        vendors.setdefault(device_id, set()).add(_tool_of(vendor, external_id))

    def crowd(group: list[Device]) -> int:
        """How many records the name really has for the "stock name" limit: a machine reinstalled many times leaves many records that are only DNSFilter's, and those count as one."""
        only_duplicating = sum(1 for d in group if vendors.get(d.id) and vendors[d.id] <= DUPLICATING_TOOLS)
        return len(group) - only_duplicating + (1 if only_duplicating else 0)

    groups = [g for g in by_name.values() if len(g) >= 2 and crowd(g) <= MAX_AUTO_MERGE_GROUP]
    if not groups:
        return by_mac
    dismissed = {
        (x.device_a, x.device_b)
        for x in (await db.execute(select(DeviceMergeDismissal).where(DeviceMergeDismissal.tenant_id == tenant_id))).scalars().all()
    }
    merged = 0
    for group in groups:
        ordered = sorted(group, key=lambda d: (-len(vendors.get(d.id, set())), d.first_seen, str(d.id)))
        keep = ordered[0]
        # What the kept device holds, tracked here because each merge fills in what it was missing.
        held = set(vendors.get(keep.id, set()))
        serial = keep.serial_number
        kind = os_kind(keep.os)
        for other in ordered[1:]:
            vo = vendors.get(other.id, set())
            if not held or not vo or (held & vo) - DUPLICATING_TOOLS:
                continue
            if serial and other.serial_number:
                continue
            if not could_be_same_machine(held, vo):
                continue
            ko = os_kind(other.os)
            if kind and ko and kind != ko:
                continue
            if _ordered(keep.id, other.id) in dismissed:
                continue
            await merge_devices(db, tenant_id, keep.id, other.id, actor_id)
            await drop_legacy_screenconnect(db, tenant_id)
            merged += 1
            held |= vo
            serial = serial or other.serial_number
            kind = kind or ko
    return by_mac + merged

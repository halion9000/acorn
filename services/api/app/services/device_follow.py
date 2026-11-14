"""A security tool's record of a machine follows the machine to the client the RMM files it under.

A tool's organizations are mapped to clients one to one, and for most tools that is right. Huntress is set up differently in places: one Huntress organization holds the machines of several
NinjaOne organizations (a hotel group filed per hotel in NinjaOne, as one group in Huntress), or holds a client under another name, or is where agents installed with the default key ended
up. Its agents then landed under the client that organization is mapped to, while NinjaOne's record of the very same machine sat under another client: two half-records, and "not in Huntress"
beside a machine Huntress protects (found 2026-11-13: 29 organization pairs sharing three or more machines under different names).

The rule is narrow on purpose. A record follows only when ALL hold:
  * it comes from a tool in ``FOLLOWING_TOOLS`` (Huntress agents, ThreatMate assets and ScreenConnect sessions: each id is unique across the whole account, so a record can be told apart wherever it sits;
    ThreatMate and ScreenConnect were added 2026-11-14 after 317 of the machines flagged "not in NinjaOne" were found filed under the client their group is mapped to, e.g. the New Waterloo hotels);
  * it carries a real serial number (not empty, not a placeholder);
  * a tool in ``ANCHOR_TOOLS`` (the RMMs: they are what says which client a machine belongs to) holds a device with that same serial AND the same machine name under exactly ONE of the owner's
    clients, and that client is not the one the record was heading for;
  * the RMM still reports that device (seen within ``ANCHOR_FRESH``: a record the RMM dropped, or left behind when the machine moved, decides nothing), under its name as the RMM gives it today,
    and the client is one that is shown (a hidden client never pulls a record out of a visible one).
An RMM's own record never moves, so two tools can never chase each other. A record that followed is removed from the client it used to sit under, with its device when nothing else is on it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select

from app.db.rls_scope import cross_tenant_reads
from app.models.device import Device, DeviceSource
from app.services.device_identity import hostname_key, normalize_serial

# The tools that say which client a machine belongs to.
ANCHOR_TOOLS = frozenset({"ninjaone", "addigy"})
# The tools whose record follows the machine. Only tools whose ids for a device are unique across the whole account belong here.
FOLLOWING_TOOLS = frozenset({"huntress", "threatmate", "screenconnect"})
# How lately the RMM must have reported its record for it to say where a machine belongs. Devices are reported every hour; nothing removes a record the RMM stops sending.
ANCHOR_FRESH = timedelta(days=3)


def machine_key(hostname: str | None, serial: str | None) -> tuple[str, str] | None:
    """What makes two records plainly the same machine: the same real serial and the same machine name (pure). None when either is missing."""
    s = normalize_serial(serial)
    h = hostname_key(hostname or "")
    return (s, h) if s and h else None


def follow_targets(
    items: Iterable[tuple[int, str, str | None, str | None, uuid.UUID]], anchored: dict[tuple[str, str], set[uuid.UUID]]
) -> dict[int, uuid.UUID]:
    """Which records go to another client than the one they were heading for (pure).

    ``items`` is (position, tool, hostname, serial, client it is heading for); ``anchored`` says, per machine, the clients under which an RMM holds it. Returns {position: client to go to}."""
    out: dict[int, uuid.UUID] = {}
    for position, vendor, hostname, serial, heading in items:
        if vendor not in FOLLOWING_TOOLS:
            continue
        key = machine_key(hostname, serial)
        places = anchored.get(key, set()) if key else set()
        if len(places) == 1 and heading not in places:
            out[position] = next(iter(places))
    return out


async def anchored_machines(
    db: Any, clients: set[uuid.UUID], incoming: Iterable[tuple[str, str | None, str | None, uuid.UUID]]
) -> dict[tuple[str, str], set[uuid.UUID]]:
    """Per machine a following tool reports, the clients under which an RMM holds it: from what is stored, and from the RMM records arriving in this same report (so the first report of both
    already joins them). ``incoming`` is (tool, hostname, serial, client it is heading for) for every record of the report."""
    incoming = list(incoming)
    wanted = {k for vendor, hostname, serial, _t in incoming if vendor in FOLLOWING_TOOLS and (k := machine_key(hostname, serial))}
    out: dict[tuple[str, str], set[uuid.UUID]] = {}
    if not wanted:
        return out
    for vendor, hostname, serial, heading in incoming:
        key = machine_key(hostname, serial)
        # Only one of the owner's shown clients can be followed to: never the owner's own tenant, never a hidden client.
        if vendor in ANCHOR_TOOLS and key in wanted and heading in clients:
            out.setdefault(key, set()).add(heading)
    serials = sorted({s for s, _h in wanted})
    fresh_since = datetime.now(UTC) - ANCHOR_FRESH
    async with cross_tenant_reads(db):
        for start in range(0, len(serials), 500):
            rows = (
                await db.execute(
                    select(Device.tenant_id, Device.serial_number, Device.hostname, DeviceSource.name)
                    .join(DeviceSource, DeviceSource.device_id == Device.id)
                    .where(
                        Device.tenant_id.in_(clients),
                        Device.serial_number.in_(serials[start : start + 500]),
                        DeviceSource.vendor.in_(ANCHOR_TOOLS),
                        DeviceSource.last_seen >= fresh_since,
                    )
                )
            ).all()
            for tenant_id, serial, hostname, reported_name in rows:
                # The name the RMM gives today: the device's own name is set when it is first seen and is not changed by a rename.
                key = machine_key(reported_name or hostname, serial)
                if key in wanted:
                    out.setdefault(key, set()).add(tenant_id)
    return out


async def remove_left_behind(
    db: Any, clients: set[uuid.UUID], kept: dict[tuple[str, str], uuid.UUID], acting: Callable[[uuid.UUID], Any]
) -> int:
    """Remove a following tool's record from every client other than the one it is stored under now, with its device when nothing else is on it. ``kept`` is {(tool, the tool's id): the client
    it is under now}. Returns how many records were removed. Runs after the report is stored."""
    if not kept:
        return 0
    ids = sorted({ext for _v, ext in kept})
    stale: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID]]] = {}
    async with cross_tenant_reads(db):
        for start in range(0, len(ids), 500):
            rows = (
                await db.execute(
                    select(
                        DeviceSource.id, DeviceSource.tenant_id, DeviceSource.device_id, DeviceSource.vendor, DeviceSource.external_id
                    ).where(
                        DeviceSource.tenant_id.in_(clients),
                        DeviceSource.vendor.in_(FOLLOWING_TOOLS),
                        DeviceSource.external_id.in_(ids[start : start + 500]),
                    )
                )
            ).all()
            for source_id, tenant_id, device_id, vendor, external_id in rows:
                home = kept.get((vendor, external_id))
                if home is not None and tenant_id != home:
                    stale.setdefault(tenant_id, []).append((source_id, device_id))
    removed = 0
    for tenant_id, rows in stale.items():
        async with acting(tenant_id):
            for source_id, device_id in rows:
                await db.execute(delete(DeviceSource).where(DeviceSource.id == source_id, DeviceSource.tenant_id == tenant_id))
                removed += 1
                left = (
                    await db.execute(select(func.count()).select_from(DeviceSource).where(DeviceSource.device_id == device_id))
                ).scalar_one()
                if left == 0:
                    await db.execute(delete(Device).where(Device.id == device_id, Device.tenant_id == tenant_id))
            await db.flush()
    return removed

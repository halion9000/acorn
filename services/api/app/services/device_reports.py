"""Two fleet reports worked out from what the tools already tell A.C.O.R.N about each device (pure): Huntress agent versions, and network device firmware (Auvik).

There is no list of the vendors' releases, so "old" is relative to what the fleet itself runs: a Huntress agent is old when it is more than two releases behind the newest version seen on any client's machines, and a network
device is behind when another device of the same make and model runs newer firmware. Versions are compared by their numbers (1.10 is newer than 1.9).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

OLD_AFTER_RELEASES = 3  # index in the newest-first list of versions: 0 current, 1 and 2 one and two behind, 3 or more is more than two releases old


OFFLINE_WORDS = frozenset({"offline", "disconnected", "down"})
OFFLINE_DAYS = 7


def is_offline(details: dict[str, Any] | None) -> bool:
    """A tool says the device is offline (pure): its ``status`` is one of the offline words, in any case."""
    return str((details or {}).get("status") or "").strip().lower() in OFFLINE_WORDS


def carry_offline_since(old: dict[str, Any] | None, new: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The details a tool just sent, with ``offline_since`` kept for as long as the device stays offline (pure). A device first seen offline starts the clock now; one back online loses it.
    The tool only says "offline", never since when, so the clock starts when A.C.O.R.N first sees it so."""
    out = dict(new)
    out.pop("offline_since", None)
    if is_offline(new):
        before = (old or {}).get("offline_since")
        out["offline_since"] = before if isinstance(before, str) and before else now.astimezone(UTC).isoformat()
    return out


def offline_for_days(devices: list[dict[str, Any]], now: datetime, days: int = OFFLINE_DAYS) -> list[dict[str, Any]]:
    """Devices offline for more than ``days`` days, longest first (pure). Each device has ``client``, ``hostname``, ``model`` and ``offline_since`` (an ISO time); a device with no usable time is left out."""
    out = []
    for d in devices:
        try:
            since = datetime.fromisoformat(str(d.get("offline_since")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
        if now - since > timedelta(days=days):
            out.append({"client": d.get("client") or "", "hostname": d.get("hostname") or "", "model": d.get("model") or "", "offline_since": since.isoformat(), "days_offline": (now - since).days})
    out.sort(key=lambda r: (-r["days_offline"], r["client"].lower(), r["hostname"].lower()))
    return out


def version_key(version: str | None) -> tuple[int, ...]:
    """The numbers in a version string as a tuple to compare (pure): ``1.10.2`` is greater than ``1.9.9``; text with no digits sorts first."""
    nums = tuple(int(n) for n in re.findall(r"\d+", str(version or "")))
    return nums or (-1,)


def huntress_versions(devices: list[dict[str, Any]]) -> dict[str, Any]:
    """The spread of Huntress agent versions, newest first, and the agents more than two releases behind the newest (pure). Each device has ``client``, ``hostname``, ``version`` and optionally ``last_callback``."""
    seen = [d for d in devices if str(d.get("version") or "").strip()]
    ordered = sorted({str(d["version"]).strip() for d in seen}, key=version_key, reverse=True)
    rank = {v: i for i, v in enumerate(ordered)}
    counts = Counter(str(d["version"]).strip() for d in seen)
    spread = [{"version": v, "agents": counts[v], "releases_behind": rank[v]} for v in ordered]
    old = [
        {"client": d.get("client") or "", "hostname": d.get("hostname") or "", "version": str(d["version"]).strip(), "releases_behind": rank[str(d["version"]).strip()], "last_callback": d.get("last_callback")}
        for d in seen
        if rank[str(d["version"]).strip()] >= OLD_AFTER_RELEASES
    ]
    old.sort(key=lambda r: (-r["releases_behind"], r["client"].lower(), r["hostname"].lower()))
    return {"newest": ordered[0] if ordered else None, "agents": len(seen), "without_version": len(devices) - len(seen), "spread": spread, "old": old}


def firmware_behind(devices: list[dict[str, Any]]) -> dict[str, Any]:
    """Network devices running older firmware than another device of the same make and model (pure). Each device has ``client``, ``hostname``, ``manufacturer``, ``model``, ``device_type`` and ``firmware``. A make and model
    with only one firmware version has nothing behind."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for d in devices:
        fw = str(d.get("firmware") or "").strip()
        model = str(d.get("model") or "").strip()
        if fw and model:
            groups[(str(d.get("manufacturer") or "").strip(), model)].append({**d, "firmware": fw})
    rows: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    for (maker, model), members in groups.items():
        versions = sorted({m["firmware"] for m in members}, key=version_key, reverse=True)
        if len(versions) < 2:
            continue
        newest = versions[0]
        behind = [m for m in members if version_key(m["firmware"]) < version_key(newest)]
        models.append({"manufacturer": maker, "model": model, "newest": newest, "devices": len(members), "behind": len(behind), "versions": versions})
        rows += [{"client": m.get("client") or "", "hostname": m.get("hostname") or "", "manufacturer": maker, "model": model, "device_type": m.get("device_type") or "", "firmware": m["firmware"], "newest": newest} for m in behind]
    rows.sort(key=lambda r: (r["manufacturer"].lower(), r["model"].lower(), r["client"].lower(), r["hostname"].lower()))
    models.sort(key=lambda m: (-m["behind"], m["manufacturer"].lower(), m["model"].lower()))
    return {"models": models, "devices": rows}


MAX_MISMATCH_LINES = 80


def org_mismatches(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Machines whose Huntress organization is not the client their NinjaOne device is filed under (pure). Each device has ``tenant``, ``client``, ``vendor`` (``huntress`` or ``ninjaone``), ``serial`` and ``hostname``, and optionally ``family`` (the id of the client's family).

    A machine is matched across the two tools by its serial number (a placeholder, a MAC address or the machine's own name is not a serial: see ``device_identity.real_serial``). It is a mismatch only when
    NO Huntress copy sits under a client that also holds a NinjaOne copy: a machine filed under the same client in both is fine, even if a second copy of it sits elsewhere. Sorted by the NinjaOne client, then name."""
    from app.services.device_identity import normalize_serial  # noqa: PLC0415 - keeps this module's imports small

    by_serial: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"huntress": [], "ninjaone": []})
    for d in devices:
        vendor = str(d.get("vendor") or "")
        key = normalize_serial(d.get("serial"))
        if key and vendor in ("huntress", "ninjaone"):
            by_serial[key][vendor].append(d)
    rows: list[dict[str, Any]] = []
    for key, sides in by_serial.items():
        h, n = sides["huntress"], sides["ninjaone"]
        if not h or not n:
            continue
        if {x.get("tenant") for x in h} & {x.get("tenant") for x in n}:
            continue
        # Clients linked in one family count as one: a machine its tools file under two sibling clients is not a mistake to chase.
        if {x.get("family") for x in h if x.get("family")} & {x.get("family") for x in n if x.get("family")}:
            continue
        rows.append(
            {
                "serial": key,
                "hostname": str(n[0].get("hostname") or h[0].get("hostname") or ""),
                "ninjaone_client": str(n[0].get("client") or ""),
                "huntress_client": str(h[0].get("client") or ""),
            }
        )
    rows.sort(key=lambda r: (r["ninjaone_client"].lower(), r["hostname"].lower(), r["serial"]))
    return rows


def org_mismatch_text(rows: list[dict[str, Any]]) -> tuple[str, str] | None:
    """The subject and text of the weekly mismatch report, or None when every machine is filed under the same client in both tools (pure)."""
    if not rows:
        return None
    n = len(rows)
    lines = [f"- {r['hostname'] or r['serial']}: NinjaOne says {r['ninjaone_client'] or 'no client'}, Huntress says {r['huntress_client'] or 'no client'} (serial {r['serial']})" for r in rows[:MAX_MISMATCH_LINES]]
    more = f"\n...and {n - MAX_MISMATCH_LINES} more" if n > MAX_MISMATCH_LINES else ""
    return (
        f"{n} machine{'' if n == 1 else 's'} filed under different clients in Huntress and NinjaOne",
        f"{n} machine{'s' if n != 1 else ''} whose Huntress organization is not the client of its NinjaOne device. Fix the one that is wrong so each tool's numbers (agents, patching, billing) land on the right client:\n" + "\n".join(lines) + more,
    )


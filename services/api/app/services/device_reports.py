"""Two fleet reports worked out from what the tools already tell A.C.O.R.N about each device (pure): Huntress agent versions, and network device firmware (Auvik).

There is no list of the vendors' releases, so "old" is relative to what the fleet itself runs: a Huntress agent is old when it is more than two releases behind the newest version seen on any client's machines, and a network
device is behind when another device of the same make and model runs newer firmware. Versions are compared by their numbers (1.10 is newer than 1.9).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

OLD_AFTER_RELEASES = 3  # index in the newest-first list of versions: 0 current, 1 and 2 one and two behind, 3 or more is more than two releases old


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

"""How a device is recognised across tools: the serial number is the key, the hostname only suggests.

A serial number is trusted to be the same machine in every tool, so devices from different tools merge on it automatically. Tools often report junk instead of a real serial
("To Be Filled By O.E.M.", "0", "Default string"), and two unrelated machines would then merge, so those values count as no serial. A hostname alone is NOT trusted: the same name can be two
machines (or one machine renamed). A pair is merged on its name only when it is unambiguous (``device_merge.auto_merge_same_name``); every other name match is a "possible duplicate" for a person to confirm.
"""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDERS = frozenset(
    {
        "TOBEFILLEDBYOEM",
        "TOBEFILLEDBYO.E.M.",
        "DEFAULTSTRING",
        "SYSTEMSERIALNUMBER",
        "SERIALNUMBER",
        "NONE",
        "NA",
        "N/A",
        "NULL",
        "UNKNOWN",
        "NOTSPECIFIED",
        "NOTAPPLICABLE",
        "OEM",
        "O.E.M.",
        "TOBEFILLEDBYO.E.M",
        "INVALID",
        "NOSERIAL",
        "NOSERIALNUMBER",
        "XXXXXXXX",
        "123456789",
        "1234567890",
        "0123456789",
    }
)
_MIN_SERIAL_LEN = 4


def normalize_serial(raw: object) -> str | None:
    """The comparable form of a serial number, or None when the value is empty or a known placeholder."""
    if raw is None:
        return None
    text = re.sub(r"\s+", "", str(raw)).upper()
    if len(text) < _MIN_SERIAL_LEN or text in _PLACEHOLDERS:
        return None
    if len(set(text)) == 1:  # 0000000, XXXXXXX, 1111111
        return None
    return text[:100]


_ENDS_IN_IPV4 = re.compile(r"(^|[^0-9])\d{1,3}(\.\d{1,3}){3}$")


_DUPLICATE_MARK = re.compile(r"\s+\(\d{1,2}\)$")


def hostname_key(raw: object) -> str:
    """A hostname reduced for comparison: lower-case, first label only (``PC-01.corp.local`` and ``pc-01`` are one name).

    A name that ends in an IP address is kept whole: its dots separate the numbers, not a domain, and cutting at the first one would make ``Device@10.7.220.92`` and ``Device@10.7.20.55`` both ``device@10``.
    """
    text = str(raw or "").strip().lower()
    if _ENDS_IN_IPV4.search(text):
        return text
    return text.split(".", 1)[0].strip()


def loose_name_key(raw: object) -> str:
    """A hostname reduced further, for telling that two tools spell one name differently: ``Airport SP - Parking`` (UniFi) and ``Airport-SP-Parking`` (Auvik) are both ``airportspparking``.

    Only letters and digits are kept. A name that ends in an IP address keeps its address form (the dots are numbers there), so it is returned as ``hostname_key`` gives it.
    """
    key = hostname_key(raw)
    if _ENDS_IN_IPV4.search(key):
        return key
    # A tool that meets two machines with one name marks the second "NAME (1)" (Liongard does): that is the same name as far as the other tools are concerned.
    return re.sub(r"[^a-z0-9]+", "", _DUPLICATE_MARK.sub("", key))


def mac_key(raw: object) -> str | None:
    """A MAC address reduced for comparison (``1C:6A:1B:49:04:8D``, ``1c-6a-1b-49-04-8d`` and ``1C6A1B49048D`` agree), or None when the value is not twelve hex digits. Auvik keeps the MAC as the serial of a device with none."""
    text = re.sub(r"[^0-9a-f]", "", str(raw or "").lower())
    return text if len(text) == 12 and len(set(text)) > 1 else None


def is_placeholder_name(key: str) -> bool:
    """True for the name a tool invents for a device it could not name (Auvik's ``Device@10.7.220.92``). Two of them say nothing about being the same machine."""
    return key.startswith("device@")


_NO_IP = ("0.0.0.0", "127.", "169.254.", "255.")


def usable_ips(addresses: object) -> set[str]:
    """The IPv4 addresses of a device that can identify it: dotted quads, not 0.0.0.0, loopback, link-local or broadcast."""
    out: set[str] = set()
    for a in addresses if isinstance(addresses, list | tuple | set) else []:
        text = str(a).strip()
        if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", text) and not text.startswith(_NO_IP):
            out.add(text)
    return out


def brand_key(manufacturer: object) -> str:
    """A maker's name reduced for comparison (``Ubiquiti Inc.`` and ``ubiquiti`` agree)."""
    text = re.sub(r"[^a-z0-9]+", " ", str(manufacturer or "").lower()).strip()
    return " ".join(w for w in text.split() if w not in {"inc", "llc", "ltd", "corp", "co", "networks", "technologies"})


def same_brand(a: object, b: object) -> bool:
    """True when two makers do not disagree: either is unknown, or one name contains the other."""
    ka, kb = brand_key(a), brand_key(b)
    return not ka or not kb or ka in kb or kb in ka


# Meraki and UniFi list physical network hardware, each unit once and with its own identity. So two records from one of them are two units however alike their names (a closet of access points
# all called "U6-Pro"), a Meraki unit is never a UniFi unit, and neither is a computer that an agent runs on. A name match involving them is a coincidence, not a duplicate.
HARDWARE_TOOLS = frozenset({"meraki", "unifi"})
# Network discovery tools list each device they find once, under whatever name it has. Two records of one of them in a client are two devices (a closet of switches, a run of "bridge-2" names), so
# two devices that BOTH carry a record from one of these are never offered as duplicates of each other.
DISCOVERY_TOOLS = frozenset({"auvik", "unifi", "meraki"})
AGENT_TOOLS = frozenset(
    {"ninjaone", "huntress", "addigy", "threatmate", "screenconnect", "fieldeffect", "dnsfilter", "autoelevate", "slide", "blumira", "cipp"}
)


def could_be_same_machine(a: set[str], b: set[str]) -> bool:
    """False when the tools behind two devices show they are different things: a hardware tool's unit alongside another hardware unit, or alongside a machine an agent runs on."""
    hw_a, hw_b = a & HARDWARE_TOOLS, b & HARDWARE_TOOLS
    if hw_a and hw_b:
        return False
    return not ((hw_a and b & AGENT_TOOLS) or (hw_b and a & AGENT_TOOLS))


# Windows (NetBIOS) cuts a computer's name to 15 characters, and some tools report the cut name while others report the full one ("NUC-GCR-BBQ1-HO" and "NUC-GCR-BBQ1-HOUSTON").
_NETBIOS_LENGTHS = (15, 16)


def netbios_truncated_pairs(
    devices: list[Any], tools: dict[Any, set[str]], dismissed: set[tuple[Any, Any]], taken: set[tuple[Any, Any]]
) -> list[tuple[Any, Any]]:
    """Pairs of one client's devices where one name is the other cut to the NetBIOS length (15 or 16 characters) and the other is longer.

    Two devices that the same tool reports are two machines (a tool lists each machine once), so a pair needs tools that do not overlap. Two different serial numbers, a hardware unit against a machine an agent runs on,
    made-up names, dismissed pairs and pairs already ``taken`` are left out. Each pair is ordered by id text.
    """
    keyed = [(d, hostname_key(d.hostname)) for d in devices]
    by_prefix: dict[str, list[tuple[Any, str]]] = {}
    for d, key in keyed:
        if len(key) > _NETBIOS_LENGTHS[0] and not is_placeholder_name(key):
            by_prefix.setdefault(key[: _NETBIOS_LENGTHS[0]], []).append((d, key))
    out: list[tuple[Any, Any]] = []
    seen = set(taken)
    for a, key_a in keyed:
        if len(key_a) not in _NETBIOS_LENGTHS or is_placeholder_name(key_a):
            continue
        for b, key_b in by_prefix.get(key_a[: _NETBIOS_LENGTHS[0]], ()):
            if b.id == a.id or len(key_b) <= len(key_a) or not key_b.startswith(key_a):
                continue
            if getattr(a, "serial_number", None) and getattr(b, "serial_number", None):
                continue
            ta, tb = tools.get(a.id, set()), tools.get(b.id, set())
            if ta & tb or not could_be_same_machine(ta, tb):
                continue
            pair = tuple(sorted((a.id, b.id), key=str))
            if pair in dismissed or pair in seen:
                continue
            seen.add(pair)
            out.append(pair)  # type: ignore[arg-type]
    return out


def ip_brand_pairs(
    devices: list[Any], tools: dict[Any, set[str]], dismissed: set[tuple[Any, Any]], taken: set[tuple[Any, Any]]
) -> list[tuple[Any, Any]]:
    """Pairs of one client's devices where one has a made-up name (Auvik's ``Device@10.7.220.92``) and the other holds one of its addresses without disagreeing about the maker.

    Names say nothing for such a device, so it is matched on what Auvik does know: an address and, when both sides state one, the brand. Two different serial numbers, a hardware unit against a machine an agent
    runs on, dismissed pairs and pairs already ``taken`` are left out. Two made-up names are looked at once, from the one whose id sorts first. Each pair is ordered by id text.

    Each device's name key and addresses are worked out once and the devices are indexed by address, so a made-up-name device looks only at the devices that share one of its addresses (it used to scan the
    whole client again for every one: 1.8 million address reads for 187 clients). The pairs and their order are exactly what the full scan gave.
    """
    out: list[tuple[Any, Any]] = []
    seen = set(taken)
    keyed = [(d, hostname_key(d.hostname), usable_ips(d.ip_addresses)) for d in devices]
    by_ip: dict[str, list[int]] = {}
    for i, (_d, _k, ips) in enumerate(keyed):
        for ip in ips:
            by_ip.setdefault(ip, []).append(i)
    for a, key_a, ips in keyed:
        if not is_placeholder_name(key_a) or not ips:
            continue
        for j in sorted({j for ip in ips for j in by_ip.get(ip, ())}):
            b, key_b, _ips_b = keyed[j]
            if b.id == a.id or (is_placeholder_name(key_b) and str(b.id) < str(a.id)):
                continue
            if not same_brand(a.manufacturer, b.manufacturer):
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

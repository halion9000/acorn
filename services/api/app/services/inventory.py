"""The stock Live Oak holds for clients: reading the SharePoint list exports, and the rules that go with an item.

Pure: no database, no clock. The exports (checked against Live Oak's own five lists, 2026-10-30) come in two shapes. The big lists have a ``Customer`` column (``LO Inventory`` for stock, ``NUC Inventory`` for the NUCs); the per-client lists
(Malk, A Pup Above, Prelude...) have none, because the list itself is the client, so a file can be given the client it belongs to. Notes arrive as HTML (``<p><br></p>``), dates as M/D/YYYY and statuses in the lists' own words.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.services.client_matching import EXACT, Candidate, normalize_name, score, suggest
from app.services.device_identity import normalize_serial

KINDS = ("stock", "nuc")
STATUSES = ("checked_in", "checked_out", "offline", "retired")
MAX_ROWS = 5000

# The customer name Live Oak's own list uses for its own stock: it belongs to Live Oak, not to a client.
OWN_NAMES = frozenset({"lo inventory (office)", "lo inventory", "live oak", "live oak it partners", "live oak it", "office", "internal"})


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (header or "").lower().lstrip("﻿"))


# header (spaces, case and punctuation ignored) -> the field it fills
HEADERS: dict[str, str] = {
    "id": "external_ref",
    "customer": "customer_name",
    "entryname": "name",
    "computername": "name",
    "name": "name",
    "devicemodel": "model",
    "modelno": "model",
    "model": "model",
    "deployedto": "deployed_to",
    "person": "person",
    "serialno": "serial",
    "serial": "serial",
    "serialnumber": "serial",
    "barcode": "barcode",
    "quantity": "quantity",
    "qty": "quantity",
    "notes": "notes",
    "status": "status",
    "tags": "tags",
    "assettype": "category",
    "category": "category",
    "type": "category",
    "partno": "part_no",
    "hascharger": "has_charger",
    "checkedoutdate": "checked_out_at",
    "checkedindate": "checked_in_at",
    "ninja": "ninja_url",
    "cpu": "cpu",
    "memory": "memory",
    "hdd": "storage",
    "storage": "storage",
    "sitelocation": "site",
    "site": "site",
    "location": "site",
    "initialdeploymentdate": "deployed_at",
    "initialdeployment": "deployed_at",
    "redeploymentdate": "redeployed_at",
    "redeployment": "redeployed_at",
    "accountingtreatment": "accounting_treatment",
}


def clean_text(value: Any, limit: int) -> str | None:
    """Text from a list cell: HTML tags and entities removed, lines kept, spaces tidied, cut to ``limit``; None when nothing is left."""
    text = str(value or "")
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</\s*p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(entity, char)
    text = "\n".join(" ".join(line.split()) for line in text.splitlines())
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return text[:limit] or None


def parse_date(value: Any) -> date | None:
    """A date as the lists write it (``9/9/2025``) or ISO; None when it is not one."""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_bool(value: Any) -> bool | None:
    text = str(value or "").strip().lower()
    if text in ("true", "yes", "y", "1", "x"):
        return True
    if text in ("false", "no", "n", "0"):
        return False
    return None


def parse_status(value: Any) -> tuple[str, list[str]]:
    """``(status, extra tags)`` from the lists' wording: Checked In or Out (with or without spaces), Offline, Archived and Decommissioned (retired), and "Checked In Damaged" (in, tagged damaged). Anything else is checked in."""
    text = re.sub(r"[^a-z]+", "", str(value or "").lower())
    if text in ("archived", "decommissioned", "retired", "disposed"):
        return "retired", []
    if text == "offline":
        return "offline", []
    if text.startswith("checkedout"):
        return "checked_out", []
    if text.startswith("checkedin"):
        return "checked_in", ["damaged"] if "damaged" in text else []
    return "checked_in", []


def parse_tags(value: Any) -> list[str]:
    seen: list[str] = []
    for part in re.split(r"[;,]", str(value or "")):
        tag = part.strip()[:40]
        if tag and tag.lower() not in (t.lower() for t in seen):
            seen.append(tag)
    return seen[:12]


def _quantity(value: Any) -> int:
    try:
        n = int(float(str(value).strip()))
    except ValueError:
        return 1
    return max(0, min(n, 100_000))


@dataclass
class ParsedRow:
    """One list row as an item, before it is placed under a client."""

    line: int
    item: dict[str, Any]
    customer_name: str | None = None
    problems: list[str] = field(default_factory=list)


def row_to_item(row: dict[str, str], kind: str, line: int = 0) -> ParsedRow:
    """One exported row as an item dict (fields of ``InventoryItem``) and the customer named on it, if any. A row with no name, serial or model is a problem and is left out by the caller."""
    values: dict[str, str] = {}
    for header, cell in row.items():
        target = HEADERS.get(_key(header or ""))
        if target and (cell or "").strip() and target not in values:
            values[target] = cell
    status, extra_tags = parse_status(values.get("status"))
    serial = clean_text(values.get("serial"), 100)
    model = clean_text(values.get("model"), 200)
    name = clean_text(values.get("name"), 300) or model or serial
    person = clean_text(values.get("person") or values.get("deployed_to"), 200)
    tags = parse_tags(values.get("tags"))
    for tag in extra_tags:
        if tag not in tags:
            tags.append(tag)
    item: dict[str, Any] = {
        "kind": kind,
        "name": name or "",
        "category": clean_text(values.get("category"), 80),
        "serial": serial,
        "model": model,
        "quantity": _quantity(values.get("quantity", 1)),
        "status": status,
        "site": clean_text(values.get("site"), 200),
        "person": person,
        "part_no": clean_text(values.get("part_no"), 60),
        "has_charger": parse_bool(values.get("has_charger")),
        "cpu": clean_text(values.get("cpu"), 200),
        "memory": clean_text(values.get("memory"), 60),
        "storage": clean_text(values.get("storage"), 60),
        "ninja_url": clean_text(values.get("ninja_url"), 500) if str(values.get("ninja_url", "")).startswith("http") else None,
        "accounting_treatment": clean_text(values.get("accounting_treatment"), 120),
        "deployed_at": parse_date(values.get("deployed_at")),
        "redeployed_at": parse_date(values.get("redeployed_at")),
        "checked_out_at": parse_date(values.get("checked_out_at")),
        "checked_in_at": parse_date(values.get("checked_in_at")),
        "notes": clean_text(values.get("notes"), 4000),
        "tags": tags,
        "external_ref": clean_text(values.get("external_ref"), 60),
    }
    problems = [] if item["name"] else ["no name, model or serial number"]
    return ParsedRow(line=line, item=item, customer_name=clean_text(values.get("customer_name"), 200), problems=problems)


def parse_csv(text: str, kind: str) -> list[ParsedRow]:
    """The rows of an exported list. The first row is the header; at most ``MAX_ROWS`` rows are read."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of: {', '.join(KINDS)}")
    reader = csv.DictReader(io.StringIO((text or "").lstrip("﻿")))
    rows: list[ParsedRow] = []
    for i, raw in enumerate(reader, start=2):
        if i - 1 > MAX_ROWS:
            break
        if not any((v or "").strip() for v in raw.values() if isinstance(v, str)):
            continue
        rows.append(row_to_item({k: (v or "") for k, v in raw.items() if k is not None}, kind, i))
    return rows


# ---- placing a row under a client --------------------------------------------------------------------------------------------------------------------------


OWN = "own"
SKIP = "skip"


@dataclass(frozen=True)
class Placement:
    """Where a customer's rows go: ``tenant_id`` (a client's, or the owner's own), how it was decided, and the nearest clients when it was not."""

    tenant_id: str | None
    how: str  # exact | own | chosen | unmatched
    suggestions: list[tuple[str, str, float]] = field(default_factory=list)


def place_customer(
    name: str | None, own_tenant: str, clients: list[Candidate], chosen: dict[str, str] | None = None, default_client: str | None = None
) -> Placement:
    """Which tenant a row belongs to.

    In this order: a choice the person made for that customer name (a client id, ``own`` or ``skip``); the file's default client; no customer or one of Live Oak's own names (Live Oak's own stock); a client whose name is the same once
    punctuation and company words are ignored. Anything else is unmatched: it is kept under Live Oak's tenant with the customer's name, and the nearest clients are offered, so nothing is dropped and nothing is guessed.
    """
    key = (name or "").strip().lower()
    if chosen and key in chosen:
        pick = chosen[key]
        if pick == SKIP:
            return Placement(None, "chosen")
        return Placement(own_tenant if pick == OWN else pick, "chosen")
    if default_client:
        return Placement(default_client, "chosen")
    if not key or key in OWN_NAMES:
        return Placement(own_tenant, "own")
    exact = [c for c in clients if score(name or "", c.name) == EXACT]
    if len(exact) == 1:
        return Placement(exact[0].tenant_id, "exact")
    near = suggest(name or "", clients, limit=3)
    return Placement(own_tenant, "unmatched", [(s.tenant_id, s.name, s.score) for s in near])


def customers_of(rows: list[ParsedRow]) -> dict[str, int]:
    """Each distinct customer name (as written, first spelling kept) with how many rows name it; rows with none are counted under an empty name."""
    seen: dict[str, tuple[str, int]] = {}
    for r in rows:
        original = r.customer_name or ""
        k = normalize_name(original) or original.lower()
        name, n = seen.get(k, (original, 0))
        seen[k] = (name, n + 1)
    return dict(seen.values())


# ---- an item's own rules ---------------------------------------------------------------------------------------------------------------------------------


def can_check_out(status: str) -> bool:
    return status in ("checked_in", "offline")


def can_check_in(status: str) -> bool:
    return status == "checked_out"


def same_item(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Whether two item dicts are the same thing: the same list id, else the same serial number (ignoring case and spaces). Items with neither are never the same, so two blank-serial cables stay two cables."""
    if a.get("external_ref") and b.get("external_ref"):
        return a["external_ref"] == b["external_ref"]
    sa, sb = _serial_key(a.get("serial")), _serial_key(b.get("serial"))
    return bool(sa and sa == sb)


def _serial_key(serial: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(serial or "").lower())


def serial_key(serial: Any) -> str:
    """A serial number reduced for matching (``abc 123`` and ``ABC-123`` agree)."""
    return _serial_key(serial)


def usable_serial(serial: Any) -> str:
    """The matching form of a serial number that can identify one thing, else an empty string: not blank, not a placeholder a BIOS or a person left behind (``Default string``, ``0000000``)."""
    return _serial_key(serial) if normalize_serial(serial) else ""


def shared_serials(items: list[dict[str, Any]]) -> set[str]:
    """The serial numbers that appear on more than one item in ``items``. Such a value is not an identifier: the NUC list has "KAMRUI" (the maker's name) on 64 NUCs and "Default string" on 14, and treating them as serial numbers
    would merge sixty different machines into one."""
    seen: dict[str, int] = {}
    for item in items:
        key = usable_serial(item.get("serial"))
        if key:
            seen[key] = seen.get(key, 0) + 1
    return {k for k, n in seen.items() if n > 1}

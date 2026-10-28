"""Read the Sigma rules the repository ships under ``detections/sigma-imports/`` as plain entries (name, level, tags, the rule text...).

They become the parent's rules and rule packs in ``app.services.sigma_packs``. Only rules outside ``_quarantine/`` are read (a quarantined rule is one the engine cannot run); a file that is
not a rule, and a repeat of an id already read, is skipped. The author is credited as the upstream project, and the licence (DRL-1.1) and its link are kept in the entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

SOURCE_DIR = "sigma-imports"
_LEVELS = {"informational", "low", "medium", "high", "critical"}


def _tags(doc: dict[str, Any]) -> list[str]:
    raw = doc.get("tags")
    out: list[str] = []
    if isinstance(raw, dict):
        for tech in raw.get("mitre") or []:
            out.append(f"attack.{str(tech).lower()}")
        out.extend(str(c) for c in raw.get("categories") or [])
    elif isinstance(raw, list):
        out.extend(str(t) for t in raw)
    return list(dict.fromkeys(out))


def entry_for(raw_text: str, rel_path: str) -> dict[str, Any] | None:
    """The entry for one rule file, or None when the file is not a rule."""
    try:
        doc = yaml.safe_load(raw_text)
    except yaml.YAMLError:
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("detection"), dict) or not isinstance(doc.get("logsource"), dict):
        return None
    rule_id, name = doc.get("id"), doc.get("name")
    if not isinstance(rule_id, str) or not rule_id.strip() or not isinstance(name, str) or not name.strip():
        return None
    level = str(doc.get("severity", "medium")).lower()
    prov = doc.get("provenance") if isinstance(doc.get("provenance"), dict) else {}
    author = str(prov.get("source") or "SigmaHQ/sigma")
    if prov.get("license"):
        author = f"{author} (licence {prov['license']})"
    return {
        "id": rule_id.strip(),
        "name": name.strip()[:255],
        "description": str(doc.get("description") or "").strip(),
        "author": author,
        "tags": _tags(doc),
        "logsource_category": str(doc["logsource"].get("category") or ""),
        "logsource_product": str(doc["logsource"].get("product") or ""),
        "level": level if level in _LEVELS else "medium",
        "sigma_yaml": raw_text,
        "source_file": rel_path,
        "license_url": prov.get("license_url"),
    }


def read_entries(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """The rule entries under ``root`` (the detections folder) and the files that were skipped (not a rule, or a repeated id)."""
    base = root / SOURCE_DIR
    entries: list[dict[str, Any]] = []
    skipped: list[str] = []
    seen: set[str] = set()
    if not base.is_dir():
        return entries, skipped
    for path in sorted(base.rglob("*.yaml")):
        rel = path.relative_to(root).as_posix()
        if "_quarantine" in path.relative_to(base).parts:
            continue
        entry = entry_for(path.read_text(encoding="utf-8"), rel)
        if entry is None or entry["id"] in seen:
            skipped.append(rel)
            continue
        seen.add(entry["id"])
        entries.append(entry)
    return entries, skipped

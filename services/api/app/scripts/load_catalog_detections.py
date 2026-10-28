"""Put the Sigma rules the repository ships under ``detections/sigma-imports/`` into the Detection Catalog (``community_catalog_items``, kind ``detection``) as approved entries.

Why this exists: the catalog page lists approved rows of that table, and nothing ever filled it, so it always said "No detection rules found". The first-party rules are loaded as built-in
rules by ``load_builtin_detections`` (they are in AiSOC's own format, not Sigma, so they are not offered here). The imported Sigma rules are what the catalog's Install button is built for: it copies
the Sigma text into the tenant's rules in ``testing`` status, where it does not fire until someone promotes it.

Only rules outside ``_quarantine/`` are listed (a quarantined rule is one the engine cannot run). The author is credited as the upstream project, and the licence (DRL-1.1) and its link are kept
in the entry. Idempotent: an entry that exists is never touched, so installs, ratings and edits made later survive a re-run.

    python -m app.scripts.load_catalog_detections            # prints one JSON line: {"ok": true, "created": N, "existing": N, "skipped": N}
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.scripts.load_builtin_detections import detections_dir

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


def entry_for(raw_text: str, rel_path: str, now: str) -> dict[str, Any] | None:
    """The catalog entry for one rule file, or None when the file is not a rule the catalog can offer."""
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
        "status": "approved",
        "install_count": 0,
        "rating": 0.0,
        "rating_count": 0,
        "submitted_at": now,
        "sigma_yaml": raw_text,
        "source_file": rel_path,
        "license_url": prov.get("license_url"),
    }


def read_entries(root: Path, now: str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    now = now or datetime.now(UTC).isoformat()
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
        entry = entry_for(path.read_text(encoding="utf-8"), rel, now)
        if entry is None or entry["id"] in seen:
            skipped.append(rel)
            continue
        seen.add(entry["id"])
        entries.append(entry)
    return entries, skipped


async def load(session: Any, entries: list[dict[str, Any]]) -> dict[str, int]:
    """Add the entries the catalog does not have yet. The caller owns the transaction and commits."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.community_catalog import CommunityCatalogItem  # noqa: PLC0415

    have = set(
        (await session.execute(select(CommunityCatalogItem.item_id).where(CommunityCatalogItem.kind == "detection"))).scalars().all()
    )
    created = 0
    for e in entries:
        if e["id"] in have:
            continue
        session.add(CommunityCatalogItem(kind="detection", item_id=e["id"], status="approved", submitter_tenant_id=None, data=e))
        created += 1
    return {"created": created, "existing": len(entries) - created}


async def main() -> None:
    root = detections_dir()
    if root is None:
        print(json.dumps({"ok": False, "error": "no detections folder found (set AISOC_DETECTIONS_DIR)"}))
        sys.exit(1)
    entries, skipped = read_entries(root)
    from app.db.database import AsyncSessionLocal  # noqa: PLC0415

    async with AsyncSessionLocal() as session:
        result = await load(session, entries)
        await session.commit()
    print(json.dumps({"ok": True, **result, "skipped": len(skipped)}))


if __name__ == "__main__":
    asyncio.run(main())

"""Built-in triage for vendor alerts, from the 60-day alert review (docs/ALERT_REVIEW_2026-11-21.md).

Two things, both run by the suppression sweeper every minute and both safe to repeat:

1. ``sweep_attack_mapping``: vendor alerts arrive with no ATT&CK technique (85 percent of them), so the heatmap showed only the identity detections. A short list of title patterns that really are a technique
   fills it in, for alerts that have none. Titles that are not honestly one technique (BitLocker off, old operating systems, an agent that was never installed) stay unmapped.
2. ``sweep_by_design``: alerts that are true of the machine by design and never need a person: disk space on the volumes macOS keeps full on purpose (iOS simulator runtimes, mounted installers, cryptex images, the
   recovery volume) and the information messages "reported as junk" / "reported as not junk". They are resolved as benign, with a note in the alert saying which rule did it, so they can be found and reopened.
   Real disk problems (the data volume, ``C:``) and "reported as malware or phish" are never touched.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

# (pattern on the title, technique, tactic). First match wins.
ATTACK_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"^email reported by user as (malware or )?phish", re.I), "T1566", "Initial Access"),
    (re.compile(r"^(unfamiliar sign-in properties|atypical travel|microsoft 365: user authentication from new country|activities from suspicious user agents)", re.I), "T1078", "Initial Access"),
    (re.compile(r"^potential unsecured credentials", re.I), "T1552.001", "Credential Access"),
    (re.compile(r"windows service: .?microsoft defender antivirus service.* is stopped", re.I), "T1562.001", "Defense Evasion"),
    (re.compile(r"sharepoint \d+ or more file deletions", re.I), "T1485", "Impact"),
    (re.compile(r"^password spray", re.I), "T1110.003", "Credential Access"),
]

# Mount points macOS keeps full or read-only on purpose.
BY_DESIGN_VOLUME = re.compile(r"^/(Library/Developer/CoreSimulator|private/var/run/com\.apple\.security\.cryptexd|Volumes/Recovery)", re.I)
# A mounted disk image (an installer) is full and read-only by design; an external drive that is nearly full is a real problem, so /Volumes counts only for installer-like names or a 100 percent reading.
INSTALLER_VOLUME = re.compile(r"^/Volumes/.*(install|setup|command ?work ?station)", re.I)
PERCENT = re.compile(r"\((\d{1,3})%\)")
DISK_ALERT = re.compile(r"^disk volume (usage|free space) for (?P<volume>\S+)", re.I)
JUNK_REPORT = re.compile(r"^email reported by user as (junk|not junk)\s*$", re.I)
AUTO_TRIAGE_NOTE = "auto_triage"


def technique_for(title: str | None) -> tuple[str, str] | None:
    """The ATT&CK technique and tactic a vendor alert title really is, or None (pure)."""
    t = (title or "").strip()
    for pattern, technique, tactic in ATTACK_PATTERNS:
        if pattern.search(t):
            return technique, tactic
    return None


def by_design_reason(title: str | None) -> str | None:
    """Why an alert needs no person, or None (pure). Disk alerts count only for volumes macOS keeps full on purpose; the data volume and Windows drives are real."""
    t = (title or "").strip()
    m = DISK_ALERT.search(t)
    if m:
        volume = m.group("volume")
        pct = PERCENT.search(t)
        full_image = volume.startswith("/Volumes/") and bool(INSTALLER_VOLUME.search(volume) or (pct and int(pct.group(1)) >= 100))
        if volume.startswith("/System/Volumes/Data") or not (BY_DESIGN_VOLUME.search(volume) or full_image):
            return None
        return "disk space on a volume macOS keeps full or read-only on purpose (simulator runtime, installer, cryptex or recovery volume)"
    if JUNK_REPORT.match(t):
        return "a user's junk report is information, not a threat"
    return None


async def sweep_attack_mapping(db: Any, limit: int = 2000) -> int:
    """Give vendor alerts that have no technique the one their title really is. Returns how many were changed. The caller commits."""
    like = ["email reported by user as%phish%", "unfamiliar sign-in properties%", "atypical travel%", "microsoft 365: user authentication from new country%", "activities from suspicious user agents%", "potential unsecured credentials%", "%microsoft defender antivirus service%stopped%", "%sharepoint % or more file deletions%", "password spray%"]
    rows = (
        await db.execute(
            text(
                "SELECT id, title FROM alerts WHERE (mitre_techniques IS NULL OR mitre_techniques = '[]'::jsonb OR mitre_techniques = 'null'::jsonb) "
                "AND lower(title) LIKE ANY (CAST(:like AS TEXT[])) ORDER BY created_at DESC LIMIT :n"
            ),
            {"like": like, "n": limit},
        )
    ).all()
    changed = 0
    for alert_id, title in rows:
        found = technique_for(title)
        if found is None:
            continue
        await db.execute(
            text("UPDATE alerts SET mitre_techniques = CAST(:t AS JSONB), mitre_tactics = CAST(:k AS JSONB) WHERE id = :id"),
            {"t": f'["{found[0]}"]', "k": f'["{found[1]}"]', "id": alert_id},
        )
        changed += 1
    return changed


async def sweep_by_design(db: Any, limit: int = 2000, now: datetime | None = None) -> int:
    """Resolve, as benign, new alerts that are true by design (see the module note). Returns how many. The caller commits."""
    now = now or datetime.now(UTC)
    rows = (
        await db.execute(
            text(
                "SELECT id, title FROM alerts WHERE status = 'new' AND (lower(title) LIKE 'disk volume usage for %' OR lower(title) LIKE 'disk volume free space for %' "
                "OR lower(title) LIKE 'email reported by user as junk%' OR lower(title) LIKE 'email reported by user as not junk%') ORDER BY created_at DESC LIMIT :n"
            ),
            {"n": limit},
        )
    ).all()
    done = 0
    for alert_id, title in rows:
        reason = by_design_reason(title)
        if reason is None:
            continue
        await db.execute(
            text(
                "UPDATE alerts SET status = 'resolved', disposition = 'benign', resolved_at = :now, updated_at = :now, "
                "enrichment_data = jsonb_set(CASE WHEN jsonb_typeof(enrichment_data) = 'object' THEN enrichment_data ELSE '{}'::jsonb END, '{auto_triage}', CAST(:note AS JSONB)) "
                "WHERE id = :id AND status = 'new'"
            ),
            {"now": now, "id": alert_id, "note": '{"rule": "by design", "reason": ' + __import__("json").dumps(reason) + "}"},
        )
        done += 1
    return done

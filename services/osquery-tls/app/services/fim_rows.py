"""Turn a file-integrity result row from osquery into a ``fim_event`` row.

The FIM packs (packs/aisoc-fim-*.yaml) name their queries after what they watch (``passwd_changes``, ``sudoers_changes``), not after the table, so a row is recognised by
its columns: osquery's ``file_events`` table always gives ``target_path`` and an ``action`` in capitals (CREATED, UPDATED, DELETED, ...). The ``/fim`` pages read the
``fim_event`` table, and nothing wrote it, so they were always empty.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models.fim_event import FimEvent

_ACTIONS = {
    "CREATED",
    "UPDATED",
    "DELETED",
    "ATTRIBUTES_MODIFIED",
    "MOVED_FROM",
    "MOVED_TO",
    "OPENED",
    "ACCESSED",
    "CLOSED",
    "TRUNCATED",
    "LINKED",
    "UNLINKED",
    "RENAMED",
}


def _int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _text(value: Any, limit: int) -> str | None:
    text = str(value).strip() if value not in (None, "") else ""
    return text[:limit] or None


def _when(row: dict, entry: dict, now: datetime) -> datetime:
    for value in (row.get("time"), entry.get("unixTime")):
        seconds = _int(value)
        if seconds is not None and seconds > 0:
            try:
                return datetime.fromtimestamp(seconds, tz=UTC)
            except (OverflowError, OSError, ValueError):
                continue
    return now


def fim_event_from(
    row: Any, *, entry: dict, node_key: str, hostname: str | None, tenant_id: str, now: datetime | None = None
) -> FimEvent | None:
    """A ``FimEvent`` for a ``file_events`` row, else None (pure: nothing is stored here)."""
    if not isinstance(row, dict):
        return None
    path = _text(row.get("target_path"), 4000)
    action = str(row.get("action") or "").strip().upper()
    if path is None or action not in _ACTIONS:
        return None
    return FimEvent(
        tenant_id=str(tenant_id)[:64],
        node_key=str(node_key)[:128],
        hostname=_text(hostname, 255),
        target_path=path,
        action=action,
        md5=_text(row.get("md5"), 64),
        sha256=_text(row.get("sha256"), 128),
        pid=_int(row.get("pid")),
        ppid=_int(row.get("ppid")),
        process_name=_text(row.get("process_name") or row.get("name"), 255),
        username=_text(row.get("username"), 128),
        event_time=_when(row, entry, now or datetime.now(UTC)),
    )

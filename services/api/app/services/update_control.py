"""The hand-off between A.C.O.R.N's "Update" button and the VM that runs it.

The API container never gets a way to run anything. It only writes a small request file into a shared folder (ACORN_UPDATE_CTL_DIR, `/srv/acorn/update-ctl` on the Azure VM). A systemd path unit on the VM sees the file and runs `infra/azure/update-acorn.sh` (pull, rebuild, migrate, health check, roll back on failure), whose output lands in `last-run.log` in the same folder. This module reads that state back for the screen. The file names are fixed here and the request holds no command, so what a request can cause is exactly one thing: the update script.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REQUEST_FILE = "request.json"
RUNNING_FILE = "running"
RUN_LOG = "last-run.log"
HISTORY_FILE = "history.log"
HISTORY_SHOWN = 20
# Who pressed Update and when, one JSON line each, written by the API only (the update script never reads it). The latest ASKED_KEPT are kept.
ASKED_FILE = "asked.log"
# What each update brought: one file per new commit, written by the update script, holding the titles of the commits it installed.
CHANGES_DIR = "changes"
CHANGES_SHOWN = 20
CHANGE_MAX = 200
ASKED_KEPT = 50
# A run is put down to a request made at most this long before the run was recorded, plus however long the run itself took.
ASKED_WINDOW_SECONDS = 30 * 60
_HISTORY_OK = {"ok", "verify_ok", "rollback_ok"}
_SAFE = re.compile(r"^[A-Za-z0-9_.:-]{1,40}$")
TAIL_LINES = 40
_SUCCESS = re.compile(r"UPDATE OK|already up to date|VERIFY OK|ROLLBACK OK")
_FAILURE = re.compile(r"FAILED|ROLLED BACK|NOT healthy")


@dataclass
class UpdateState:
    available: bool
    state: str  # "unavailable" | "idle" | "queued" | "running"
    requested_by: str | None = None
    requested_at: str | None = None
    last_run_at: str | None = None
    last_run_ok: bool | None = None
    summary: str | None = None
    log: list[str] = field(default_factory=list)
    # Past runs that did something, newest first: when, the script's own status word, the commit it ended on, and what kind of run it was.
    history: list[dict] = field(default_factory=list)


class UpdateRefused(Exception):
    """The request cannot be made now (code is a short reason for the screen)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def control_dir(env: dict[str, str] | None = None) -> Path | None:
    raw = (env if env is not None else os.environ).get("ACORN_UPDATE_CTL_DIR", "").strip()
    return Path(raw) if raw else None


def _verdict(lines: list[str]) -> tuple[bool | None, str | None]:
    """The last line that says how the run went decides, as in CORE's own reading of the same script."""
    for line in reversed(lines):
        if _FAILURE.search(line):
            return False, line.strip()[:300]
        if _SUCCESS.search(line):
            return True, line.strip()[:300]
    return None, (lines[-1].strip()[:300] if lines else None)


def parse_history(text: str, shown: int = HISTORY_SHOWN) -> list[dict]:
    """The update script's history lines (time, status, commit, mode and, since 2026-11-11, the seconds the run took; tab-separated, newest last) as rows, newest first. An older line has no
    seconds (None). A line that is not four or five plain fields is skipped: the file is written by a script, but it is shown on a page, so nothing unexpected is passed through."""
    rows = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) not in (4, 5) or not all(_SAFE.match(p) for p in parts):
            continue
        at, status, commit, mode = parts[:4]
        seconds = None
        if len(parts) == 5:
            if not parts[4].isdigit():
                continue
            seconds = int(parts[4])
        try:
            datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            continue
        rows.append(
            {
                "at": at,
                "status": status,
                "ok": status in _HISTORY_OK,
                "commit": None if commit == "none" else commit,
                "mode": mode,
                "seconds": seconds,
            }
        )
    return rows[::-1][:shown]


def read_state(directory: Path | None) -> UpdateState:
    if directory is None or not directory.is_dir():
        return UpdateState(available=False, state="unavailable")
    request = directory / REQUEST_FILE
    running = directory / RUNNING_FILE
    state = "running" if running.exists() else "queued" if request.exists() else "idle"
    out = UpdateState(available=True, state=state)
    if request.exists():
        try:
            data = json.loads(request.read_text(encoding="utf-8"))
            out.requested_by = str(data.get("requested_by", ""))[:200] or None
            out.requested_at = str(data.get("requested_at", "")) or None
        except (OSError, ValueError):
            pass
    try:
        out.history = attach_changes(
            attach_askers(parse_history((directory / HISTORY_FILE).read_text(encoding="utf-8", errors="replace")), read_asked(directory)),
            directory,
        )
    except OSError:
        pass  # no history yet
    log = directory / RUN_LOG
    if log.exists():
        try:
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        out.log = [ln[:400] for ln in lines[-TAIL_LINES:]]
        out.last_run_at = datetime.fromtimestamp(log.stat().st_mtime, UTC).isoformat()
        if state == "idle":
            out.last_run_ok, out.summary = _verdict(lines)
        else:
            out.summary = lines[-1].strip()[:300] if lines else None
    return out


def request_update(directory: Path | None, requested_by: str, now: datetime | None = None) -> None:
    """Ask for one update. Refused when the folder is missing or one is already queued or running."""
    if directory is None or not directory.is_dir():
        raise UpdateRefused("unavailable", "Updating from here is not set up on this A.C.O.R.N.")
    if (directory / RUNNING_FILE).exists() or (directory / REQUEST_FILE).exists():
        raise UpdateRefused("busy", "An update is already waiting or running.")
    body = {"requested_by": requested_by, "requested_at": (now or datetime.now(UTC)).isoformat()}
    tmp = directory / (REQUEST_FILE + ".tmp")
    tmp.write_text(json.dumps(body), encoding="utf-8")
    os.replace(tmp, directory / REQUEST_FILE)
    _note_asked(directory, requested_by, body["requested_at"])


def _note_asked(directory: Path, requested_by: str, at: str) -> None:
    """Remember who asked, for the history list. Never fails a request: the update matters more than the note."""
    try:
        file = directory / ASKED_FILE
        old = file.read_text(encoding="utf-8", errors="replace").splitlines() if file.exists() else []
        lines = [*old, json.dumps({"by": requested_by[:200], "at": at})][-ASKED_KEPT:]
        file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def read_asked(directory: Path) -> list[tuple[datetime, str]]:
    """Who asked for an update and when, oldest first; a line that cannot be read is skipped."""
    out: list[tuple[datetime, str]] = []
    try:
        lines = (directory / ASKED_FILE).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            data = json.loads(line)
            at = datetime.fromisoformat(str(data["at"]))
            by = str(data["by"])[:200]
        except (ValueError, KeyError, TypeError):
            continue
        if by:
            out.append((at if at.tzinfo else at.replace(tzinfo=UTC), by))
    return sorted(out, key=lambda x: x[0])


def attach_askers(rows: list[dict], asked: list[tuple[datetime, str]]) -> list[dict]:
    """Each history row with ``asked_by``: the person whose request came before the run was recorded, within the window (plus the run's own length); None for a run nobody asked for from the
    page (one started on the server). A request is put down to one run only: the first recorded after it. Pure."""
    left = list(asked)
    by_row: dict[int, str | None] = {}
    order = sorted(range(len(rows)), key=lambda i: rows[i]["at"])  # oldest run first, so an early request is not taken by a later run
    for i in order:
        row = rows[i]
        try:
            done = datetime.strptime(row["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except (ValueError, KeyError):
            by_row[i] = None
            continue
        allowed = ASKED_WINDOW_SECONDS + int(row.get("seconds") or 0)
        match = next((k for k, (at, _) in enumerate(left) if at <= done and (done - at).total_seconds() <= allowed), None)
        by_row[i] = left.pop(match)[1] if match is not None else None
    return [{**row, "asked_by": by_row.get(i)} for i, row in enumerate(rows)]


_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")


def read_changes(directory: Path, commit: str | None) -> list[str]:
    """The titles of the commits an update to ``commit`` installed, as the update script wrote them: at most twenty, each one line of printable text cut to 200 characters. Nothing when the
    commit is not a plain hash (it becomes a file name), when there is no such file, or when it cannot be read."""
    if not commit or not _COMMIT.match(commit):
        return []
    try:
        lines = (directory / CHANGES_DIR / f"{commit}.txt").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[str] = []
    for line in lines:
        clean = "".join(ch for ch in line if ch.isprintable()).strip()[:CHANGE_MAX]
        if clean:
            out.append(clean)
        if len(out) == CHANGES_SHOWN:
            break
    return out


def attach_changes(rows: list[dict], directory: Path) -> list[dict]:
    """Each history row gains ``changes``: what that run installed. Only a run that updated and passed (status ok) brought something; a health check, a roll back or a failed run lists nothing."""
    for row in rows:
        row["changes"] = read_changes(directory, row.get("commit")) if row.get("status") == "ok" else []
    return rows

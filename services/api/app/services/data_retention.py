"""What the platform keeps, and for how long, in plain words: the one answer to a client's "how long do you keep my data".

Built from the live settings, so it cannot drift from what the sweepers actually do. Each line says what is kept, for how long, and what ends it (a sweeper that deletes, a rule that only sets aside, or
nothing). A line is never softer than the setting: "kept until deleted by hand" is said when nothing deletes it.
"""

from __future__ import annotations

from typing import Any


def _days(n: int) -> str:
    return f"{n} day" + ("" if n == 1 else "s")


def retention_lines(settings: Any) -> list[dict[str, str]]:
    sweeper_on = bool(getattr(settings, "RETENTION_SWEEPER_ENABLED", True))
    dry = bool(getattr(settings, "RETENTION_DRY_RUN", False))
    sweeper_note = (
        ""
        if sweeper_on and not dry
        else (
            " The cleaner is switched off, so nothing is deleted."
            if not sweeper_on
            else " The cleaner is in count-only mode, so nothing is deleted yet."
        )
    )
    alert_days = int(getattr(settings, "RETENTION_ALERTS_DAYS", 0) or 0)
    stale_days = int(getattr(settings, "ALERT_STALE_DAYS", 0) or 0)
    posture_days = int(getattr(settings, "RETENTION_POSTURE_HISTORY_DAYS", 0) or 0)

    def line(what: str, kept: str, ends: str) -> dict[str, str]:
        return {"what": what, "kept": kept, "ends": ends}

    return [
        line(
            "Alerts",
            "Kept until deleted by hand" if alert_days <= 0 else f"Finished alerts with no case are deleted after {_days(alert_days)}",
            "Nothing deletes alerts automatically."
            if alert_days <= 0
            else "Open, in-progress and case-linked alerts are never deleted." + sweeper_note,
        ),
        line(
            "Stale alerts",
            "Set aside, never deleted" if stale_days > 0 else "Not set aside (the setting is off)",
            f"An alert nobody touched for {_days(stale_days)} (not critical or high, in no case) moves to the Stale list for review."
            if stale_days > 0
            else "Quiet alerts stay open.",
        ),
        line("Cases and investigations", "Kept until deleted by hand", "Nothing deletes cases automatically."),
        line(
            "Check and count history (security checks, licence counts, scores)",
            "Kept for ever" if posture_days <= 0 else f"{_days(posture_days)}",
            "The current checks and counts are never deleted; only the history of how they changed is." + sweeper_note
            if posture_days > 0
            else "Nothing deletes it automatically.",
        ),
        line(
            "Copilot conversations",
            _days(int(getattr(settings, "RETENTION_COPILOT_CONVERSATIONS_DAYS", 90))),
            "Deleted after this long without activity." + sweeper_note,
        ),
        line(
            "Detection suggestions",
            _days(int(getattr(settings, "RETENTION_DETECTION_SUGGESTIONS_DAYS", 180))),
            "Deleted after this long." + sweeper_note,
        ),
        line(
            "Finished response actions",
            f"{_days(int(getattr(settings, 'RETENTION_RESPONSE_ACTIONS_DEFAULT_DAYS', 730)))} unless the client set its own",
            "Only finished actions are deleted; pending, approved and running ones never are." + sweeper_note,
        ),
        line("Raw events (the data lake)", "90 days", "Expires on its own in the event store."),
        line(
            "Sent e-mail log (alert e-mails)",
            _days(int(getattr(settings, "ALERT_EMAIL_LOG_RETENTION_DAYS", 90))),
            "Older entries are removed.",
        ),
        line("Audit trail", "Kept until deleted by hand", "It records who changed what, so nothing deletes it automatically."),
    ]

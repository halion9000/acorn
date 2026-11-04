"""An alert from a finished BEC search, when CIPP itself rates the person's mailbox and sign-in trail High or Medium.

CIPP computes the rating on its side (Score.Value and Score.Level in the finished report, from weighted signals such as new inbox rules, mailbox permission changes, malicious apps and foreign sign-ins; see
CIPP-API's Get-CIPPBecScore). This only READS that rating: nothing here decides a person is compromised, and a Low or missing rating raises nothing (and is never worded as "clean"). The alert names the signals
that are present in the report by counting its own lists, and the collectors that could not finish, because a rating built on a search that could not look is weaker than it reads.

One alert per search (the key is the case), so a result that arrives twice makes one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.services.identity_detections import Finding

RULE_ID = "aisoc-id-bec-findings"
RULE_NAME = "BEC search found signs of compromise"

# The report's own lists that are signs when they are not empty, with how each is worded for a person. Only lists CIPP's scoring reads are named here.
SIGNALS: list[tuple[str, str]] = [
    ("NewRules", "new inbox rule"),
    ("InboxRuleChanges", "inbox rule change"),
    ("MailboxPermissionChanges", "mailbox permission change"),
    ("AddedApps", "added app"),
    ("MaliciousSPs", "app matching a known malicious app"),
    ("NewUsers", "new user"),
    ("SafelistChanges", "safe-sender list change"),
]

LEVEL_SEVERITY = {"high": "high", "medium": "medium"}


def _plural(n: int, word: str) -> str:
    """"1 new inbox rule", "3 new inbox rules"."""
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def signal_counts(report: dict[str, Any] | None) -> list[tuple[str, int]]:
    """(wording, count) for each of the report's signal lists that holds something. A section that is not a list is not counted."""
    out: list[tuple[str, int]] = []
    for key, word in SIGNALS:
        value = (report or {}).get(key)
        if isinstance(value, list) and value:
            out.append((word, len(value)))
    return out


def finding_for_case(*, case_ref: str, case_id: str, email: str, summary: dict[str, Any], report: dict[str, Any] | None, now: datetime | None = None) -> Finding | None:
    """The alert for a finished search, or None when CIPP's level is not High or Medium (or is not there)."""
    level = str(summary.get("level") or "").strip()
    severity = LEVEL_SEVERITY.get(level.lower())
    if severity is None:
        return None
    score = summary.get("score") if isinstance(summary.get("score"), int | float) and not isinstance(summary.get("score"), bool) else None
    raw = summary.get("incomplete")
    incomplete = [x for x in raw if isinstance(x, str)][:12] if isinstance(raw, list) else []
    signals = signal_counts(report)
    found = "; ".join(_plural(n, w) for w, n in signals) if signals else "none of the lists CIPP's score reads has an entry (the rating came from other signals, see the report)"
    fields = [("Search", case_ref), ("CIPP's level", level), ("CIPP's score", str(score) if score is not None else "not given"), ("Seen in the report", found)]
    if incomplete:
        fields.append(("Checks that could not finish", ", ".join(incomplete)))
    when = now or datetime.now(UTC)
    return Finding(
        rule_id=RULE_ID,
        rule_name=RULE_NAME,
        title=f"BEC search for {email}: CIPP rates it {level}",
        severity=severity,
        tactic="Collection",
        technique="T1114",
        key=case_id,
        occurred_at=when,
        summary=(
            f"CIPP searched {email}'s mailbox and sign-in trail and rated what it found {level}. This is CIPP's own rating of what it could see in its window; read the report on the Identities page before acting. "
            + ("Some checks could not finish, so the picture may be incomplete. " if incomplete else "")
            + "If the signs are real: end the sessions, block sign-in, reset the password from a clean machine, and remove what should not be there."
        ),
        fields=fields,
        users=[email],
    )

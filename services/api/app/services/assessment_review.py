"""Suggested answers to the assessment questions of the vCIO Toolbox review template (see ``assessment_questions``), from the checks A.C.O.R.N already holds for the client.

A question is answered only where a check the platform already runs speaks to it, and the answer says which check and what it saw. A status means the practice is in place as the template wants it
(``met``), partly, or not. Everything else is ``needs_person``: nobody can read a UPS's run time or a Google Chat setting from the tools connected today, and this never guesses. A person's typed
answer is laid over these (``review_overrides.merge_assess``). Nothing here is sent to vCIO Toolbox. Pure functions over simple values, so every rule is testable without a database.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.services.assessment_questions import QUESTIONS

_STATUSES = {"met", "partly", "not_met"}


class AssessAnswer(BaseModel):
    sheet: str
    group: str
    question: str
    # met / partly / not_met from a check; needs_person when nothing A.C.O.R.N runs answers it; not_applicable when a person says it does not apply.
    status: str
    evidence: str = ""
    # A person's typed status or note (see review_overrides). ``manual``: the status was typed, replacing what A.C.O.R.N worked out, which is kept in ``auto_status``.
    manual: bool = False
    note: str | None = None
    auto_status: str | None = None
    updated_at: datetime | None = None


# Question (or the start of it, when it is the only one that starts that way) -> the checks that answer it, in order of preference. The first one the client has wins.
CHECK_ANSWERS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("Are all Windows Desktop Operating systems installed 10 or 11 Professional?", ("ninjaone_unsupported_os",), "Windows machines, servers and workstations together"),
    ("Are all servers running currently supported versions of their respective Vendor Operating System?", ("ninjaone_unsupported_os",), "Windows machines, servers and workstations together"),
    ("Are Windows Updates for security patches configured and enabled?", ("ninjaone_patching",), "Windows machines"),
    ("Are all workstations up to the latest service pack and updates for their respective OS?", ("ninjaone_patching",), "Windows machines, servers and workstations together"),
    ("Has a managed endpoint security been deployed to protect against virus, malware, and host intrusion", ("huntress_protection", "ninjaone_antivirus"), ""),
    ("Are all firm-issued Windows Laptops encrypted?", ("liongard_disk_encryption",), ""),
    ("Are all users up to date on their training?", ("sat_training_completion",), ""),
    ("Are users clicking on phishing emails?", ("sat_phishing_simulation",), ""),
    ("Are test restores performed regularly?", ("slide_verification",), ""),
    ("Are backups (either incremental or full) scheduled to run on mission-critical systems daily?", ("slide_alerts", "liongard_datto_bcdr"), ""),
    ("Do you ensure that DKIM is enabled for all mail enabled domains", ("liongard_email_domain_records",), ""),
    ("Do you ensure the SPF record is configured for all mail enabled domains", ("liongard_email_domain_records",), ""),
    ("Do you ensure the DMARC record is configured for all mail enabled domains", ("threatmate_dmarc", "liongard_email_domain_records"), ""),
)

_RDP_QUESTION = "Is the Public port 3389 (Remote Desktop) exposed allowing remote access to servers and/or desktops?"
_EXPOSURE_CHECK = "threatmate_external_exposure"


def _question(prefix: str) -> str:
    found = [q for _s, _g, q in QUESTIONS if q == prefix] or [q for _s, _g, q in QUESTIONS if q.startswith(prefix)]
    if len(found) != 1:
        raise ValueError(f"{prefix!r} matches {len(found)} assessment questions")
    return found[0]


def _usable(check: dict[str, Any] | None) -> bool:
    return isinstance(check, dict) and check.get("status") in _STATUSES


def assessment_answers(checks: dict[str, dict[str, Any]]) -> list[AssessAnswer]:
    """One answer per template question, in the template's order. ``checks`` maps a check key to the check the client has (its ``status`` and ``evidence``)."""
    suggested: dict[str, tuple[str, str]] = {}
    for prefix, keys, scope in CHECK_ANSWERS:
        for key in keys:
            check = checks.get(key)
            if _usable(check):
                saw = str(check.get("evidence") or "").strip()  # type: ignore[union-attr]
                text = f"{scope}: {saw}" if scope and saw else saw
                suggested[_question(prefix)] = (str(check["status"]), f"From {key}. {text}".strip()[:300])  # type: ignore[index]
                break
    exposure = checks.get(_EXPOSURE_CHECK)
    if _usable(exposure):
        saw = str(exposure.get("evidence") or "").strip()  # type: ignore[union-attr]
        # Public RDP is something a clean exposure scan rules out and a finding can name; any other finding says nothing about this one question.
        if exposure["status"] == "met":  # type: ignore[index]
            suggested[_RDP_QUESTION] = ("met", f"From {_EXPOSURE_CHECK}. {saw}"[:300])
        elif "3389" in saw or "rdp" in saw.lower() or "remote desktop" in saw.lower():
            suggested[_RDP_QUESTION] = ("not_met", f"From {_EXPOSURE_CHECK}. {saw}"[:300])
    out: list[AssessAnswer] = []
    for sheet, group, question in QUESTIONS:
        status, evidence = suggested.get(question, ("needs_person", ""))
        out.append(AssessAnswer(sheet=sheet, group=group, question=question, status=status, evidence=evidence))
    return out

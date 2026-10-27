"""Guess the ATT&CK tactic of an alert whose source did not name one.

Most vendor findings (Huntress, NinjaOne, ThreatMate, Blumira, ...) arrive with no MITRE fields, so the dashboard's tactic chart had nothing to count. This reads the title for words that clearly
belong to one tactic and says nothing otherwise: an alert no rule matches is not counted, rather than put under a tactic it does not belong to. A tactic the source did name always wins over this
(see ``tactics_for``). Pure function, so every rule is testable on its own.
"""

from __future__ import annotations

import re

# (tactic, pattern), first match wins, most specific first.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (tactic, re.compile(pattern, re.IGNORECASE))
    for tactic, pattern in (
        ("Credential Access", r"credential|password|brute.?force|spray|mfa fatigue|token theft|keylog"),
        ("Initial Access", r"from new country|impossible travel|unusual (sign|log)[- ]?in|phish|unexpected country|external (rdp|exposure)|exposed (to the internet|service)"),
        ("Lateral Movement", r"lateral|pass.the.hash|psexec|remote service|\bsmb\b.*(share|relay)|\brdp\b"),
        ("Privilege Escalation", r"privilege escalation|elevat|admin role (added|granted)|added to .*admin"),
        ("Persistence", r"persist|scheduled task|startup item|autorun|run key|new (service|account) (created|installed)|inbox rule|mail forward"),
        ("Defense Evasion", r"disabled|tamper|clear(ed)? (the )?(event )?log|defender (off|disabled)|bitlocker|encryption is disabled|not installed|security (agent|software)"),
        ("Discovery", r"port scan|network scan|enumerat|discovery|reconnaissance|recon\b"),
        ("Collection", r"mailbox access|email collection|screen capture|clipboard"),
        ("Command and Control", r"command and control|\bc2\b|beacon|dns tunnel|reverse shell|tor exit"),
        ("Exfiltration", r"exfiltrat|data (leak|loss|theft)|large (upload|download)|external share|mass download"),
        ("Impact", r"ransom|file deletions?|mass delet|wiper|denial.of.service|\bdos\b|flood|crash|cpu consumption|memory leak|resource exhaustion|encrypts? files"),
        ("Execution", r"remote code execution|code execution|arbitrary code|command injection|buffer overflow|out.of.bounds|malware|trojan|powershell|macro|exploit"),
    )
)


def infer_tactic(title: str | None) -> str | None:
    """The one tactic ``title`` clearly belongs to, or ``None`` when no rule matches."""
    text = (title or "").strip()
    if not text:
        return None
    for tactic, pattern in _RULES:
        if pattern.search(text):
            return tactic
    return None


def tactics_for(stored: list | None, title: str | None) -> list[str]:
    """Tactics the source named, else the one inferred from the title, else none."""
    named = [t for t in (stored or []) if isinstance(t, str) and t]
    if named:
        return named
    guess = infer_tactic(title)
    return [guess] if guess else []

"""The risk register's pure rules: the score, its level, the starter library of common risks, and what a change to a risk is called in the history. No database here."""

from __future__ import annotations

from typing import Any

CATEGORIES = (
    "Access and identity",
    "Data protection",
    "Endpoints and devices",
    "Email and phishing",
    "Backup and recovery",
    "Vendors and third parties",
    "People",
    "Physical and environment",
    "Compliance",
    "Other",
)
TREATMENTS = ("mitigate", "accept", "transfer", "avoid", "undecided")


def score(likelihood: int | None, impact: int | None) -> int | None:
    """Likelihood times impact (1 to 25), or None when either is missing."""
    if likelihood is None or impact is None:
        return None
    return likelihood * impact


def level(value: int | None) -> str | None:
    """The word for a score: 1 to 4 low, 5 to 9 medium, 10 to 15 high, 16 to 25 critical."""
    if value is None:
        return None
    if value >= 16:
        return "critical"
    if value >= 10:
        return "high"
    if value >= 5:
        return "medium"
    return "low"


def matrix(rows: list[Any]) -> list[list[int]]:
    """A 5 by 5 grid of how many risks sit at each likelihood (row 0 = 5, the top) and impact (column 0 = 1), by their inherent rating."""
    grid = [[0] * 5 for _ in range(5)]
    for r in rows:
        grid[5 - r.likelihood][r.impact - 1] += 1
    return grid


# Common risks of a small organization that an IT provider looks after: a starting point a person adjusts, never applied on its own.
LIBRARY: tuple[dict[str, Any], ...] = (
    {
        "id": "phishing-takeover",
        "title": "A phishing email leads to a taken-over account",
        "category": "Email and phishing",
        "likelihood": 4,
        "impact": 4,
        "description": "Someone enters their password on a fake sign-in page and an attacker uses the account to read mail, send fraud or reach files.",
    },
    {
        "id": "ransomware",
        "title": "Ransomware encrypts the file servers and workstations",
        "category": "Endpoints and devices",
        "likelihood": 3,
        "impact": 5,
        "description": "Malware locks the organization's files and demands payment; work stops until systems are restored.",
    },
    {
        "id": "bec-payment-fraud",
        "title": "A fake invoice or changed bank details leads to a fraudulent payment",
        "category": "Email and phishing",
        "likelihood": 3,
        "impact": 4,
        "description": "A convincing email (often from a taken-over account) gets finance to pay the wrong account.",
    },
    {
        "id": "no-mfa",
        "title": "Accounts without multi-factor sign-in are guessed or stolen",
        "category": "Access and identity",
        "likelihood": 4,
        "impact": 4,
        "description": "A password alone protects mail, files or remote access, so a reused or leaked password is enough to get in.",
    },
    {
        "id": "lost-device",
        "title": "A lost or stolen laptop or phone exposes client or company data",
        "category": "Endpoints and devices",
        "likelihood": 3,
        "impact": 3,
        "description": "A device without disk encryption or a screen lock is taken and its data read.",
    },
    {
        "id": "unpatched-systems",
        "title": "Unpatched systems are attacked through a known flaw",
        "category": "Endpoints and devices",
        "likelihood": 3,
        "impact": 4,
        "description": "Operating systems, firewalls or applications that miss updates are exploited by an attacker or by malware.",
    },
    {
        "id": "backup-failure",
        "title": "Backups fail or cannot be restored when needed",
        "category": "Backup and recovery",
        "likelihood": 3,
        "impact": 5,
        "description": "Backup jobs stop or are never tested, so a disk failure, deletion or ransomware cannot be recovered from.",
    },
    {
        "id": "leaver-access",
        "title": "A person who left keeps access to systems or data",
        "category": "People",
        "likelihood": 3,
        "impact": 3,
        "description": "Accounts, shared passwords or devices are not removed when someone leaves, so a former employee can still sign in.",
    },
    {
        "id": "vendor-breach",
        "title": "A vendor or supplier breach exposes the organization's data",
        "category": "Vendors and third parties",
        "likelihood": 3,
        "impact": 4,
        "description": "A tool or service provider that holds company data is breached, or its access into the network is abused.",
    },
    {
        "id": "cloud-misconfig",
        "title": "A misconfigured cloud share or setting exposes data publicly",
        "category": "Data protection",
        "likelihood": 2,
        "impact": 4,
        "description": "A shared link, storage bucket or mailbox rule is left open to anyone, or forwards mail outside the organization.",
    },
    {
        "id": "insider-data-theft",
        "title": "An employee copies or removes data they should not",
        "category": "People",
        "likelihood": 2,
        "impact": 4,
        "description": "Someone with legitimate access takes client lists, files or credentials when they leave or out of spite.",
    },
    {
        "id": "single-admin",
        "title": "Only one person knows the passwords or how key systems work",
        "category": "People",
        "likelihood": 3,
        "impact": 3,
        "description": "Loss of that person (illness, resignation, an argument) leaves the organization unable to manage or recover systems.",
    },
    {
        "id": "outage",
        "title": "A power or internet outage stops work for more than a day",
        "category": "Physical and environment",
        "likelihood": 2,
        "impact": 3,
        "description": "A single internet line or no battery backup means the office or cloud tools are out of reach.",
    },
    {
        "id": "no-policies",
        "title": "Security rules are unwritten or not accepted, so they are not followed",
        "category": "Compliance",
        "likelihood": 3,
        "impact": 3,
        "description": "Without current written policies that people have accepted, practice differs by person and an auditor or insurer finds gaps.",
    },
)


def library_item(library_id: str) -> dict[str, Any] | None:
    return next((i for i in LIBRARY if i["id"] == library_id), None)


def describe_changes(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """One plain line for each field that changed, for the history ("Likelihood 3 to 4")."""
    labels = {
        "title": "Title",
        "description": "Description",
        "category": "Category",
        "owner": "Owner",
        "likelihood": "Likelihood",
        "impact": "Impact",
        "treatment": "Treatment",
        "treatment_note": "Treatment note",
        "residual_likelihood": "Residual likelihood",
        "residual_impact": "Residual impact",
    }
    out: list[str] = []
    for key, label in labels.items():
        if before.get(key) != after.get(key):
            if key in ("description", "treatment_note", "title"):
                out.append(f"{label} changed")
            else:
                out.append(
                    f"{label} {before.get(key) if before.get(key) not in (None, '') else 'none'} to {after.get(key) if after.get(key) not in (None, '') else 'none'}"
                )
    return out

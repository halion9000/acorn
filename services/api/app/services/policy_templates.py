"""Policy templates written for A.C.O.R.N, with fields that fill themselves in.

The text here is our own wording for a small managed-services organization. It is a starting point to be read and adapted, not legal advice. A policy made from a template keeps the fields as written (``{{client_name}}``)
in its stored text, so the fields always show today's facts: they are filled in only when the policy is shown or exported (see ``render``). Fields:

* ``{{client_name}}``    the organization the policy belongs to
* ``{{owner}}``          the person responsible for the policy (set on the policy)
* ``{{version}}``        the version number being shown
* ``{{last_updated}}``   the date that version was saved
* ``{{review_date}}``    the date the policy is next due for review
* ``{{date}}``           today's date
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

FIELDS = ("client_name", "owner", "version", "last_updated", "review_date", "date")
_FIELD = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")

HEADER = """# {title}

Organization: {{client_name}}
Policy owner: {{owner}}
Version {{version}}, last updated {{last_updated}}. Next review: {{review_date}}.

"""


@dataclass(frozen=True)
class Template:
    key: str
    title: str
    summary: str
    interval_days: int
    body: str


def _t(key: str, title: str, summary: str, body: str, interval_days: int = 365) -> Template:
    return Template(
        key=key, title=title, summary=summary, interval_days=interval_days, body=HEADER.replace("{title}", title) + body.strip() + "\n"
    )


TEMPLATES: tuple[Template, ...] = (
    _t(
        "information-security",
        "Information Security Policy",
        "The top-level statement of how {{client_name}} protects its information and who is responsible.",
        """
## Purpose
This policy sets out how {{client_name}} protects the confidentiality, integrity and availability of the information it holds and the systems that process it.

## Scope
It applies to everyone who works for {{client_name}} (employees, contractors and temporary staff) and to every system, device and service used to do the organization's work.

## Principles
1. Information is protected in proportion to its value and the harm its loss would cause.
2. People are given the access they need to do their job and no more.
3. Risks are identified, recorded in the risk register, assigned an owner and treated or accepted on purpose.
4. Security events are reported at once and handled under the Incident Response Policy.
5. Third parties that handle our information are reviewed before use and on a schedule.

## Responsibilities
- Leadership approves this policy, provides the resources to follow it and reviews it at least once a year.
- The policy owner ({{owner}}) keeps it current and reports on how well it is followed.
- Everyone follows it, completes security training and reports anything that looks wrong.

## Exceptions and enforcement
An exception needs a written reason, a named approver and an end date. Breaking this policy can lead to loss of access and, where it applies, disciplinary action.

## Review
This policy is reviewed by {{review_date}} and whenever something significant changes.
""",
    ),
    _t(
        "acceptable-use",
        "Acceptable Use Policy",
        "What people may and may not do with company devices, accounts and data.",
        """
## Purpose
To make clear how {{client_name}}'s devices, accounts, networks and data may be used.

## Using company systems
- Use company systems for work. Limited personal use is fine if it does not put information at risk or get in the way of work.
- Keep your devices up to date, locked when you step away, and encrypted. Do not turn off security software.
- Use only approved applications and services for company data. Do not store company data in personal accounts.

## Accounts and passwords
- Each person uses their own account. Never share a password or sign-in code.
- Use multi-factor sign-in wherever it is offered. Use a password manager.

## Email, web and messages
- Be careful with links and attachments. Report anything suspicious using the report button or to {{owner}}.
- Do not send sensitive information through channels that are not approved for it.

## Not allowed
Illegal activity, harassment, bypassing security controls, installing unlicensed software, and accessing information you have no need to see.

## Monitoring
{{client_name}} may monitor the use of its systems for security and to keep them working, as the law allows.

## Review
Reviewed by {{review_date}}.
""",
    ),
    _t(
        "access-control",
        "Access Control Policy",
        "Who gets access to what, how it is granted, reviewed and removed.",
        """
## Purpose
To make sure only the right people have access to {{client_name}}'s systems and data, for only as long as they need it.

## Rules
1. **Least privilege.** Access is given for the job a person does, and no more.
2. **Approval.** Access to a system is requested and approved by the system's owner or the person's manager. The approval is recorded.
3. **Unique accounts.** Every person has their own account. Shared and generic accounts are avoided, and where unavoidable have a named owner.
4. **Multi-factor sign-in** is required for email, remote access, administrator accounts and any system holding sensitive data.
5. **Administrator access** is held in a separate account used only for administration.
6. **Joiners, movers, leavers.** Access is set up on the first day, changed when a role changes and removed on the last day, or sooner if a person leaves under difficult circumstances.
7. **Access reviews.** Access to every important system is reviewed at least every quarter. Anything no longer needed is removed and the review is recorded.

## Records
Requests, approvals, removals and reviews are kept as evidence for at least one year.

## Review
This policy is reviewed by {{review_date}}. Owner: {{owner}}.
""",
    ),
    _t(
        "incident-response",
        "Incident Response Policy",
        "How {{client_name}} finds, handles and learns from security incidents.",
        """
## Purpose
To make sure security incidents at {{client_name}} are found quickly, handled in a consistent way and learned from.

## What counts as an incident
Any event that threatens the confidentiality, integrity or availability of information or systems: a taken-over account, malware, lost or stolen device, data sent to the wrong person, or an attack on a service.

## Reporting
Anyone who sees or suspects an incident reports it at once to {{owner}} or the service desk. Nobody is blamed for a report made in good faith.

## Handling
1. **Detect and record.** Open a record with the time, who reported it and what was seen.
2. **Assess.** Decide how serious it is and who must be told.
3. **Contain.** Stop it spreading: disable the account, isolate the device, block the sender.
4. **Remove and recover.** Remove the cause, restore from known good state, check nothing was missed.
5. **Notify.** Tell the people and organizations the law or a contract requires, within the time required.
6. **Learn.** Within two weeks of closing, review what happened, what worked and what to change.

## Evidence
Keep the records, logs and decisions for each incident for at least one year.

## Testing
The process is tested at least once a year with a practice exercise.

## Review
Reviewed by {{review_date}} and after every serious incident.
""",
    ),
    _t(
        "vendor-management",
        "Vendor Management Policy",
        "How third parties are chosen, reviewed and ended.",
        """
## Purpose
To make sure the third parties {{client_name}} depends on, or that handle its information, are chosen with care and watched over time.

## Rules
1. **Register.** Every vendor is listed in the vendor register with what it provides, who owns the relationship and the data it can reach.
2. **Risk level.** Each vendor is given a risk level (low, medium, high or critical) based on the data it can reach and how much the business depends on it.
3. **Before use.** For medium risk and above, review the vendor's security evidence (a SOC 2 report, ISO 27001 certificate or a security questionnaire) before it is used.
4. **Contract.** Contracts say how the vendor protects information, how it tells us about incidents and what happens to our data when the contract ends.
5. **Reviews.** Vendors are reviewed on a schedule: high and critical every year, medium every two years. A review records what was checked and what it found.
6. **Ending.** When a vendor is no longer used, access is removed and our data is returned or deleted.

## Responsibilities
{{owner}} keeps the register and the review schedule. Vendor owners carry out the reviews.

## Review
This policy is reviewed by {{review_date}}.
""",
    ),
    _t(
        "backup-and-recovery",
        "Backup and Disaster Recovery Policy",
        "How data is backed up and how {{client_name}} recovers from a serious outage.",
        """
## Purpose
To make sure {{client_name}} can recover its important information and services after data loss, an outage or a disaster.

## Backups
- Important systems and data are backed up automatically on a schedule that matches how much loss the business can accept.
- Backups are kept in a separate place from the original, protected from deletion by a single account, and encrypted.
- Backups are monitored. A failed backup is fixed within one working day.

## Recovery testing
A restore is tested at least once a year for each important system, and the result is recorded: what was restored, how long it took and what was learned.

## Disaster recovery
- A list of the important systems, in the order they are brought back, is kept up to date, with who does what.
- The target for how quickly each is brought back, and how much recent data may be lost, is written down and agreed.
- The plan is practiced at least once a year and updated afterwards.

## Responsibilities
{{owner}} owns this policy and reports on backup health and test results.

## Review
Reviewed by {{review_date}}.
""",
    ),
)

BY_KEY = {t.key: t for t in TEMPLATES}


def render(body: str, fields: dict[str, Any]) -> str:
    """The text with each known field filled in (pure). A field with no value, and a name that is not a field, stay as written so a gap is visible, never silently empty."""

    def fill(m: re.Match[str]) -> str:
        value = fields.get(m.group(1))
        return str(value) if m.group(1) in FIELDS and value not in (None, "") else m.group(0)

    return _FIELD.sub(fill, body)


def field_values(client_name: str, owner: str, version: int, last_updated: date, review_date: date, today: date) -> dict[str, Any]:
    return {
        "client_name": client_name,
        "owner": owner,
        "version": version,
        "last_updated": last_updated.isoformat(),
        "review_date": review_date.isoformat(),
        "date": today.isoformat(),
    }


def fields_used(body: str) -> list[str]:
    """The fields a text uses, in the order they first appear (pure)."""
    seen: list[str] = []
    for m in _FIELD.finditer(body):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen

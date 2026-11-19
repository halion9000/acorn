"""The employee toolbox (roadmap rw-toolbox, from the Rewst Tool Portal): the Microsoft 365 actions a technician can ask for, as a catalog, and the check of a request (pure).

STAGE 1: a press only creates an approval request. Nothing runs against a client's tenant here; running an approved request through CIPP is a later stage, built with the rules CORE already holds for CIPP
actions (opted-in clients, protected accounts, an hourly cap, an audit file). The catalog says what each tool needs and how risky it is, so the approver sees the same words the technician pressed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

USER = ("user", "User (email address)")


@dataclass(frozen=True)
class Tool:
    id: str
    group: str
    label: str
    risk: str  # low, medium, high
    reversible: bool
    summary: str
    fields: tuple[tuple[str, str], ...] = field(default_factory=lambda: (USER,))


GROUPS = ("User management", "Password and security", "Mail and permissions")

TOOLS: tuple[Tool, ...] = (
    Tool("group_membership", "User management", "Change group membership", "medium", True, "Add a person to a group, or take them out.", (USER, ("group", "Group name"), ("change", "add or remove"))),
    Tool("onedrive_permissions", "User management", "Give access to someone's OneDrive", "medium", True, "Let another person open this person's OneDrive.", (USER, ("grantee", "Who gets access (email address)"))),
    Tool("user_attributes", "User management", "Change a person's details", "low", True, "Change job title, department, manager or phone number.", (USER, ("attribute", "Which detail"), ("value", "New value"))),
    Tool("onboard_user", "User management", "Onboard a new person", "medium", True, "Create the account, set the license, add the groups and mailbox for a new hire.", (USER, ("name", "Full name"), ("license", "License to assign"), ("groups", "Groups to join, separated by commas"))),
    Tool("offboard_user", "User management", "Offboard a person", "high", False, "Block sign-in, remove sessions, convert the mailbox, remove licenses and groups, and pass the data on.", (USER, ("manager", "Who receives the mailbox and files (email address)"), ("when", "Date and time to do it"))),
    Tool("change_password", "Password and security", "Change a password", "medium", False, "Set a new temporary password and require a change at next sign-in.", (USER,)),
    Tool("compromised_user", "Password and security", "Remediate a compromised user", "high", False, "Reset the password, end all sessions, reset MFA and remove inbox rules and forwarding.", (USER, ("reason", "What happened"))),
    Tool("reset_mfa", "Password and security", "Reset a person's MFA", "high", False, "Remove their registered methods so they set MFA up again.", (USER, ("reason", "Why"))),
    Tool("out_of_office", "Mail and permissions", "Set an out of office reply", "low", True, "Turn the automatic reply on or off with the text to send.", (USER, ("message", "Reply text"), ("until", "Until when"))),
    Tool("mailbox_permissions", "Mail and permissions", "Give access to a mailbox", "medium", True, "Full access or send-as on a mailbox.", (USER, ("grantee", "Who gets access (email address)"), ("level", "Full access or send as"))),
    Tool("mail_forwarding", "Mail and permissions", "Forward a person's mail", "high", True, "Forward their mail to another address.", (USER, ("to", "Forward to (email address)"), ("keep_copy", "Keep a copy: yes or no"))),
    Tool("shared_mailbox", "Mail and permissions", "Create or change a shared mailbox", "medium", True, "Create a shared mailbox or change who can use it.", (("mailbox", "Shared mailbox (email address)"), ("members", "Members, separated by commas"))),
    Tool("litigation_hold", "Mail and permissions", "Put a mailbox on litigation hold", "high", True, "Keep everything in the mailbox, including deleted items.", (USER, ("reason", "Why"))),
    Tool("calendar_permissions", "Mail and permissions", "Give access to a calendar", "low", True, "Let another person see or edit a calendar.", (USER, ("grantee", "Who gets access (email address)"), ("level", "Viewer or editor"))),
)

BY_ID = {t.id: t for t in TOOLS}
MAX_VALUE = 500


def catalog() -> list[dict[str, Any]]:
    """The tools as plain data for the page, in groups."""
    return [
        {"id": t.id, "group": t.group, "label": t.label, "risk": t.risk, "reversible": t.reversible, "summary": t.summary, "fields": [{"key": k, "label": lbl} for k, lbl in t.fields]}
        for t in TOOLS
    ]


def check_request(tool_id: str, args: dict[str, Any]) -> tuple[Tool | None, dict[str, str], str | None]:
    """The tool, the cleaned arguments and a reason the request cannot be made (pure). Every field the tool asks for must be given; a value is text of at most ``MAX_VALUE`` characters; an email field must look like one; nothing extra is kept."""
    tool = BY_ID.get(tool_id)
    if tool is None:
        return None, {}, "That tool does not exist."
    clean: dict[str, str] = {}
    for key, label in tool.fields:
        raw = args.get(key)
        value = str(raw).strip() if raw is not None else ""
        if not value:
            return tool, {}, f"{label} is needed."
        if len(value) > MAX_VALUE:
            return tool, {}, f"{label} is too long."
        if key in ("user", "grantee", "manager", "to", "mailbox") and ("@" not in value or " " in value):
            return tool, {}, f"{label} must be an email address."
        clean[key] = value
    return tool, clean, None


def approval_text(tool: Tool, client: str, args: dict[str, str]) -> tuple[str, str]:
    """The title and summary of the approval card: what is asked, for whom, with every value shown (the approver decides on exactly this)."""
    who = args.get("user") or args.get("mailbox") or ""
    title = f"{tool.label}: {who}" if who else tool.label
    lines = [f"{tool.summary} Client: {client}."] + [f"{label}: {args[key]}" for key, label in tool.fields if key in args]
    lines.append("Reversible." if tool.reversible else "Not easily reversed.")
    return title[:200], "\n".join(lines)

"""The employee toolbox (roadmap rw-toolbox, from the Rewst Tool Portal): the Microsoft 365 actions a technician can ask for, as a catalog, and the check of a request (pure).

STAGE 1: a press only creates an approval request. Nothing runs against a client's tenant here; running an approved request through CIPP is a later stage, built with the rules CORE already holds for CIPP
actions (opted-in clients, protected accounts, an hourly cap, an audit file). The catalog says what each tool needs and how risky it is, so the approver sees the same words the technician pressed.

Every field has a kind, so the page offers the right control and the server checks the same thing: ``user`` and ``email`` are picked from the client's own Microsoft 365 people (``email`` also takes an address
that is not on the list, for example an outside forwarding address), ``users`` is several of those, ``choice`` is one of a fixed list, ``domain`` is one of the client's own sign-in domains, ``datetime`` is a date
and time, ``text`` and ``longtext`` are the few things only a person can say (a reason, a message). ``group`` is picked from the client's own groups (CORE reads them through CIPP) and ``rules`` is some of one
person's inbox rules, one name per line, picked from the list CORE reads for that person.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

MAX_VALUE = 500
MAX_PEOPLE = 20
EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
PERSON_KINDS = ("user", "email")
KINDS = ("user", "email", "users", "choice", "domain", "datetime", "text", "longtext", "group", "rules", "ticket", "secret")
MIN_SECRET, MAX_SECRET = 8, 128
MAX_RULES = 30
MAX_RULES_CHARS = 4000


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str = "text"
    options: tuple[str, ...] = ()
    required: bool = True
    hint: str = ""
    default: str = ""


@dataclass(frozen=True)
class Tool:
    id: str
    group: str
    label: str
    risk: str  # low, medium, high
    reversible: bool
    summary: str
    fields: tuple[Field, ...] = field(default_factory=tuple)


USER = Field("user", "Person", "user")
YES_NO = ("Yes", "No")
GROUPS = ("User management", "Password and security", "Mail and permissions")

_TOOLS: tuple[Tool, ...] = (
    Tool("group_membership", "User management", "Change group membership", "medium", True, "Add a person to a group, or take them out.", (USER, Field("change", "What to do", "choice", ("Add to the group", "Remove from the group")), Field("group", "Group", "group", hint="Pick from the client's groups. If the list does not load, type the name exactly as it shows in Microsoft Entra."))),
    Tool("onedrive_permissions", "User management", "Give access to someone's OneDrive", "medium", True, "Let another person open this person's OneDrive.", (Field("user", "Whose OneDrive", "user"), Field("grantee", "Who gets access", "user"))),
    Tool(
        "user_attributes",
        "User management",
        "Change a person's details",
        "low",
        True,
        "Change job title, department, manager, office or phone number.",
        (USER, Field("attribute", "Which detail", "choice", ("Job title", "Department", "Manager", "Office location", "Mobile phone", "Business phone", "Company name")), Field("value", "New value", "text", hint="For Manager, give the manager's email address.")),
    ),
    Tool(
        "onboard_user",
        "User management",
        "Onboard a new person",
        "medium",
        True,
        "Create the Microsoft 365 account with a generated password, then give the new hire the license, groups and shared mailboxes asked for. The fields follow Rewst's Microsoft: User Onboarding workflow.",
        (
            Field("first_name", "First name", "text"),
            Field("middle_name", "Middle name or initial", "text", required=False),
            Field("last_name", "Last name", "text"),
            Field("username_format", "Username format", "choice", ("first.last", "flast", "firstl", "first"), required=False, hint="Blank: the client's usual format."),
            Field("email_domain", "Email domain", "domain"),
            Field("job_title", "Job title", "text", required=False),
            Field("department", "Department", "text", required=False),
            Field("supervisor", "Supervisor or manager", "user", required=False),
            Field("employee_id", "Employee ID", "text", required=False),
            Field("mobile_phone", "Mobile phone", "text", required=False),
            Field("office_location", "Office or location", "text", required=False),
            Field("usage_location", "Usage location", "choice", ("United States", "Canada", "Mexico", "United Kingdom"), required=False, hint="Needed before a license can be assigned. Blank: the client's usual."),
            Field("copy_from", "Same license and groups as", "user", required=False, hint="Pick someone with the same job. Their license, groups and Teams are copied."),
            Field("shared_mailboxes", "Shared mailbox access", "users", required=False),
            Field("shared_mailbox_access", "Kind of shared mailbox access", "choice", ("Full access, shows up in Outlook", "Full access, not added to Outlook", "Full access and send as", "Full access and send on behalf"), required=False),
            Field("hide_from_gal", "Hide from the address list", "choice", YES_NO, required=False, hint="Blank means No."),
            Field("vip", "VIP", "choice", YES_NO, required=False, hint="Blank means No."),
            Field("force_password_change", "Require a password change at first sign-in", "choice", YES_NO, required=False, hint="Blank: the client's usual."),
            Field("password_to", "Who receives the password", "choice", ("The supervisor", "The new hire's mobile phone", "The ticket only"), required=False),
            Field("start_date", "Employee start date", "datetime", hint="Used for the client's lead-time check."),
            Field("account_creation", "Create the account at", "datetime", required=False, hint="Blank: as soon as it is approved."),
            Field("requestor", "Requested by", "user", required=False),
            Field("ticket_id", "Existing ticket number", "text", required=False, hint="Blank: a new ticket is opened."),
            Field("notes", "Anything else", "longtext", required=False, hint="For example a license or group the copied person does not have, or hardware to order."),
        ),
    ),
    Tool(
        "offboard_user",
        "User management",
        "Offboard a person",
        "high",
        False,
        "Reset the password, block sign-in and end sessions, then handle the mailbox, files, license, groups and devices as chosen below. The fields follow Rewst's Microsoft: User Offboarding workflow.",
        (
            USER,
            Field("when", "Do it at", "datetime", required=False, hint="Blank: as soon as it is approved."),
            Field("supervisor", "Supervisor or manager", "user", required=False, hint="Told when it is done."),
            Field("convert_to_shared", "Convert the mailbox to a shared mailbox", "choice", YES_NO, required=False, hint="Blank means No."),
            Field("mailbox_access", "Who gets access to the mailbox", "users", required=False),
            Field("forward_to", "Forward new mail to", "email", required=False),
            Field("keep_copy", "Keep a copy of forwarded mail in the mailbox", "choice", YES_NO, required=False, hint="Blank means No."),
            Field("onedrive_to", "Give access to the OneDrive files to", "user", required=False),
            Field("internal_reply", "Automatic reply to people inside", "longtext", required=False),
            Field("external_reply", "Automatic reply to people outside", "longtext", required=False),
            Field("remove_licenses", "Remove licenses", "choice", YES_NO, required=False, hint="Blank means No."),
            Field("remove_groups", "Remove from all groups", "choice", YES_NO, required=False, hint="Blank means No."),
            Field("remove_mobile_devices", "Remove mobile devices from the account", "choice", YES_NO, required=False, hint="Blank means No."),
            Field("reset_mfa", "Reset recovery and MFA methods", "choice", YES_NO, required=False, hint="Blank means No."),
            Field("hide_from_gal", "Hide from the address list", "choice", YES_NO, required=False, hint="Blank means No."),
            Field("disable_psa_contact", "Disable the contact in the ticket system", "choice", YES_NO, required=False, hint="Blank means No."),
            Field("approver", "Approver", "user", required=False, hint="Who confirms it before it runs."),
        ),
    ),
    Tool(
        "change_password",
        "Password and security",
        "Change a password",
        "medium",
        False,
        "Set a new password for the person and, if asked, make them change it at their next sign-in. The fields follow Rewst's Change Password form.",
        (
            USER,
            Field("entra_override", "User Entra override", "email", required=False, hint="Only for hybrid environments that are not synced, where the person's username in Entra differs from on-prem."),
            Field("require_change", "Require a password change at next sign-in", "choice", YES_NO, default="Yes"),
            Field("password", "Password", "secret", hint="CIPP cannot set a chosen password yet: when this runs CIPP creates the password and CORE writes it into the ticket. What is typed here is not sent anywhere."),
        ),
    ),
    Tool("compromised_user", "Password and security", "Remediate a compromised user", "high", False, "Reset the password, end all sessions, reset MFA and remove inbox rules and forwarding.", (USER, Field("reason", "What happened", "longtext"))),
    Tool("reset_mfa", "Password and security", "Reset a person's MFA", "high", False, "Remove their registered methods so they set MFA up again.", (USER, Field("reason", "Why", "text"))),
    Tool("out_of_office", "Mail and permissions", "Set an out of office reply", "low", True, "Turn the automatic reply on with the text to send.", (USER, Field("message", "Reply text", "longtext"), Field("until", "Until", "datetime"))),
    Tool("mailbox_permissions", "Mail and permissions", "Give access to a mailbox", "medium", True, "Full access, send as or send on behalf on a mailbox.", (Field("user", "Mailbox", "user"), Field("grantee", "Who gets access", "user"), Field("level", "Kind of access", "choice", ("Full access", "Send as", "Send on behalf")))),
    Tool("mail_forwarding", "Mail and permissions", "Forward a person's mail", "high", True, "Forward their mail to another address.", (USER, Field("to", "Forward to", "email", hint="Pick a person, or type an outside address."), Field("keep_copy", "Keep a copy in the mailbox", "choice", YES_NO))),
    Tool(
        "remove_inbox_rules",
        "Mail and permissions",
        "Remove bad inbox rules",
        "medium",
        False,
        "Remove only the inbox rules chosen, such as one that forwards mail outside the client, deletes mail or hides it in a folder. Pick the person to see their rules.",
        (Field("user", "Mailbox", "user"), Field("rules", "Rules to remove", "rules", hint="Rules that forward outside the client, delete mail or move it to a quiet folder are ticked for you."), Field("reason", "Why", "text", required=False)),
    ),
    Tool("shared_mailbox", "Mail and permissions", "Convert a mailbox to a shared mailbox", "medium", True, "Make the mailbox shared (no license needed) and say who can use it.", (Field("user", "Mailbox", "user"), Field("members", "Who can use it", "users", required=False))),
    Tool("litigation_hold", "Mail and permissions", "Put a mailbox on litigation hold", "high", True, "Keep everything in the mailbox, including deleted items.", (Field("user", "Mailbox", "user"), Field("length", "For how long", "choice", ("Until released", "90 days", "180 days", "1 year", "7 years")), Field("reason", "Why", "text"))),
    Tool("calendar_permissions", "Mail and permissions", "Give access to a calendar", "low", True, "Let another person see or edit a calendar.", (Field("user", "Whose calendar", "user"), Field("grantee", "Who gets access", "user"), Field("level", "Kind of access", "choice", ("Free and busy times only", "Reviewer (see details)", "Editor (change items)")))),
)

# Every tool takes a ticket number first: an existing one to write the work into, or none, and a new ticket is opened when the request runs (Hal: all Toolbox items).
TICKET = Field("ticket", "Ticket number", "ticket", required=False, hint="An existing ticket to write the work into. Leave it empty and a new ticket is opened when this runs.")
TOOLS: tuple[Tool, ...] = tuple(replace(t, fields=(TICKET, *t.fields)) for t in _TOOLS)
BY_ID = {t.id: t for t in TOOLS}


def catalog() -> list[dict[str, Any]]:
    """The tools as plain data for the page, in groups."""
    return [
        {
            "id": t.id,
            "group": t.group,
            "label": t.label,
            "risk": t.risk,
            "reversible": t.reversible,
            "summary": t.summary,
            "fields": [{"key": f.key, "label": f.label, "kind": f.kind, "options": list(f.options), "required": f.required, "hint": f.hint, "default": f.default} for f in t.fields],
        }
        for t in TOOLS
    ]


def _check_value(f: Field, value: str) -> str | None:
    """Why this value does not fit its field's kind, or None when it does."""
    if f.kind in PERSON_KINDS and not EMAIL.match(value):
        return f"{f.label} must be an email address."
    if f.kind == "users":
        people = [p.strip() for p in re.split(r"[,;]", value) if p.strip()]
        if len(people) > MAX_PEOPLE:
            return f"{f.label} has too many people (at most {MAX_PEOPLE})."
        if not people or not all(EMAIL.match(p) for p in people):
            return f"{f.label} must be email addresses."
    if f.kind == "choice" and value not in f.options:
        return f"{f.label} must be one of: {', '.join(f.options)}."
    if f.kind == "domain" and not re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", value):
        return f"{f.label} must be a domain name."
    if f.kind == "ticket" and not re.match(r"^[0-9]{1,12}$", value):
        return f"{f.label} must be the number of an existing ticket."
    if f.kind == "secret" and not (MIN_SECRET <= len(value) <= MAX_SECRET):
        return f"{f.label} must be between {MIN_SECRET} and {MAX_SECRET} characters."
    if f.kind == "rules":
        names = [n.strip() for n in value.splitlines() if n.strip()]
        if not names or len(names) > MAX_RULES or any(len(n) > 160 for n in names):
            return f"{f.label}: pick between 1 and {MAX_RULES} rules."
    if f.kind == "datetime":
        try:
            datetime.fromisoformat(value)
        except ValueError:
            return f"{f.label} must be a date and time."
    return None


def check_request(tool_id: str, args: dict[str, Any]) -> tuple[Tool | None, dict[str, str], str | None]:
    """The tool, the cleaned arguments and a reason the request cannot be made (pure). A required field must be given; a value is text of at most ``MAX_VALUE`` characters that fits its kind (an email address,
    one of the listed choices, a date and time); an optional field left empty is dropped; nothing extra is kept."""
    tool = BY_ID.get(tool_id)
    if tool is None:
        return None, {}, "That tool does not exist."
    clean: dict[str, str] = {}
    for f in tool.fields:
        raw = args.get(f.key)
        value = str(raw).strip() if raw is not None else ""
        if not value and f.default:
            value = f.default
        if not value:
            if f.required:
                return tool, {}, f"{f.label} is needed."
            continue
        if len(value) > (MAX_RULES_CHARS if f.kind == "rules" else MAX_VALUE):
            return tool, {}, f"{f.label} is too long."
        why = _check_value(f, value)
        if why:
            return tool, {}, why
        clean[f.key] = value
    return tool, clean, None


def approval_text(tool: Tool, client: str, args: dict[str, str]) -> tuple[str, str]:
    """The title and summary of the approval card: what is asked, for whom, with every value shown (the approver decides on exactly this)."""
    who = args.get("user") or (f"{args['first_name']} {args['last_name']}" if "first_name" in args else "")
    title = f"{tool.label}: {who}" if who else tool.label
    lines = [f"{tool.summary} Client: {client}."] + [f"{f.label}: {'set (hidden)' if f.kind == 'secret' else args[f.key].replace(chr(10), '; ')}" for f in tool.fields if f.key in args]
    if not args.get("ticket"):
        lines.append("No ticket was given: a new ticket is opened when this runs.")
    lines.append("Reversible." if tool.reversible else "Not easily reversed.")
    return title[:200], "\n".join(lines)


def people_and_domains(rows: list[tuple[str, str | None, bool, str | None]]) -> dict[str, Any]:
    """The picker lists from a client's Microsoft 365 user rows ``(upn, display name, enabled, user type)`` (pure): people sorted by name with members before guests, and the sign-in domains of the members, most used first."""
    people = sorted(
        ({"email": upn, "name": name or upn, "enabled": bool(enabled), "guest": (kind or "").lower() == "guest"} for upn, name, enabled, kind in rows if upn and "@" in upn),
        key=lambda p: (p["guest"], not p["enabled"], p["name"].lower()),
    )
    counts: dict[str, int] = {}
    for p in people:
        if not p["guest"]:
            d = p["email"].rsplit("@", 1)[1].lower()
            counts[d] = counts.get(d, 0) + 1
    domains = [d for d, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {"people": people, "domains": domains}


# --- Running a request ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
RUN_ACTION = "toolbox_run"
RUN_STATUS = {"pending": "waiting", "claimed": "running", "done": "done", "failed": "failed"}


def run_params(tool: Tool, client: str, args: dict[str, str], cipp: str, halo: str | None, requested_by: str | None) -> dict[str, Any]:
    """What CORE is told to run (pure): the tool, the client's CIPP customer id and HaloPSA client id, and every value except a secret (CIPP cannot take a typed password, so none is queued)."""
    secrets = {f.key for f in tool.fields if f.kind == "secret"}
    return {
        "tool": tool.id,
        "label": tool.label,
        "client": client,
        "client_id": cipp,
        **({"halo_client_id": halo} if halo else {}),
        "args": {k: v for k, v in args.items() if k not in secrets},
        "requested_by_name": (requested_by or "")[:200] or None,
    }


def present_run(row: Any, client: str | None) -> dict[str, Any]:
    """One request as the page lists it (pure): what was asked, for which client, how far it is, and what CORE said, with the ticket CORE used."""
    p = row.params or {}
    data = row.result_data or {}
    return {
        "request_id": str(row.id),
        "tool": p.get("tool"),
        "label": p.get("label") or p.get("tool"),
        "client": client or p.get("client"),
        "person": (p.get("args") or {}).get("user") or ((p.get("args") or {}).get("first_name") or ""),
        "status": RUN_STATUS.get(row.status, row.status),
        "message": row.result_message,
        "ticket": data.get("ticket") or (p.get("args") or {}).get("ticket"),
        "steps": data.get("steps") or [],
        "requested_by": p.get("requested_by_name"),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }

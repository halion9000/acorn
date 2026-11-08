"""People (e-mail identities) across the connected tools, put together per client.

A person is one e-mail address (lower case) in one client. Microsoft 365 people come from CIPP's list (``identity_mfa_users``); every other tool reports its own people into ``identity_sources``.
This puts a person's rows from all tools together, says which tools know them, works out their multi-factor state from the Microsoft 365 row, and ties alerts to them by the e-mail address the alert
names. Pure functions over simple values, so every rule is testable without a database.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.identity_merge import merge_people
from app.services.mfa_registration import has_second_factor, registration_known, required_of

MICROSOFT = "cipp"
# A tool's row not refreshed for this long is no longer shown: the person has gone from that tool.
STALE_DAYS = 3
_EMAIL = re.compile(r"^[^@\s]{1,128}@[^@\s]{1,190}\.[^@\s]{2,63}$")
_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


# The tools that back up people's mailboxes: what each says about a person is shown on their row.
BACKUP_TOOLS = ("dropsuite", "datto-saas")
# Tools that say where a person's address turned up in a breach. They describe people other tools know; an exposed address no directory knows is not made into a person.
EXPOSURE_TOOLS = ("threatmate", "liongard")
# A Dropsuite mailbox with no backup in this long is stale.
FRESH_HOURS = 48


def _when(value: Any) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def backup_infos(sources: list[SourceRef], now: datetime) -> list[BackupInfo]:
    """The backup state each backup tool reports for a person. Datto SaaS Protection says whether the seat is protected, not when it last ran; Dropsuite says when the mailbox last backed up and any error."""
    out: list[BackupInfo] = []
    for s in sources:
        d = s.details or {}
        if s.vendor == "dropsuite":
            err = d.get("errors")
            last = _when(d.get("last_backup"))
            if s.enabled is False:
                out.append(BackupInfo("dropsuite", "paused", "Mailbox deactivated in Dropsuite"))
            elif isinstance(err, int) and err > 0:
                out.append(BackupInfo("dropsuite", "issue", f"Dropsuite reports {err} error{'s' if err != 1 else ''} on this mailbox"))
            elif last is None:
                out.append(BackupInfo("dropsuite", "stale", "Dropsuite has not backed this mailbox up yet"))
            elif now - last > timedelta(hours=FRESH_HOURS):
                days = max(1, (now - last).days)
                out.append(BackupInfo("dropsuite", "stale", f"Last Dropsuite backup {days} day{'s' if days != 1 else ''} ago"))
            else:
                out.append(BackupInfo("dropsuite", "ok", "Backed up by Dropsuite in the last 48 hours"))
        elif s.vendor == "datto-saas":
            state = str(d.get("seat_state") or "").lower()
            if state == "active":
                out.append(BackupInfo("datto-saas", "ok", "Protected by Datto SaaS Protection (active seat)"))
            elif state == "paused":
                out.append(BackupInfo("datto-saas", "paused", "Datto SaaS Protection seat is paused"))
            elif state in ("unprotected", "archived"):
                out.append(BackupInfo("datto-saas", "unprotected", f"Datto SaaS Protection seat is {state}"))
            else:
                out.append(BackupInfo("datto-saas", "unprotected", "No active Datto SaaS Protection seat"))
    return out


def normalize_email(raw: Any) -> str | None:
    """The e-mail address in lower case, or None when it is not one (a bare user name or a device account)."""
    text = str(raw or "").strip().lower()
    return text if _EMAIL.match(text) else None


@dataclass
class SourceRef:
    vendor: str
    external_id: str
    enabled: bool | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class BackupInfo:
    """What one backup tool says about one person's data: ``ok``, ``stale`` (no recent backup), ``issue`` (the tool reports an error), ``paused`` or ``unprotected``."""

    vendor: str
    status: str
    detail: str


@dataclass
class Exposure:
    """Where a person's address was found in dark-web breaches: how many, the newest, and the kinds of data that leaked (never the data itself)."""

    count: int
    latest: str | None = None
    password: bool = False
    stealer_log: bool = False
    malware: bool = False
    breaches: list[dict[str, Any]] = field(default_factory=list)


def exposure_of(sources: list[Any]) -> Exposure | None:
    """The exposure the exposure tools report for one person (the worst reading wins when more than one tool reports), or None."""
    best: Exposure | None = None
    for s in sources:
        d = s.details or {}
        n = d.get("exposed_in")
        if not isinstance(n, int) or n <= 0:
            continue
        got = Exposure(
            count=n,
            latest=d.get("latest_breach") if isinstance(d.get("latest_breach"), str) else None,
            password=bool(d.get("password_exposed")),
            stealer_log=bool(d.get("stealer_log")),
            malware=bool(d.get("malware")),
            breaches=[b for b in (d.get("breaches") or []) if isinstance(b, dict)][:5],
        )
        if best is None or (got.stealer_log, got.password, got.count) > (best.stealer_log, best.password, best.count):
            best = got
    return best


@dataclass
class Person:
    tenant_id: uuid.UUID
    email: str
    client_name: str | None = None
    display_name: str | None = None
    kind: str = "user"  # user / guest / shared / other
    enabled: bool | None = None
    admin: bool = False
    licensed: bool | None = None
    mfa: str = "unknown"  # covered / registered_not_required / none / unknown
    mfa_methods: str | None = None
    sources: list[SourceRef] = field(default_factory=list)
    open_alerts: int = 0
    top_severity: str | None = None
    # Open alerts by the tool that raised them ("huntress": 2, "petra": 1); "other" when an alert names no tool.
    alerts_by_source: dict[str, int] = field(default_factory=dict)
    backups: list[BackupInfo] = field(default_factory=list)
    exposure: Exposure | None = None
    # The other addresses of the same human, folded into this person (see identity_merge), and why each was.
    aliases: list[str] = field(default_factory=list)
    alias_reasons: dict[str, str] = field(default_factory=dict)
    # How the person compares with the client's HaloPSA users (see halo_checks): "cloud_not_in_halo", "halo_inactive_cloud_enabled", or None.
    halo_check: str | None = None
    # Microsoft 365 password set never to expire: True / False, or None when CIPP's user list could not say.
    password_never_expires: bool | None = None
    # "active" / "inactive" (90+ days) / "never", or None when the client's sign-in data is not available.
    signin_state: str | None = None
    days_since_signin: int | None = None

    @property
    def key(self) -> str:
        return f"{self.tenant_id}:{self.email}"

    @property
    def addresses(self) -> list[str]:
        return [self.email, *self.aliases]

    @property
    def vendors(self) -> list[str]:
        return sorted({s.vendor for s in self.sources})


def mfa_state(user: Any, registration_is_known: bool) -> str:
    """covered: a second factor is required of them and they have one. registered_not_required: they signed up for one but nothing requires it. none: neither. (Same rules as the Multi-Factor page.)"""
    if has_second_factor(user, registration_is_known) and required_of(user):
        return "covered"
    if registration_is_known and user.registered and not required_of(user):
        return "registered_not_required"
    return "none"


def _apply_directory(p: Person, s: Any) -> None:
    """What a tool that reads the client's cloud directory (ThreatMate) says about a person, used only where Microsoft 365's own list (CIPP) says nothing: a Google Workspace user, or a Microsoft one CIPP
    does not hold. Microsoft 365's row always wins. A second factor the tool sees registered is ``registered_not_required`` (it cannot tell whether one is required); none registered is ``none``."""
    d = s.details or {}
    if p.mfa == "unknown" and isinstance(d.get("mfa_enrolled"), bool):
        p.mfa = "registered_not_required" if d["mfa_enrolled"] else "none"
    if d.get("super_admin") is True:
        p.admin = True
    if p.licensed is None and isinstance(d.get("licensed"), bool):
        p.licensed = d["licensed"]
    if p.enabled is None and s.enabled is not None:
        p.enabled = bool(s.enabled)


def build_people(
    names: dict[uuid.UUID, str],
    microsoft_users: list[Any],
    sources: list[Any],
    now: datetime,
    stale_days: int = STALE_DAYS,
    merges: list[tuple[uuid.UUID, str, str]] | None = None,
    separate: list[tuple[uuid.UUID, str, str]] | None = None,
) -> list[Person]:
    """Every person, one row each, with the tools that know them. ``microsoft_users`` are IdentityMfaUser rows and ``sources`` IdentitySource rows (anything with the same fields)."""
    people: dict[str, Person] = {}

    def person(tenant_id: uuid.UUID, email: str) -> Person:
        key = f"{tenant_id}:{email}"
        if key not in people:
            people[key] = Person(tenant_id=tenant_id, email=email, client_name=names.get(tenant_id))
        return people[key]

    by_tenant: dict[uuid.UUID, list[Any]] = {}
    for u in microsoft_users:
        by_tenant.setdefault(u.tenant_id, []).append(u)
    known = {tid: registration_known(rows) for tid, rows in by_tenant.items()}
    for u in microsoft_users:
        email = normalize_email(u.upn)
        if email is None:
            continue
        p = person(u.tenant_id, email)
        p.display_name = p.display_name or (u.display_name or None)
        p.kind = "guest" if str(u.user_type or "").lower() == "guest" else "user"
        p.enabled = bool(u.enabled)
        p.admin = bool(u.admin)
        p.licensed = bool(u.licensed)
        p.mfa = mfa_state(u, known[u.tenant_id])
        p.mfa_methods = u.methods or None
        p.password_never_expires = getattr(u, "password_never_expires", None)
        p.signin_state = getattr(u, "signin_state", None)
        p.days_since_signin = getattr(u, "days_since_signin", None)
        p.sources.append(
            SourceRef(
                vendor=MICROSOFT,
                external_id=str(u.user_id),
                enabled=bool(u.enabled),
                details={"licensed": bool(u.licensed), "admin": bool(u.admin)},
            )
        )

    cutoff = now - timedelta(days=stale_days)
    exposure_rows: dict[str, list[Any]] = {}
    for s in sources:
        email = normalize_email(s.email)
        refreshed = s.refreshed_at if s.refreshed_at.tzinfo else s.refreshed_at.replace(tzinfo=now.tzinfo)
        if email is None or refreshed < cutoff:
            continue
        if s.vendor in EXPOSURE_TOOLS:
            exposure_rows.setdefault(f"{s.tenant_id}:{email}", []).append(s)
            # ThreatMate also reads the client's cloud directory (Microsoft 365 and Google Workspace). A row that says it came from one is a person the tool really holds, so it makes the person (an exposed
            # address no directory knows still does not).
            if not (s.details or {}).get("directory"):
                continue
        p = person(s.tenant_id, email)
        p.display_name = p.display_name or (s.display_name or None)
        if p.kind == "user" and s.kind in ("shared", "guest", "other"):
            p.kind = s.kind
        if s.enabled is False and p.enabled is None:
            p.enabled = False
        p.sources.append(SourceRef(vendor=s.vendor, external_id=s.external_id, enabled=s.enabled, details=dict(s.details or {})))
        if (s.details or {}).get("directory"):
            _apply_directory(p, s)
    # One human, one person: fold the addresses that are the same human (the rules and the owner's own merges are in identity_merge).
    out = merge_people(people, merges, separate)
    for p in out:
        p.sources.sort(key=lambda r: (r.vendor != MICROSOFT, r.vendor, r.external_id))
        p.backups = backup_infos(p.sources, now)
        p.exposure = exposure_of([row for address in p.addresses for row in exposure_rows.get(f"{p.tenant_id}:{address}", [])])
    halo_checks(out)
    return out


HALO = "halopsa"
HALO_CHECKS = ("cloud_not_in_halo", "halo_inactive_cloud_enabled")


# Addresses that belong to a thing or a team, not a person: nobody is added to HaloPSA as a user for these. Matched on the part before the @, split into words at . _ - + (whole words only, so
# "scanlon" is not "scan"), plus a few fragments that are distinctive enough to match inside a word ("xmdreports", "gshake-admin", "itadmin").
ROLE_WORDS = frozenset(
    "info information scan scans scanner scopier support helpdesk help sales billing accounting accounts payable receivable payroll hr service services backup alerts alert notifications notification noreply "
    "donotreply postmaster webmaster office contact mail team front reception security orders order marketing store shop test testing it admin admins administrator scanning printer print copier copy fax "
    "ricoh xerox konica kyocera canon epson brother lexmark".split()
)
ROLE_FRAGMENTS = ("copier", "report", "admin", "noreply", "no-reply", "donotreply")


def looks_like_role_account(emails: list[str], display_name: str | None = None) -> bool:
    """True for a shared or function address (info@, scan@, a copier, a reports sender, an admin account), judged by the address and, when the display name is a single such word, by that (pure)."""
    for email in emails:
        local = email.split("@", 1)[0].lower()
        words = [w for w in re.split(r"[._\-+]+", local) if w]
        if any(w in ROLE_WORDS for w in words) or any(f in local for f in ROLE_FRAGMENTS):
            return True
    if display_name:
        name_words = [w for w in re.split(r"[^a-z]+", display_name.lower()) if w]
        if len(name_words) <= 2 and any(w in ROLE_WORDS or any(f in w for f in ROLE_FRAGMENTS) for w in name_words):
            return True
    return False


def halo_checks(people: list[Person]) -> None:
    """Compare each person's cloud account (Microsoft 365, or a directory ThreatMate reads) with the client's HaloPSA users, and set ``halo_check`` on the ones that need a look. Only judged for a client whose HaloPSA users
    we hold at all (otherwise every account would read as missing), and only for ordinary users: a guest, a shared mailbox or another kind of account is not expected to be a Halo user.
    - cloud_not_in_halo: an enabled cloud account that no HaloPSA user matches (by the person's address or one of their aliases).
    - halo_inactive_cloud_enabled: HaloPSA marks the person inactive (left, or never to return) but the cloud account is still enabled.
    It only points: nothing is changed, and an unmatched account may well be a service or shared account nobody has labelled (pure)."""
    with_halo = {p.tenant_id for p in people if any(s.vendor == HALO for s in p.sources)}
    for p in people:
        p.halo_check = None
        if p.tenant_id not in with_halo or p.kind != "user":
            continue
        cloud = [s for s in p.sources if s.vendor == MICROSOFT or (s.details or {}).get("directory")]
        if not cloud or p.enabled is False or not any(s.enabled is not False for s in cloud):
            continue
        halo = [s for s in p.sources if s.vendor == HALO]
        if not halo:
            # A function address (info@, scan@, a copier, an admin account) is not someone to add to Halo, so it is not listed as missing.
            if not looks_like_role_account(list(p.addresses) or [p.email], p.display_name):
                p.halo_check = "cloud_not_in_halo"
        elif all(s.enabled is False for s in halo):
            p.halo_check = "halo_inactive_cloud_enabled"


# The managed detection and response tools: none lists its people to us, but each says who a threat is about. A person one of them raised an alert about is a person that tool is watching.
ALERT_TOOLS = frozenset({"huntress", "petra", "fieldeffect", "blumira"})


def address_index(people: list[Person]) -> dict[str, Person]:
    """Every address of every person (the shown one and the folded-in aliases), as "client:address", to its person."""
    index: dict[str, Person] = {}
    for p in people:
        for address in p.addresses:
            index[f"{p.tenant_id}:{address}"] = p
    return index


def add_alert_sources(
    people: list[Person], alerts: list[Any], names: dict[uuid.UUID, str], source_of: Any, tools: frozenset[str] = ALERT_TOOLS
) -> list[Person]:
    """Add each MDR tool that raised an alert naming a person to that person's tools (creating the person when no other tool knows them). Returns the people, with any new ones added."""
    index = address_index(people)
    out = list(people)
    for a in alerts:
        tool = source_of(a.raw_event, getattr(a, "connector_type", None))
        if tool not in tools:
            continue
        for raw in a.affected_users if isinstance(a.affected_users, list) else []:
            addr = normalize_email(raw)
            if addr is None:
                continue
            key = f"{a.tenant_id}:{addr}"
            p = index.get(key)
            if p is None:
                p = Person(tenant_id=a.tenant_id, email=addr, client_name=names.get(a.tenant_id))
                index[key] = p
                out.append(p)
            if not any(s.vendor == tool for s in p.sources):
                p.sources.append(SourceRef(vendor=tool, external_id="alert", details={"via": "an alert it raised"}))
    for p in out:
        p.sources.sort(key=lambda r: (r.vendor != MICROSOFT, r.vendor, r.external_id))
    return out


def attach_alerts(people: list[Person], alerts: list[Any], source_of: Any = None) -> dict[str, list[Any]]:
    """Tie open alerts to the people they name (by e-mail address, same client). Sets each person's count and highest severity; returns the alerts by person key, newest first."""
    index = address_index(people)
    by_person = {p.key: p for p in people}
    by_key: dict[str, list[Any]] = {}
    for a in alerts:
        seen: set[str] = set()
        for raw in a.affected_users if isinstance(a.affected_users, list) else []:
            email = normalize_email(raw)
            who = index.get(f"{a.tenant_id}:{email}") if email else None
            # An alert that names two addresses of the same human counts once for that person.
            if who is not None and who.key not in seen:
                seen.add(who.key)
                by_key.setdefault(who.key, []).append(a)
    for key, rows in by_key.items():
        rows.sort(key=lambda a: a.created_at, reverse=True)
        p = by_person[key]
        p.open_alerts = len(rows)
        counts: dict[str, int] = {}
        for a in rows:
            tool = (source_of(a.raw_event, getattr(a, "connector_type", None)) if source_of else None) or "other"
            counts[tool] = counts.get(tool, 0) + 1
        p.alerts_by_source = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
        p.top_severity = max((str(a.severity).lower() for a in rows), key=lambda s: _SEVERITY_RANK.get(s, -1))
    return by_key


def is_active(p: Person) -> bool:
    """An active identity: a person with a LICENSED account (Microsoft 365 or Google), who is not a guest and whose account is not disabled. Unknown is not enough: an account no tool says is licensed is not counted,
    and an account that only some tool leaves silent about (enabled unknown) is not called disabled."""
    return p.licensed is True and p.kind != "guest" and p.enabled is not False


def never_expires(p: "Person") -> bool:
    """Whether the tile counts this person: a working (not disabled) account of the organization's own (not a guest) whose password CIPP says never expires. Unknown is never counted (pure)."""
    return p.password_never_expires is True and p.enabled is not False and p.kind != "guest"


def counts_as(p: "Person", state: str) -> bool:
    """Whether the inactive or never-signed-in tile counts this person: a working (not disabled), own (not guest) account whose sign-in state is known to be ``state`` ("inactive" or "never"). Unknown is never counted (pure)."""
    return p.signin_state == state and p.enabled is not False and p.kind != "guest"


def filter_people(
    people: list[Person],
    *,
    search: str | None = None,
    source: str | None = None,
    has_alerts: bool = False,
    mfa: str | None = None,
    admin: bool = False,
    disabled: bool = False,
    enabled: bool = False,
    kind: str | None = None,
    only_in: str | None = None,
    alert_source: str | None = None,
    backup: str | None = None,
    exposed: str | None = None,
    active: bool = False,
    halo_check: str | None = None,
    password_never_expires: bool = False,
    inactivity: str | None = None,
) -> list[Person]:
    """The people a page asked for: every filter given must hold. ``only_in`` keeps people known to just that one tool."""
    rows = people
    if search:
        needle = search.strip().lower()
        rows = [
            p
            for p in rows
            if any(needle in address for address in p.addresses)
            or needle in (p.display_name or "").lower()
            or needle in (p.client_name or "").lower()
        ]
    if source:
        rows = [p for p in rows if source in p.vendors]
    if only_in:
        rows = [p for p in rows if p.vendors == [only_in]]
    if has_alerts:
        rows = [p for p in rows if p.open_alerts > 0]
    if halo_check:
        rows = [p for p in rows if p.halo_check == halo_check]
    if backup == "ok":
        rows = [p for p in rows if p.backups and all(b.status == "ok" for b in p.backups)]
    elif backup == "problem":
        # A disabled account is not a backup problem: nobody signs in to it, so an unprotected or stale mailbox is not something to fix (the tile counts the same way).
        rows = [p for p in rows if p.enabled is not False and any(b.status != "ok" for b in p.backups)]
    elif backup == "none":
        rows = [p for p in rows if not p.backups]
    if exposed == "any":
        rows = [p for p in rows if p.exposure is not None]
    elif exposed == "serious":
        rows = [p for p in rows if p.exposure is not None and (p.exposure.password or p.exposure.stealer_log or p.exposure.malware)]
    if alert_source:
        rows = [p for p in rows if p.alerts_by_source.get(alert_source, 0) > 0]
    if mfa:
        # "No multi-factor" leaves out disabled accounts, as the tile does: a blocked account cannot be signed in to, with or without a second factor.
        rows = [p for p in rows if p.mfa == mfa and not (mfa == "none" and p.enabled is False)]
    if password_never_expires:
        rows = [p for p in rows if never_expires(p)]
    if inactivity:
        rows = [p for p in rows if counts_as(p, inactivity)]
    if admin:
        rows = [p for p in rows if p.admin]
    if disabled:
        rows = [p for p in rows if p.enabled is False]
    if enabled:
        # Every account that is not known to be disabled: an account whose tools say nothing about it is not called disabled.
        rows = [p for p in rows if p.enabled is not False]
    if kind:
        rows = [p for p in rows if p.kind == kind]
    if active:
        rows = [p for p in rows if is_active(p)]
    return rows


SORTS = ("alerts", "email", "name", "client", "tools", "exposure")


def sort_people(people: list[Person], by: str = "alerts") -> list[Person]:
    """Most alerts first by default (then the most serious), or by e-mail, name, client or number of tools."""
    if by == "email":
        return sorted(people, key=lambda p: p.email)
    if by == "name":
        return sorted(people, key=lambda p: ((p.display_name or "~").lower(), p.email))
    if by == "client":
        return sorted(people, key=lambda p: ((p.client_name or "").lower(), p.email))
    if by == "tools":
        return sorted(people, key=lambda p: (-len(p.vendors), p.email))
    if by == "exposure":
        return sorted(people, key=lambda p: (-(p.exposure.count if p.exposure else 0), p.email))
    return sorted(people, key=lambda p: (-p.open_alerts, -_SEVERITY_RANK.get(p.top_severity or "", -1), p.email))

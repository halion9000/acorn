"""Alerts from the sign-ins and directory audit entries CORE collects through CIPP.

Until now these were stored and scored for unusual behaviour but nothing alerted on them. These rules read what is already stored and raise an alert when a pattern is clear:

- ``rare_country``: a successful sign-in from a country nobody in the client's tenant has signed in from in the last 45 days (judged only once the tenant has at least 50 sign-ins of history).
- ``impossible_travel``: the same person signed in successfully, interactively, from two countries within an hour.
- ``failed_after_revoke``: three or more failed sign-ins by a person in the two hours after their sessions were revoked.
- ``password_spray``: five or more people failing a password from one address within an hour.
- ``mfa_fatigue``: five or more failed or unanswered multi-factor prompts for one person within an hour.
- ``guessed_password``: a success right after five or more wrong passwords for the same person within an hour.
- ``risky_signin``: Microsoft's own medium or high risk rating on a successful sign-in.
- ``legacy_protocol``: a successful sign-in over IMAP, POP, SMTP, ActiveSync or "other clients", which cannot ask for multi-factor.
- ``admin_security_info``: an administrator registered, changed or removed a person's sign-in methods.
- ``app_consent``: consent or a delegated permission was given to an application.
- ``app_credentials``: a secret or certificate was added to an application.
- ``mass_deletion``: ten or more users or groups deleted by one actor within fifteen minutes.
- ``privileged_role_change``: someone was added to a directory role.
- ``ca_policy_change``: a Conditional Access policy was added, changed or deleted.

The detectors are pure functions over rows (anything with the same attributes as ``SigninEvent`` / ``DirectoryAuditEvent``), so each rule is tested without a database. An alert has a fixed id built from
the client and the finding, so seeing the same thing again (or the same batch twice) never raises a second alert.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("aisoc.identity_detections")

_NAMESPACE = uuid.UUID("5f0f1c55-6d7f-4a54-9f7e-1d0b7a3c9a11")
BASELINE_DAYS = 45
BASELINE_MIN_SIGNINS = 50
TRAVEL_WINDOW = timedelta(hours=1)
REVOKE_WINDOW = timedelta(hours=2)
REVOKE_FAILURES = 3
MASS_DELETE_COUNT = 10
MASS_DELETE_WINDOW = timedelta(minutes=15)
SPRAY_PEOPLE = 5  # distinct people failing from one address within an hour
FATIGUE_PROMPTS = 5  # refused or unanswered multi-factor prompts for one person within an hour
GUESS_FAILURES = 5  # wrong passwords before a success counts as a guessed one
# Microsoft's own error codes: a wrong password, an account locked by too many tries, and a multi-factor request that failed.
WRONG_PASSWORD = {50126, 50053}
MFA_FAILED = {500121, 50074, 50076}
# What Microsoft calls the older protocols that cannot do multi-factor.
LEGACY_CLIENTS = {"imap4", "pop3", "smtp", "authenticated smtp", "exchange activesync", "other clients"}

_PRIORITY = {"critical": 95, "high": 80, "medium": 55, "low": 30, "info": 10}


@dataclass
class Finding:
    rule_id: str
    rule_name: str
    title: str
    severity: str
    tactic: str
    technique: str
    key: str  # what makes this finding the same finding next time
    occurred_at: datetime
    summary: str
    fields: list[tuple[str, str]] = field(default_factory=list)
    users: list[str] = field(default_factory=list)
    ips: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)


def _utc(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _stamp(t: datetime) -> str:
    return _utc(t).strftime("%Y-%m-%d %H:%M UTC")


# ---- sign-in rules ---------------------------------------------------------------------------------------------------------------------------------------


def detect_rare_country(new: list[Any], baseline_countries: set[str], baseline_total: int) -> list[Finding]:
    """A successful interactive sign-in from a country the tenant has not been seen in; one finding per person and country."""
    if baseline_total < BASELINE_MIN_SIGNINS:
        return []
    out: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for r in sorted(new, key=lambda x: _utc(x.occurred_at)):
        country = (r.country or "").strip()
        if not r.success or not r.interactive or not country or country in baseline_countries or (r.user_principal, country) in seen:
            continue
        seen.add((r.user_principal, country))
        no_mfa = r.mfa is False
        out.append(
            Finding(
                rule_id="aisoc-id-rare-country",
                rule_name="Sign-in from a country this client rarely sees",
                title=f"Sign-in from an unusual country - {country}",
                severity="high" if no_mfa else "medium",
                tactic="Initial Access",
                technique="T1078",
                key=f"rare-country:{r.user_principal}:{country}",
                occurred_at=r.occurred_at,
                summary=f"{r.user_principal} signed in from {country}, which nobody at this client has signed in from in the last {BASELINE_DAYS} days.",
                fields=[
                    ("Person", r.user_principal),
                    ("Country", country),
                    ("City", r.city or "unknown"),
                    ("Address", r.ip_address or "unknown"),
                    ("App", r.app or "unknown"),
                    ("Multi-factor", "not used" if no_mfa else "used" if r.mfa else "unknown"),
                    ("Time", _stamp(r.occurred_at)),
                ],
                users=[r.user_principal],
                ips=[r.ip_address] if r.ip_address else [],
                source_ids=[r.source_id],
            )
        )
    return out


def detect_impossible_travel(rows: list[Any], new_ids: set[str]) -> list[Finding]:
    """Two successful interactive sign-ins by one person from different countries within an hour. ``rows`` hold the new sign-ins and the person's recent earlier ones; a pair is only judged when its later
    sign-in is new, so an old pair is never raised again."""
    by_user: dict[str, list[Any]] = defaultdict(list)
    for r in rows:
        if r.success and r.interactive and r.country:
            by_user[r.user_principal].append(r)
    out: list[Finding] = []
    for user, items in by_user.items():
        items.sort(key=lambda x: _utc(x.occurred_at))
        for earlier, later in zip(items, items[1:], strict=False):
            if later.source_id not in new_ids or earlier.country == later.country:
                continue
            gap = _utc(later.occurred_at) - _utc(earlier.occurred_at)
            if gap > TRAVEL_WINDOW:
                continue
            minutes = int(gap.total_seconds() // 60)
            out.append(
                Finding(
                    rule_id="aisoc-id-impossible-travel",
                    rule_name="Impossible travel",
                    title=f"Impossible travel - {earlier.country} to {later.country}",
                    severity="high",
                    tactic="Initial Access",
                    technique="T1078",
                    key=f"travel:{user}:{later.source_id}",
                    occurred_at=later.occurred_at,
                    summary=f"{user} signed in from {earlier.country} and {minutes} minutes later from {later.country}. A VPN can cause this; confirm with the person.",
                    fields=[
                        ("Person", user),
                        (
                            "First",
                            f"{earlier.country} ({earlier.city or 'unknown city'}), {earlier.ip_address or 'unknown address'}, {_stamp(earlier.occurred_at)}",
                        ),
                        (
                            "Second",
                            f"{later.country} ({later.city or 'unknown city'}), {later.ip_address or 'unknown address'}, {_stamp(later.occurred_at)}",
                        ),
                        ("Minutes apart", str(minutes)),
                    ],
                    users=[user],
                    ips=[ip for ip in (earlier.ip_address, later.ip_address) if ip],
                    source_ids=[earlier.source_id, later.source_id],
                )
            )
    return out


def detect_device_code(new: list[Any]) -> list[Finding]:
    """A successful sign-in made with the device-code flow. Attackers phish with it (the person is talked into typing a code on Microsoft's own page and the attacker is handed a token), so every one is
    worth a look; a person setting up a meeting-room device or a command-line tool does it too. One finding per sign-in."""
    out: list[Finding] = []
    for r in sorted(new, key=lambda x: _utc(x.occurred_at)):
        protocol = (getattr(r, "auth_protocol", None) or "").lower()
        transfer = (getattr(r, "transfer_method", None) or "").lower()
        if not r.success or (protocol != "devicecode" and transfer != "devicecodeflow"):
            continue
        resource = getattr(r, "resource", None)
        out.append(
            Finding(
                rule_id="aisoc-id-device-code",
                rule_name="Sign-in with a device code",
                title=f"Device-code sign-in - {r.user_principal}",
                severity="high" if r.mfa is False else "medium",
                tactic="Initial Access",
                technique="T1078",
                key=f"device-code:{r.user_principal}:{r.source_id}",
                occurred_at=r.occurred_at,
                summary=f"{r.user_principal} signed in with a device code. Attackers phish people into approving one; confirm with the person that they started it (setting up a device or a tool is the usual innocent reason).",
                fields=[
                    ("Person", r.user_principal),
                    ("App", r.app or "unknown"),
                    ("Service", resource or "unknown"),
                    ("Country", r.country or "unknown"),
                    ("Address", r.ip_address or "unknown"),
                    ("Multi-factor", "not used" if r.mfa is False else "used" if r.mfa else "unknown"),
                    ("Time", _stamp(r.occurred_at)),
                ],
                users=[r.user_principal],
                ips=[r.ip_address] if r.ip_address else [],
                source_ids=[r.source_id],
            )
        )
    return out


def detect_risky_signin(new: list[Any]) -> list[Finding]:
    """A successful sign-in that Microsoft itself scored as medium or high risk (only tenants whose licence shows the score send one). Microsoft's own judgement, so it is worth a look even when no other rule fires."""
    out: list[Finding] = []
    for r in sorted(new, key=lambda x: _utc(x.occurred_at)):
        risk = (getattr(r, "risk", None) or "").lower()
        if not r.success or risk not in ("medium", "high"):
            continue
        out.append(
            Finding(
                rule_id="aisoc-id-risky-signin",
                rule_name="Microsoft rated a sign-in as risky",
                title=f"{risk.capitalize()}-risk sign-in - {r.user_principal}",
                severity="high" if risk == "high" else "medium",
                tactic="Initial Access",
                technique="T1078",
                key=f"risky:{r.user_principal}:{r.source_id}",
                occurred_at=r.occurred_at,
                summary=f"Microsoft rated a successful sign-in by {r.user_principal} as {risk} risk. Confirm with the person that it was them.",
                fields=[
                    ("Person", r.user_principal),
                    ("Risk", risk),
                    ("App", r.app or "unknown"),
                    ("Country", r.country or "unknown"),
                    ("Address", r.ip_address or "unknown"),
                    ("Multi-factor", "not used" if r.mfa is False else "used" if r.mfa else "unknown"),
                    ("Time", _stamp(r.occurred_at)),
                ],
                users=[r.user_principal],
                ips=[r.ip_address] if r.ip_address else [],
                source_ids=[r.source_id],
            )
        )
    return out


def _hour(t: datetime) -> str:
    return _utc(t).strftime("%Y%m%d%H")


def detect_password_spray(rows: list[Any], new_ids: set[str]) -> list[Finding]:
    """Five or more different people failing a password from one address in the same clock hour. One finding per address and hour; the batch must contain at least one new failure so an old hour is never raised again."""
    buckets: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for r in rows:
        if not r.success and r.error_code in WRONG_PASSWORD and r.ip_address:
            buckets[(r.ip_address, _hour(r.occurred_at))].append(r)
    out: list[Finding] = []
    for (ip, hour), items in buckets.items():
        people = sorted({i.user_principal for i in items})
        if len(people) < SPRAY_PEOPLE or not any(i.source_id in new_ids for i in items):
            continue
        first = min(items, key=lambda x: _utc(x.occurred_at))
        out.append(
            Finding(
                rule_id="aisoc-id-password-spray",
                rule_name="Password spray",
                title=f"Password spray from {ip} - {len(people)} people",
                severity="high",
                tactic="Credential Access",
                technique="T1110.003",
                key=f"spray:{ip}:{hour}",
                occurred_at=first.occurred_at,
                summary=f"{len(people)} different people failed a password from {ip} within the same hour: someone is trying one password against many accounts.",
                fields=[
                    ("Address", ip),
                    ("Country", first.country or "unknown"),
                    ("People", ", ".join(people[:10]) + (" ..." if len(people) > 10 else "")),
                    ("Failures", str(len(items))),
                    ("First", _stamp(first.occurred_at)),
                ],
                users=people[:25],
                ips=[ip],
                source_ids=[i.source_id for i in items][:50],
            )
        )
    return out


def detect_mfa_fatigue(rows: list[Any], new_ids: set[str]) -> list[Finding]:
    """Five or more failed multi-factor requests for one person in the same clock hour (someone who has the password keeps sending prompts hoping to be approved)."""
    buckets: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for r in rows:
        if not r.success and r.error_code in MFA_FAILED:
            buckets[(r.user_principal, _hour(r.occurred_at))].append(r)
    out: list[Finding] = []
    for (user, hour), items in buckets.items():
        if len(items) < FATIGUE_PROMPTS or not any(i.source_id in new_ids for i in items):
            continue
        first = min(items, key=lambda x: _utc(x.occurred_at))
        ips = sorted({i.ip_address for i in items if i.ip_address})
        out.append(
            Finding(
                rule_id="aisoc-id-mfa-fatigue",
                rule_name="Many failed multi-factor prompts",
                title=f"Repeated multi-factor prompts - {user}",
                severity="high",
                tactic="Credential Access",
                technique="T1621",
                key=f"fatigue:{user}:{hour}",
                occurred_at=first.occurred_at,
                summary=f"{user} had {len(items)} multi-factor requests that failed or went unanswered within an hour. Someone may know the password and be hoping the person approves one; ask them, and reset the password if so.",
                fields=[
                    ("Person", user),
                    ("Prompts", str(len(items))),
                    ("Addresses", ", ".join(ips[:5]) or "unknown"),
                    ("First", _stamp(first.occurred_at)),
                ],
                users=[user],
                ips=ips[:10],
                source_ids=[i.source_id for i in items][:50],
            )
        )
    return out


def detect_guessed_password(rows: list[Any], new_ids: set[str]) -> list[Finding]:
    """A new successful sign-in that follows five or more wrong passwords for the same person within the hour before it."""
    by_user: dict[str, list[Any]] = defaultdict(list)
    for r in rows:
        by_user[r.user_principal].append(r)
    out: list[Finding] = []
    for user, items in by_user.items():
        items.sort(key=lambda x: _utc(x.occurred_at))
        for r in items:
            if not r.success or r.source_id not in new_ids:
                continue
            window_start = _utc(r.occurred_at) - TRAVEL_WINDOW
            fails = [
                f
                for f in items
                if not f.success and f.error_code in WRONG_PASSWORD and window_start <= _utc(f.occurred_at) <= _utc(r.occurred_at)
            ]
            if len(fails) < GUESS_FAILURES:
                continue
            ips = sorted({f.ip_address for f in fails if f.ip_address})
            out.append(
                Finding(
                    rule_id="aisoc-id-guessed-password",
                    rule_name="Sign-in after many wrong passwords",
                    title=f"Sign-in succeeded after {len(fails)} wrong passwords - {user}",
                    severity="high",
                    tactic="Credential Access",
                    technique="T1110",
                    key=f"guessed:{user}:{r.source_id}",
                    occurred_at=r.occurred_at,
                    summary=f"{user} failed {len(fails)} password attempts within an hour and then signed in successfully. The password may have been guessed; confirm with the person.",
                    fields=[
                        ("Person", user),
                        ("Wrong passwords", str(len(fails))),
                        ("Failed from", ", ".join(ips[:5]) or "unknown"),
                        ("Signed in from", f"{r.ip_address or 'unknown'} ({r.country or 'unknown country'})"),
                        ("Multi-factor", "not used" if r.mfa is False else "used" if r.mfa else "unknown"),
                        ("Time", _stamp(r.occurred_at)),
                    ],
                    users=[user],
                    ips=[ip for ip in [*ips[:5], r.ip_address] if ip],
                    source_ids=[*(f.source_id for f in fails[:20]), r.source_id],
                )
            )
    return out


def detect_legacy_protocol(new: list[Any]) -> list[Finding]:
    """A successful sign-in over a legacy protocol (IMAP, POP, SMTP, ActiveSync, "other clients"). They cannot ask for multi-factor, so they are how a stolen password is used past it. One finding per person, app and day."""
    out: list[Finding] = []
    seen: set[str] = set()
    for r in sorted(new, key=lambda x: _utc(x.occurred_at)):
        client = (getattr(r, "client_app", None) or "").strip()
        if not r.success or client.lower() not in LEGACY_CLIENTS:
            continue
        key = f"legacy:{r.user_principal}:{client.lower()}:{_utc(r.occurred_at).strftime('%Y%m%d')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Finding(
                rule_id="aisoc-id-legacy-protocol",
                rule_name="Sign-in over a legacy protocol",
                title=f"Legacy-protocol sign-in ({client}) - {r.user_principal}",
                severity="medium",
                tactic="Defense Evasion",
                technique="T1078",
                key=key,
                occurred_at=r.occurred_at,
                summary=f"{r.user_principal} signed in with {client}, an older protocol that cannot ask for multi-factor. Block legacy authentication with a Conditional Access policy unless something here truly needs it.",
                fields=[
                    ("Person", r.user_principal),
                    ("Protocol", client),
                    ("Country", r.country or "unknown"),
                    ("Address", r.ip_address or "unknown"),
                    ("Time", _stamp(r.occurred_at)),
                ],
                users=[r.user_principal],
                ips=[r.ip_address] if r.ip_address else [],
                source_ids=[r.source_id],
            )
        )
    return out


# ---- directory audit rules ---------------------------------------------------------------------------------------------------------------------------------

_REVOKE = re.compile(r"revoke.*(session|token)|invalidate.*(session|token)", re.IGNORECASE)
_DELETE = re.compile(r"^(hard )?delete (user|group)", re.IGNORECASE)
_ROLE_ADD = re.compile(r"^add (eligible |scoped )?member to role", re.IGNORECASE)
_CA = re.compile(r"conditional access policy", re.IGNORECASE)


def detect_failed_after_revoke(audits: list[Any], signins: list[Any]) -> list[Finding]:
    """Three or more failed sign-ins by a person in the two hours after their sessions were revoked (someone is still trying to use stolen access)."""
    out: list[Finding] = []
    for a in audits:
        if not a.success or not a.target or not _REVOKE.search(a.activity or ""):
            continue
        person = a.target.lower()
        start = _utc(a.occurred_at)
        failed = [
            s for s in signins if s.user_principal == person and not s.success and start < _utc(s.occurred_at) <= start + REVOKE_WINDOW
        ]
        if len(failed) < REVOKE_FAILURES:
            continue
        ips = sorted({s.ip_address for s in failed if s.ip_address})
        out.append(
            Finding(
                rule_id="aisoc-id-failed-after-revoke",
                rule_name="Failed sign-ins after sessions were revoked",
                title="Failed sign-ins after sessions were revoked",
                severity="high",
                tactic="Credential Access",
                technique="T1110",
                key=f"revoke:{person}:{a.source_id}",
                occurred_at=failed[-1].occurred_at,
                summary=f"{person}'s sessions were revoked by {a.actor}, and the account then had {len(failed)} failed sign-ins within two hours.",
                fields=[
                    ("Person", person),
                    ("Revoked by", a.actor),
                    ("Revoked at", _stamp(a.occurred_at)),
                    ("Failed sign-ins", str(len(failed))),
                    ("From", ", ".join(ips[:5]) or "unknown"),
                ],
                users=[person],
                ips=ips[:5],
                source_ids=[a.source_id, *[s.source_id for s in failed[:5]]],
            )
        )
    return out


def detect_mass_deletion(audits: list[Any]) -> list[Finding]:
    """Ten or more users or groups deleted by one actor within fifteen minutes."""
    by_actor: dict[str, list[Any]] = defaultdict(list)
    for a in audits:
        if a.success and _DELETE.search(a.activity or ""):
            by_actor[a.actor].append(a)
    out: list[Finding] = []
    for actor, items in by_actor.items():
        items.sort(key=lambda x: _utc(x.occurred_at))
        i = 0
        while i < len(items):
            j = i
            while j + 1 < len(items) and _utc(items[j + 1].occurred_at) - _utc(items[i].occurred_at) <= MASS_DELETE_WINDOW:
                j += 1
            burst = items[i : j + 1]
            if len(burst) >= MASS_DELETE_COUNT:
                kinds = sorted({(b.target_type or "object") for b in burst})
                out.append(
                    Finding(
                        rule_id="aisoc-id-mass-deletion",
                        rule_name="Mass deletion of users or groups",
                        title=f"Mass deletion: {len(burst)} users or groups deleted",
                        severity="high",
                        tactic="Impact",
                        technique="T1485",
                        key=f"mass-delete:{actor}:{burst[0].source_id}",
                        occurred_at=burst[0].occurred_at,
                        summary=f"{actor} deleted {len(burst)} users or groups within {MASS_DELETE_WINDOW.seconds // 60} minutes.",
                        fields=[
                            ("Actor", actor),
                            ("Deleted", str(len(burst))),
                            ("Kinds", ", ".join(kinds)),
                            ("First", _stamp(burst[0].occurred_at)),
                            ("Last", _stamp(burst[-1].occurred_at)),
                        ],
                        users=[actor],
                        ips=[burst[0].actor_ip] if burst[0].actor_ip else [],
                        source_ids=[b.source_id for b in burst[:10]],
                    )
                )
                i = j + 1
            else:
                i += 1
    return out


def detect_privileged_role_change(audits: list[Any]) -> list[Finding]:
    """Someone was added to a directory role."""
    out: list[Finding] = []
    for a in audits:
        if not a.success or not _ROLE_ADD.search(a.activity or ""):
            continue
        out.append(
            Finding(
                rule_id="aisoc-id-role-change",
                rule_name="Someone was added to a directory role",
                title=f"Added to a directory role - {a.target or 'unknown'}",
                severity="high" if a.actor_is_app else "medium",
                tactic="Privilege Escalation",
                technique="T1098",
                key=f"role:{a.source_id}",
                occurred_at=a.occurred_at,
                summary=f"{a.actor} added {a.target or 'an account'} to a directory role ({a.activity}).",
                fields=[
                    ("Actor", a.actor + (" (an app)" if a.actor_is_app else "")),
                    ("Target", a.target or "unknown"),
                    ("Activity", a.activity),
                    ("Time", _stamp(a.occurred_at)),
                    ("Address", a.actor_ip or "unknown"),
                ],
                users=[u for u in (a.actor, a.target) if u],
                ips=[a.actor_ip] if a.actor_ip else [],
                source_ids=[a.source_id],
            )
        )
    return out


_SECURITY_INFO_BY_ADMIN = re.compile(r"^admin (registered|deleted|updated) security info", re.IGNORECASE)
_CONSENT = re.compile(r"^(consent to application|add delegated permission grant)", re.IGNORECASE)
_APP_CREDENTIAL = re.compile(r"(certificates and secrets management|add service principal credentials)", re.IGNORECASE)


def _audit_finding(
    a: Any,
    *,
    rule_id: str,
    rule_name: str,
    title: str,
    severity: str,
    tactic: str,
    technique: str,
    key: str,
    summary: str,
    target_label: str,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        rule_name=rule_name,
        title=title,
        severity=severity,
        tactic=tactic,
        technique=technique,
        key=key,
        occurred_at=a.occurred_at,
        summary=summary,
        fields=[
            ("Actor", a.actor + (" (an app)" if a.actor_is_app else "")),
            (target_label, a.target or "unknown"),
            ("Activity", a.activity),
            ("Time", _stamp(a.occurred_at)),
            ("Address", a.actor_ip or "unknown"),
        ],
        users=[u for u in (a.actor, a.target) if u and "@" in u],
        ips=[a.actor_ip] if a.actor_ip else [],
        source_ids=[a.source_id],
    )


def detect_security_info_changed_by_admin(audits: list[Any]) -> list[Finding]:
    """An administrator registered, changed or removed a person's sign-in methods (their phone, authenticator app...). Help desks do this when a phone is lost; an attacker with an admin account does it to keep a way in."""
    out: list[Finding] = []
    for a in audits:
        if not a.success or not _SECURITY_INFO_BY_ADMIN.search(a.activity or ""):
            continue
        verb = (a.activity or "").split()[1].lower()
        out.append(
            _audit_finding(
                a,
                rule_id="aisoc-id-admin-security-info",
                rule_name="An administrator changed a person's sign-in methods",
                title=f"Sign-in methods {verb} by an administrator - {a.target or 'unknown'}",
                severity="medium",
                tactic="Persistence",
                technique="T1556.006",
                key=f"secinfo:{a.source_id}",
                summary=f"{a.actor} {verb} sign-in methods ({a.activity}) for {a.target or 'an account'}. Expected when someone lost a phone; confirm there was a request.",
                target_label="Person",
            )
        )
    return out


def detect_app_consent(audits: list[Any]) -> list[Finding]:
    """Consent was given to an application, or a delegated permission was granted to one: the usual way a phishing app gets lasting access to mail and files."""
    out: list[Finding] = []
    for a in audits:
        if not a.success or not _CONSENT.search(a.activity or ""):
            continue
        out.append(
            _audit_finding(
                a,
                rule_id="aisoc-id-app-consent",
                rule_name="Consent was given to an application",
                title=f"Consent given to an application - {a.target or 'unknown'}",
                severity="medium",
                tactic="Persistence",
                technique="T1528",
                key=f"consent:{a.source_id}",
                summary=f"{a.actor} gave an application consent ({a.activity}). Check that the application is one the client uses; a phishing app asks for exactly this.",
                target_label="Application",
            )
        )
    return out


def detect_app_credentials_added(audits: list[Any]) -> list[Finding]:
    """A secret or certificate was added to an application or service principal: a way to keep signing in as the app after the person who added it is gone."""
    out: list[Finding] = []
    for a in audits:
        if not a.success or not _APP_CREDENTIAL.search(a.activity or "") or (a.activity or "").lower().startswith(("delete", "remove")):
            continue
        out.append(
            _audit_finding(
                a,
                rule_id="aisoc-id-app-credentials",
                rule_name="A credential was added to an application",
                title=f"Credential added to an application - {a.target or 'unknown'}",
                severity="medium",
                tactic="Persistence",
                technique="T1098.001",
                key=f"appcred:{a.source_id}",
                summary=f"{a.actor} added a secret or certificate to an application ({a.activity}). Confirm it was planned.",
                target_label="Application",
            )
        )
    return out


def detect_ca_policy_change(audits: list[Any]) -> list[Finding]:
    """A Conditional Access policy was added, changed or deleted."""
    out: list[Finding] = []
    for a in audits:
        if not a.success or not _CA.search(a.activity or ""):
            continue
        deleted = (a.activity or "").lower().startswith("delete")
        out.append(
            Finding(
                rule_id="aisoc-id-ca-policy-change",
                rule_name="A Conditional Access policy changed",
                title=f"Conditional Access policy {'deleted' if deleted else 'changed'} - {a.target or 'unknown'}",
                severity="high" if deleted else "medium",
                tactic="Defense Evasion",
                technique="T1562",
                key=f"ca:{a.source_id}",
                occurred_at=a.occurred_at,
                summary=f"{a.actor} changed a Conditional Access policy ({a.activity}).",
                fields=[
                    ("Actor", a.actor + (" (an app)" if a.actor_is_app else "")),
                    ("Policy", a.target or "unknown"),
                    ("Activity", a.activity),
                    ("Time", _stamp(a.occurred_at)),
                    ("Address", a.actor_ip or "unknown"),
                ],
                users=[a.actor],
                ips=[a.actor_ip] if a.actor_ip else [],
                source_ids=[a.source_id],
            )
        )
    return out


# ---- turning findings into alerts ---------------------------------------------------------------------------------------------------------------------------


def alert_id(tenant_id: uuid.UUID, finding: Finding) -> uuid.UUID:
    """The same client and the same finding always give the same id, so a repeat is a no-op."""
    return uuid.uuid5(_NAMESPACE, f"{tenant_id}:{finding.rule_id}:{finding.key}")


def alert_values(tenant_id: uuid.UUID, finding: Finding, now: datetime) -> dict[str, Any]:
    """The columns of the alert row for a finding."""
    lines = [finding.summary, ""] + [f"{k}: {v}" for k, v in finding.fields]
    at = _utc(finding.occurred_at)
    return {
        "id": alert_id(tenant_id, finding),
        "tenant_id": tenant_id,
        "title": finding.title[:500],
        "description": "\n".join(lines),
        "severity": finding.severity,
        "status": "new",
        "priority": _PRIORITY.get(finding.severity, 50),
        "category": "identity",
        "mitre_tactics": [finding.tactic],
        "mitre_techniques": [finding.technique],
        "connector_type": "cipp",
        "source_event_ids": finding.source_ids,
        "rule_id": finding.rule_id,
        "rule_name": finding.rule_name,
        "ai_recommendations": [],
        "affected_ips": finding.ips,
        "affected_hosts": [],
        "affected_users": finding.users,
        "affected_assets": [],
        "child_alert_ids": [],
        "is_merged": False,
        "raw_event": {
            "source": "aisoc-identity-detections",
            "finding": {"uid": f"{finding.rule_id}:{finding.key}", "title": finding.title},
        },
        "enrichment_data": {},
        "tags": ["identity", finding.rule_id],
        "event_time": at,
        "first_seen": at,
        "last_seen": at,
        "created_at": now,
        "updated_at": now,
    }


async def save_findings(db: Any, tenant_id: uuid.UUID, findings: list[Finding], now: datetime | None = None) -> int:
    """Insert an alert for each finding that has none yet; returns how many were new. Never raises: a failure here must not lose the sign-ins or audits it was triggered by."""
    if not findings:
        return 0
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models.alert import Alert

    now = now or datetime.now(UTC)
    made = 0
    try:
        async with db.begin_nested():  # a failure rolls back to here, not the whole request
            for f in findings:
                res = await db.execute(
                    pg_insert(Alert).values(**alert_values(tenant_id, f, now)).on_conflict_do_nothing(index_elements=["id"])
                )
                made += res.rowcount or 0
    except Exception:  # noqa: BLE001
        logger.warning("identity detections: saving alerts failed for tenant=%s", tenant_id, exc_info=True)
        return 0
    return made


# ---- the two entry points the ingest endpoints call -----------------------------------------------------------------------------------------------------------


async def run_signin_detections(db: Any, tenant_id: uuid.UUID, rows: list[Any], now: datetime | None = None) -> int:
    """Run the sign-in rules over a batch just stored for one client (the rows are flushed), and save the alerts. Returns how many alerts were new."""
    if not rows:
        return 0
    from sqlalchemy import func, select

    from app.models.signin import SigninEvent

    now = now or datetime.now(UTC)
    try:
        first = min(_utc(r.occurred_at) for r in rows)
        new_ids = {r.source_id for r in rows}
        base = (
            await db.execute(
                select(SigninEvent.country, func.count())
                .where(
                    SigninEvent.tenant_id == tenant_id,
                    SigninEvent.occurred_at >= first - timedelta(days=BASELINE_DAYS),
                    SigninEvent.occurred_at < first,
                    SigninEvent.success.is_(True),
                )
                .group_by(SigninEvent.country)
            )
        ).all()
        countries = {c for c, _n in base if c}
        total = sum(n for _c, n in base)
        users = {r.user_principal for r in rows}
        earlier = (
            (
                await db.execute(
                    select(SigninEvent).where(
                        SigninEvent.tenant_id == tenant_id,
                        SigninEvent.user_principal.in_(users),
                        SigninEvent.occurred_at >= first - TRAVEL_WINDOW,
                        SigninEvent.occurred_at < first,
                    )
                )
            )
            .scalars()
            .all()
        )
        findings = (
            detect_rare_country(rows, countries, total)
            + detect_impossible_travel([*earlier, *rows], new_ids)
            + detect_device_code(rows)
            + detect_legacy_protocol(rows)
            + detect_risky_signin(rows)
            + detect_password_spray([*earlier, *rows], new_ids)
            + detect_mfa_fatigue([*earlier, *rows], new_ids)
            + detect_guessed_password([*earlier, *rows], new_ids)
        )
    except Exception:  # noqa: BLE001
        logger.warning("identity detections: sign-in rules failed for tenant=%s", tenant_id, exc_info=True)
        return 0
    return await save_findings(db, tenant_id, findings, now)


async def run_audit_detections(db: Any, tenant_id: uuid.UUID, rows: list[Any], now: datetime | None = None) -> int:
    """Run the directory audit rules over a batch just stored for one client (the rows are flushed), and save the alerts. Returns how many alerts were new."""
    if not rows:
        return 0
    from sqlalchemy import select

    from app.models.signin import SigninEvent

    now = now or datetime.now(UTC)
    try:
        findings = (
            detect_mass_deletion(rows)
            + detect_privileged_role_change(rows)
            + detect_ca_policy_change(rows)
            + detect_security_info_changed_by_admin(rows)
            + detect_app_consent(rows)
            + detect_app_credentials_added(rows)
        )
        revokes = [r for r in rows if r.success and r.target and _REVOKE.search(r.activity or "")]
        if revokes:
            people = {r.target.lower() for r in revokes}
            start = min(_utc(r.occurred_at) for r in revokes)
            signins = (
                (
                    await db.execute(
                        select(SigninEvent).where(
                            SigninEvent.tenant_id == tenant_id,
                            SigninEvent.user_principal.in_(people),
                            SigninEvent.occurred_at > start,
                            SigninEvent.occurred_at <= start + REVOKE_WINDOW + timedelta(days=1),
                        )
                    )
                )
                .scalars()
                .all()
            )
            findings += detect_failed_after_revoke(revokes, list(signins))
    except Exception:  # noqa: BLE001
        logger.warning("identity detections: audit rules failed for tenant=%s", tenant_id, exc_info=True)
        return 0
    return await save_findings(db, tenant_id, findings, now)

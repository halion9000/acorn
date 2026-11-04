"""MTA-STS: whether a domain tells other mail servers to insist on an encrypted, correctly named connection when they deliver to it (RFC 8461).

Two public pieces: a DNS record ``_mta-sts.<domain>`` (``v=STSv1; id=...``) that says a policy exists, and the policy file itself at ``https://mta-sts.<domain>/.well-known/mta-sts.txt`` (mode, the mail servers it
covers, and how long senders may remember it). The file is fetched with the guarded fetch (https, public address, no redirect: the standard forbids following one) and only parsed, never followed further.

What is reported is what a person would act on: the mode (``enforce`` protects, ``testing`` only reports, ``none`` switches it off), the age senders remember it for, and above all whether the policy's server
list still covers the domain's real MX records, because an ``enforce`` policy that misses one makes senders refuse to deliver to it. Nothing is judged that could not be read: an unreachable file says so.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.services import safe_fetch
from app.services.domain_posture import Resolver

Fetcher = Callable[[str], Awaitable[bytes]]

MIN_MAX_AGE = 86_400  # under a day is too short to protect anything: senders forget it before the next message
GOOD_MAX_AGE = 604_800  # a week or more is what the standard's own guidance suggests as the starting point
MAX_POLICY_BYTES = 64_000
_MODES = ("enforce", "testing", "none")


@dataclass
class MtaSts:
    state: str  # "none" (no record), "unreadable" (record but no usable file), "ok"
    record_id: str | None = None
    mode: str | None = None
    max_age: int | None = None
    mx_patterns: list[str] = field(default_factory=list)
    uncovered_mx: list[str] = field(default_factory=list)  # real MX hosts the policy's list does not match
    issues: list[str] = field(default_factory=list)


def parse_record(txt: list[str]) -> str | None:
    """The record's id, or None when there is no single valid ``v=STSv1`` record."""
    found = [t for t in (x.strip() for x in txt) if t.lower().startswith("v=stsv1")]
    if len(found) != 1:
        return None
    for part in found[0].split(";"):
        key, _, value = part.strip().partition("=")
        if key.strip().lower() == "id" and re.fullmatch(r"[A-Za-z0-9]{1,32}", value.strip()):
            return value.strip()
    return None


def parse_policy(body: str) -> tuple[str | None, int | None, list[str], list[str]]:
    """(mode, max_age, mx patterns, problems) from the policy file's text."""
    mode: str | None = None
    max_age: int | None = None
    patterns: list[str] = []
    problems: list[str] = []
    version_ok = False
    for raw in body.replace("\r", "").split("\n"):
        line = raw.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "version":
            version_ok = value == "STSv1"
        elif key == "mode":
            mode = value.lower() if value.lower() in _MODES else None
            if mode is None:
                problems.append(f"The policy's mode is “{value[:20]}”, which is not enforce, testing or none.")
        elif key == "max_age":
            if value.isdigit() and int(value) <= 31_557_600:
                max_age = int(value)
            else:
                problems.append("The policy's max_age is not a number of seconds up to a year.")
        elif key == "mx" and value:
            patterns.append(value.lower().rstrip("."))
    if not version_ok:
        problems.append("The policy file does not start with “version: STSv1”.")
    if mode is None and not any("mode" in p for p in problems):
        problems.append("The policy file has no mode.")
    if max_age is None and not any("max_age" in p for p in problems):
        problems.append("The policy file has no max_age.")
    if mode in ("enforce", "testing") and not patterns:
        problems.append("The policy lists no mail servers (mx lines).")
    return mode, max_age, patterns, problems


def host_matches(pattern: str, host: str) -> bool:
    """A policy's ``mx`` line against a real host: exact, or ``*.example.com`` which stands for exactly one label before the rest."""
    host = host.lower().rstrip(".")
    if pattern.startswith("*."):
        suffix = pattern[1:]
        head = host[: -len(suffix)] if host.endswith(suffix) else None
        return bool(head) and "." not in head
    return pattern == host


def real_mx_hosts(mx: list[str]) -> list[str]:
    """Host names from the resolver's MX answers, which may be ``10 mail.example.com.`` or just the host."""
    out = []
    for m in mx:
        parts = m.split()
        host = parts[-1].lower().rstrip(".") if parts else ""
        if host:
            out.append(host)
    return out


async def public_fetch(url: str) -> bytes:
    return await safe_fetch.fetch(url, max_bytes=MAX_POLICY_BYTES, max_redirects=0, accept="text/plain")


async def check(domain: str, resolver: Resolver, fetch: Fetcher = public_fetch, mx: list[str] | None = None) -> MtaSts:
    """Read the domain's MTA-STS record and policy. ``mx`` is the domain's MX list when the caller already has it."""
    try:
        record = await resolver.txt(f"_mta-sts.{domain}")
    except Exception:
        return MtaSts(state="unreadable", issues=["The MTA-STS record could not be looked up just now."])
    if not any(t.strip().lower().startswith("v=stsv1") for t in record):
        return MtaSts(state="none")
    record_id = parse_record(record)
    if record_id is None:
        return MtaSts(state="unreadable", issues=["The _mta-sts record is not a single valid “v=STSv1; id=…” record."])
    try:
        body = (await fetch(f"https://mta-sts.{domain}/.well-known/mta-sts.txt")).decode("utf-8", errors="replace")
    except safe_fetch.FetchRefused as e:
        return MtaSts(state="unreadable", record_id=record_id, issues=[f"The record exists but the policy file could not be read: {e}"])
    mode, max_age, patterns, problems = parse_policy(body)
    out = MtaSts(state="ok", record_id=record_id, mode=mode, max_age=max_age, mx_patterns=patterns, issues=problems)
    hosts = real_mx_hosts(mx if mx is not None else await _safe_mx(resolver, domain))
    out.uncovered_mx = sorted(h for h in hosts if not any(host_matches(p, h) for p in patterns))
    return out


async def _safe_mx(resolver: Resolver, domain: str) -> list[str]:
    try:
        return await resolver.mx(domain)
    except Exception:
        return []


def advice(result: MtaSts, has_mail: bool) -> list[str]:
    """Plain-language next steps, most urgent first. A domain that receives no mail is not nagged about it."""
    out: list[str] = []
    if result.state == "none":
        if has_mail:
            out.append(
                "No MTA-STS policy. Without one, a mail server sending to this domain can be tricked into dropping encryption. "
                "Publish a policy in testing mode first, then switch it to enforce once the reports are clean."
            )
        return out
    if result.state == "unreadable":
        out.extend(result.issues)
        return out
    if result.mode == "enforce" and result.uncovered_mx:
        out.append(
            f"The MTA-STS policy is enforced but does not list {', '.join(result.uncovered_mx[:3])}, a mail server this domain really uses. Senders that follow the policy will refuse to deliver to it. "
            "Add it to the policy, and raise the id in the DNS record so senders reload the file."
        )
    elif result.uncovered_mx:
        out.append(
            f"The policy does not list {', '.join(result.uncovered_mx[:3])}. Add it before switching the policy to enforce, or mail to it will be refused."
        )
    if result.mode == "testing":
        out.append("The MTA-STS policy is in testing mode: senders only report problems. When the reports are clean, change it to enforce.")
    elif result.mode == "none":
        out.append("The MTA-STS policy is set to none, which switches protection off.")
    if result.max_age is not None and result.max_age < MIN_MAX_AGE and result.mode in ("enforce", "testing"):
        out.append(
            f"The policy is remembered for only {result.max_age // 60} minutes. Raise max_age to at least a week ({GOOD_MAX_AGE}) once enforcing."
        )
    out.extend(i for i in result.issues if i not in out)
    return out
